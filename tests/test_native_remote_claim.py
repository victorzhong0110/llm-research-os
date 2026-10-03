"""Real TLS dispatch binding, partial lifecycle persistence and consumed-grant replay."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_native_output_transport import _transport
from test_native_reviewed_preparation import PROJECT

from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers import client as client_module
from llm_research_os.workers import native_claim
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.native_output import output_lock


def _run(world, plane):  # type: ignore[no-untyped-def]
    return RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)


def test_claim_records_queue_but_never_starts_and_restart_only_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, tls, clock, server, client = _transport(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("claim started a process"))
    try:
        before = plane.store.last_sequence()
        claim = client.poll()
        assert claim is not None and claim["resumed"] is False
        assert claim["configDigest"] == world.request.config_digest
        assert (
            plane.store.last_sequence() == before + 6
        )  # 3 lifecycle + grant consumption + lease + claim
        snapshot = _run(world, plane).rebuild().snapshot
        assert snapshot.status.value == "running"
        assert len(snapshot.attempts) == 1
        assert snapshot.attempts[0].status.value == "queued"
        assert snapshot.max_attempts == 1
        assert not list(tmp_path.rglob("*.identity.json"))
        head = plane.store.last_sequence()
        context = server._native_context
        port = server.port
        server.stop()
        server = LoopbackWorkerServer(
            world.database,
            plane.artifacts,
            hmac_key=world.hmac_key,
            project_id=PROJECT,
            source=plane.source,
            clock=lambda: clock[0],
            port=port,
            tls=tls,
            native_context=context,
        )
        server.start()
        replay = replace(client).poll()
        assert replay["leaseId"] == claim["leaseId"] and replay["resumed"] is True
        assert plane.store.last_sequence() == head
        assert _run(world, plane).rebuild().snapshot == snapshot
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["context", "spec", "registry", "tls", "revoke", "lock"])
def test_dispatch_refusals_precede_lifecycle_and_consumption(tmp_path: Path, fault: str) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    lock = None
    try:
        if fault == "context":
            server._native_context = None
        elif fault == "spec":
            context = server._native_context
            changed = context.spec.model_copy(deep=True)
            changed.metadata.title += " changed"
            server._native_context = replace(context, spec=changed)
        elif fault == "registry":
            server._native_context = replace(server._native_context, registry=BlockRegistry())
        elif fault == "tls":
            # The socket still uses real TLS; the capability gate itself refuses.
            server._tls = None
        elif fault == "revoke":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.claim",
            )
        else:
            lock = output_lock(world.database)
            lock.__enter__()
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.store.last_sequence() == before
        assert _run(world, plane).rebuild().snapshot is None
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("after", [1, 2, 3])
def test_partial_controller_journal_replays_exact_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    append = native_claim._append_bound
    calls = 0

    def interrupted(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        append(*args, **kwargs)
        calls += 1
        if calls == after:
            raise ValueError("controller crashed after durable fact")

    monkeypatch.setattr(native_claim, "_append_bound", interrupted)
    try:
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.store.last_sequence() == before + after
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        monkeypatch.setattr(native_claim, "_append_bound", append)
        claim = client.poll()
        assert claim is not None and claim["resumed"] is False
        assert plane.store.last_sequence() == before + 6
        assert _run(world, plane).rebuild().snapshot.attempts[0].status.value == "queued"
    finally:
        server.stop()
        plane.store.close()


def test_lost_claim_response_returns_resumed_not_new_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    connect = client_module._connection
    calls = 0

    class DropResponse:
        def __init__(self, connection):  # type: ignore[no-untyped-def]
            self.connection = connection

        def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.connection.request(*args, **kwargs)

        def getresponse(self):  # type: ignore[no-untyped-def]
            response = self.connection.getresponse()
            response.read()
            raise OSError("claim response lost")

        def close(self):  # type: ignore[no-untyped-def]
            self.connection.close()

    def connection(*args):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        conn = connect(*args)
        return DropResponse(conn) if calls == 1 else conn

    monkeypatch.setattr(client_module, "_connection", connection)
    try:
        before = plane.store.last_sequence()
        claim = client.poll()
        assert claim is not None and claim["resumed"] is True
        assert calls == 2 and plane.store.last_sequence() == before + 6
        assert plane.rebuild().grant("grant.native").consumed_lease_id == claim["leaseId"]
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["cancel", "revoke", "unknown"])
def test_partial_queue_cannot_mask_cancellation_or_other_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    original_poll = native_claim.WorkerPlane.poll
    monkeypatch.setattr(
        native_claim.WorkerPlane, "poll", lambda *a, **k: (_ for _ in ()).throw(ValueError("lost"))
    )
    try:
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        run = _run(world, plane)
        if fault == "cancel":
            _lifecycle(run, world.request, "run.cancel.requested", {"reasonCode": "user-requested"})
        elif fault == "revoke":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.claim",
            )
        else:
            _lifecycle(run, world.request, "attempt.started", {}, attempt=True)
            _lifecycle(run, world.request, "attempt.unknown", {"reasonCode": "lost"}, attempt=True)
        before = plane.store.last_sequence()
        monkeypatch.setattr(native_claim.WorkerPlane, "poll", original_poll)
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["query", "extra", "boolean-wait", "wait", "encoding", "large"])
def test_native_poll_wire_is_closed_and_bounded(tmp_path: Path, fault: str) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    try:
        document = {
            "workerId": client.worker_id,
            "grantToken": client.grant_token,
            "waitSeconds": 0,
        }
        path = "/v0alpha1/work/poll"
        if fault == "query":
            path += "?other=1"
        elif fault == "extra":
            document["spec"] = {}
        elif fault == "boolean-wait":
            document["waitSeconds"] = False
        elif fault == "wait":
            document["waitSeconds"] = 1
        elif fault == "large":
            document["padding"] = "x" * 4096
        before = plane.store.last_sequence()
        if fault == "encoding":
            connection = client_module._connection(
                client_module.urlparse(client.base_url), client.ca_path, client.tls_fingerprint
            )
            try:
                connection.request(
                    "POST",
                    path,
                    json.dumps(document).encode(),
                    {
                        "Authorization": f"Bearer {client.session}",
                        "Content-Type": "application/json",
                        "Content-Encoding": "gzip",
                    },
                )
                response = connection.getresponse()
                response.read()
                assert response.status == 400
            finally:
                connection.close()
        else:
            status, _ = client._json("POST", path, document)
            assert status == 400
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        server.stop()
        plane.store.close()


def test_existing_local_run_is_not_a_remote_dispatch(tmp_path: Path) -> None:
    from test_native_output_transport import _start_run

    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        _start_run(_run(world, plane), world.request)
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        server.stop()
        plane.store.close()


def test_stable_lifecycle_id_must_also_match_recorded_binding(tmp_path: Path) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        changed = world.request.model_copy(update={"worker_id": "worker.foreign"})
        native_claim._append_bound(
            _run(world, plane),
            plane,
            changed,
            "run.queued",
            {
                "workflowId": changed.workflow_id,
                "specDigest": changed.spec_digest,
                "registryDigest": changed.registry_digest,
                "planDigest": changed.plan_digest,
                "decisionDigest": changed.decision_digest,
                "authorizationEventId": changed.authorization_event_id,
                "authorizationSequence": changed.authorization_sequence,
                "maxAttempts": 1,
            },
            attempt=False,
        )
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        server.stop()
        plane.store.close()


def test_revocation_during_queueing_prevents_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    append = native_claim._append_bound

    def revoke(*args, **kwargs):  # type: ignore[no-untyped-def]
        append(*args, **kwargs)
        if args[3] == "attempt.queued":
            args[1].revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.claim.during",
            )

    monkeypatch.setattr(native_claim, "_append_bound", revoke)
    try:
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        assert _run(world, plane).rebuild().snapshot.attempts[0].status.value == "queued"
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "boundary", ["work.leased", "work.claimed", "authorization.grant.consumed"]
)
def test_partial_worker_claim_is_always_a_resume_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from llm_research_os.workers.control import WorkerControl

    world, plane, _, _, server, client = _transport(tmp_path)
    original = WorkerControl.append
    crashed = False

    def append(self, document, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal crashed
        result = original(self, document, **kwargs)
        if document["type"] == boundary and not crashed:
            crashed = True
            raise ValueError("crashed after persisted Worker fact")
        return result

    monkeypatch.setattr(WorkerControl, "append", append)
    try:
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        monkeypatch.setattr(WorkerControl, "append", original)
        claim = client.poll()
        assert claim is not None and claim["resumed"] is True
        assert claim["leaseId"] == "lease.grant.native"
        assert plane.store.last_sequence() == before + 6
        assert plane.rebuild().grant("grant.native").consumed_lease_id == claim["leaseId"]
        assert _run(world, plane).rebuild().snapshot.attempts[0].status.value == "queued"
    finally:
        server.stop()
        plane.store.close()


def test_controller_spec_drift_during_queueing_prevents_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    append = native_claim._append_bound

    def drift(*args, **kwargs):  # type: ignore[no-untyped-def]
        append(*args, **kwargs)
        if args[3] == "attempt.queued":
            server._native_context.spec.metadata.title += " changed"

    monkeypatch.setattr(native_claim, "_append_bound", drift)
    try:
        with pytest.raises(WorkerError, match="poll failed"):
            client.poll()
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        assert _run(world, plane).rebuild().snapshot.attempts[0].status.value == "queued"
    finally:
        server.stop()
        plane.store.close()
