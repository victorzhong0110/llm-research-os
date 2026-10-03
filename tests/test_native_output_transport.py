"""Scoped HTTPS completion, receipt recovery and publication-time authorization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_native_reviewed_preparation import NOW, PROJECT, SOURCE
from test_native_reviewed_runtime import _world

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import request_digest
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers import native_output, native_transfer
from llm_research_os.workers.client import WorkerClient, _connection
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.native_claim import NativeControllerContext
from llm_research_os.workers.tls import load_or_create_loopback_tls


def _payload(world):  # type: ignore[no-untyped-def]
    request = world.request
    return canonical_json(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeReviewedTaskOutput",
            "requestDigest": request_digest(request),
            "taskId": request.task_id,
            "runId": request.run_id,
            "attemptId": request.attempt_id,
            "output": {"rows": 1},
        }
    ).encode()


def _transport(tmp_path):  # type: ignore[no-untyped-def]
    world, plane, spec, registry = _world(tmp_path)
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    clock = [NOW]
    server = LoopbackWorkerServer(
        world.database,
        plane.artifacts,
        hmac_key=world.hmac_key,
        project_id=PROJECT,
        source=SOURCE,
        clock=lambda: clock[0],
        tls=tls,
        native_context=NativeControllerContext(spec, registry),
    )
    server.start()
    client = WorkerClient(
        server.base_url,
        world.request.worker_id,
        server.session_for(world.request.worker_id),
        world.token,
        ca_path=tls.cert_path,
        tls_fingerprint=tls.fingerprint,
    )
    return world, plane, tls, clock, server, client


def test_scoped_upload_replay_and_controller_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, tls, clock, server, client = _transport(tmp_path)
    payload = _payload(world)
    (tmp_path / "worker-cas").mkdir()
    worker_cas = LocalArtifactStore(tmp_path / "worker-cas")
    artifact = worker_cas.put_bytes(payload)
    try:
        with pytest.raises(WorkerError, match="refused"):
            client.upload_native_output(lease_id="lease.grant.native", payload=payload)
        claim = client.poll()
        assert claim is not None
        lease = claim["leaseId"]
        before = plane.store.last_sequence()
        wrong = replace(client, session=server.session_for("worker.other"))
        with pytest.raises(WorkerError, match="refused"):
            wrong.upload_native_output(lease_id=lease, payload=payload)
        bad_pin = replace(client, tls_fingerprint="sha256:" + "0" * 64)
        with pytest.raises(WorkerError) as exc:
            bad_pin.upload_native_output(lease_id=lease, payload=payload)
        assert exc.value.code == "tls-fingerprint-mismatch"
        receipt = client.upload_native_output(lease_id=lease, payload=payload)
        assert receipt["digest"] == artifact.digest
        assert receipt["resultDigest"] == content_digest(json.loads(payload))
        assert receipt["sequence"] == before + 1
        assert plane.rebuild().lease(lease).status == "completed"
        assert (
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)
            .rebuild()
            .snapshot.status.value
            == "running"
        )
        # Neither legacy route can bypass native output validation.
        with pytest.raises(WorkerError):
            client.put_artifact(payload)
        with pytest.raises(WorkerError):
            client.complete(
                lease_id=lease,
                result_digest=receipt["resultDigest"],
                artifact_digest=artifact.digest,
            )
        changed = _payload(world).replace(b'"rows":1', b'"rows":2')
        with pytest.raises(WorkerError, match="refused"):
            client.upload_native_output(lease_id=lease, payload=changed)
        assert not plane.artifacts.exists("sha256:" + hashlib.sha256(changed).hexdigest())
        plane.revoke_grant(
            grant_id="grant.native", actor_id=world.request.actor_id, event_id="evt.revoke.output"
        )
        clock[0] = NOW + timedelta(seconds=61)
        before_replay = plane.store.last_sequence()
        port = server.port
        server.stop()
        server = LoopbackWorkerServer(
            world.database,
            plane.artifacts,
            hmac_key=world.hmac_key,
            project_id=PROJECT,
            source=SOURCE,
            clock=lambda: clock[0],
            tls=tls,
            port=port,
        )
        server.start()
        # A completed receipt replay needs no temporary disk and no live authority.
        monkeypatch.setattr(
            native_output.os, "statvfs", lambda path: SimpleNamespace(f_bavail=0, f_frsize=4096)
        )
        assert client.upload_native_output(lease_id=lease, payload=payload) == receipt
        assert plane.store.last_sequence() == before_replay
        assert plane.rebuild().grant("grant.native").consumed_lease_id == lease
    finally:
        server.stop()
        plane.store.close()


def test_lost_completion_response_retries_without_new_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, _, clock, server, client = _transport(tmp_path)
    try:
        claim = client.poll()
        assert claim is not None
        before = plane.store.last_sequence()
        original = native_transfer._connection
        calls = []

        class DropResponse:
            def __init__(self, connection):  # type: ignore[no-untyped-def]
                self.connection = connection

            def request(self, *args):  # type: ignore[no-untyped-def]
                self.connection.request(*args)

            def getresponse(self):  # type: ignore[no-untyped-def]
                response = self.connection.getresponse()
                response.read()
                # Lose the successful acknowledgement, then expire the lease.
                clock[0] = NOW + timedelta(seconds=61)
                raise OSError("completion response lost")

            def close(self):  # type: ignore[no-untyped-def]
                self.connection.close()

        def connect(*args):  # type: ignore[no-untyped-def]
            calls.append(1)
            connection = original(*args)
            return DropResponse(connection) if len(calls) == 1 else connection

        monkeypatch.setattr(native_transfer, "_connection", connect)
        receipt = replace(client, retries=999).upload_native_output(
            lease_id=claim["leaseId"], payload=_payload(world)
        )
        assert len(calls) == 2
        assert plane.store.last_sequence() == before + 1
        assert receipt["sequence"] == before + 1
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["revoked", "expired", "cancelled", "foreign-run", "noncanonical", "disk", "lock"]
)
def test_output_refusals_do_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    world, plane, _, clock, server, client = _transport(tmp_path)
    try:
        claim = client.poll()
        assert claim is not None
        payload = _payload(world)
        if fault == "revoked":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.output",
            )
        elif fault == "expired":
            clock[0] += timedelta(seconds=61)
        elif fault == "cancelled":
            run = RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)
            _start_run(run, world.request)
            _lifecycle(run, world.request, "run.cancel.requested", {"reasonCode": "user-requested"})
        elif fault == "foreign-run":
            document = json.loads(payload)
            document["runId"] = "run.foreign"
            payload = canonical_json(document).encode()
        elif fault == "noncanonical":
            payload = b" " + payload
        elif fault == "disk":
            monkeypatch.setattr(
                native_output.os, "statvfs", lambda path: SimpleNamespace(f_bavail=0, f_frsize=4096)
            )
        elif fault == "lock":
            victim = tmp_path / "unrelated"
            victim.write_bytes(b"preserve")
            native_output.output_lock_path(world.database).unlink()
            native_output.output_lock_path(world.database).symlink_to(victim)
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            client.upload_native_output(lease_id=claim["leaseId"], payload=payload)
        assert plane.store.last_sequence() == before
        assert plane.rebuild().lease(claim["leaseId"]).status == "leased"
        assert not plane.artifacts.exists("sha256:" + hashlib.sha256(payload).hexdigest())
        if fault == "lock":
            assert victim.read_bytes() == b"preserve"
    finally:
        server.stop()
        plane.store.close()


def _start_run(run, request):  # type: ignore[no-untyped-def]
    if run.rebuild().snapshot is not None:
        return
    _lifecycle(
        run,
        request,
        "run.queued",
        {
            "workflowId": request.workflow_id,
            "specDigest": request.spec_digest,
            "registryDigest": request.registry_digest,
            "planDigest": request.plan_digest,
            "decisionDigest": request.decision_digest,
            "authorizationEventId": request.authorization_event_id,
            "authorizationSequence": request.authorization_sequence,
            "maxAttempts": 1,
        },
    )


@pytest.mark.parametrize("fault", ["digest", "size", "encoding"])
def test_wire_bounds_before_publication(tmp_path: Path, fault: str) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        claim = client.poll()
        assert claim is not None
        payload = _payload(world)
        headers = {
            "Authorization": f"Bearer {client.session}",
            "Content-Type": "application/json",
            "X-ResearchOS-Grant": world.token,
            "X-ResearchOS-Lease": claim["leaseId"],
            "X-ResearchOS-Artifact": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
        if fault == "digest":
            headers["X-ResearchOS-Artifact"] = "sha256:" + "0" * 64
        elif fault == "size":
            headers["Content-Length"] = str(world.request.limits.artifact_bytes + 1)
        else:
            headers["Content-Encoding"] = "gzip"
        connection = _connection(
            native_transfer._origin(client), client.ca_path, client.tls_fingerprint
        )
        before = plane.store.last_sequence()
        try:
            connection.request("POST", "/v0alpha1/native/outputs", payload, headers)
            response = connection.getresponse()
            assert response.status == 400
            response.read()
        finally:
            connection.close()
        assert plane.store.last_sequence() == before
        assert plane.rebuild().lease(claim["leaseId"]).status == "leased"
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("race", ["revocation-after-write", "cancel-before-append"])
def test_publication_rechecks_authority_and_log_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    world, plane, _, _ = _world(tmp_path)
    try:
        request = world.request
        run = RunControl(plane.store, project_id=PROJECT, run_id=request.run_id)
        _start_run(run, request)
        claim = plane.poll(worker_id=request.worker_id, grant_token=world.token)
        assert claim is not None
        payload = _payload(world)
        if race == "revocation-after-write":
            original = LocalArtifactStore.put_bytes

            def publish(store, payload, **kwargs):  # type: ignore[no-untyped-def]
                record = original(store, payload, **kwargs)
                plane.revoke_grant(
                    grant_id="grant.native", actor_id=request.actor_id, event_id="evt.race.revoke"
                )
                return record

            monkeypatch.setattr(LocalArtifactStore, "put_bytes", publish)
        else:
            original_append = plane._control.append
            raced = []

            def append(document, **kwargs):  # type: ignore[no-untyped-def]
                if document["type"] == "work.completed" and not raced:
                    raced.append(True)
                    _lifecycle(
                        run, request, "run.cancel.requested", {"reasonCode": "user-requested"}
                    )
                return original_append(document, **kwargs)

            monkeypatch.setattr(plane._control, "append", append)
        with pytest.raises(WorkerError):
            native_output.complete_native_output(
                plane,
                worker_id=request.worker_id,
                grant_token=world.token,
                lease_id=claim.lease_id,
                digest="sha256:" + hashlib.sha256(payload).hexdigest(),
                payload=payload,
            )
        assert plane.store.get_event(f"evt.work.completed.{claim.lease_id}") is None
        assert plane.rebuild().lease(claim.lease_id).status == "leased"
    finally:
        plane.store.close()


@pytest.mark.parametrize(
    "fault",
    [
        "disconnect",
        "short",
        "oversize",
        "refused",
        "invalid-json",
        "large",
        "bad-length",
        "bool-sequence",
        "foreign-lease",
    ],
)
def test_receipt_reads_and_retries_are_bounded(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    payload = b'{"output":1}'
    lease = "lease.test"
    receipt = {
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "sizeBytes": len(payload),
        "resultDigest": content_digest(json.loads(payload)),
        "leaseId": "lease.other" if fault == "foreign-lease" else lease,
        "eventId": f"evt.work.completed.{lease}",
        "type": "work.completed",
        "sequence": True if fault == "bool-sequence" else 1,
    }
    body = b"invalid" if fault == "invalid-json" else json.dumps(receipt).encode()
    calls, reads, closed = [], [], []

    class Response:
        status = 403 if fault == "refused" else 200

        def getheader(self, name: str, default: str) -> str:
            if fault == "large":
                return "4097"
            if fault == "bad-length":
                return "invalid"
            return str(len(body))

        def read(self, limit: int) -> bytes:
            reads.append(limit)
            if fault == "short":
                return body[:-1]
            return body + b" " if fault == "oversize" else body

    class Connection:
        def request(self, *args: object) -> None:
            calls.append(1)
            if fault == "disconnect":
                raise OSError("disconnected")

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            closed.append(1)

    monkeypatch.setattr(native_transfer, "_connection", lambda *args: Connection())
    client = WorkerClient("https://host", "worker", "session", "grant", retries=999)
    with pytest.raises(WorkerError) as exc:
        client.upload_native_output(lease_id=lease, payload=payload)
    assert len(calls) == (3 if fault in {"disconnect", "short"} else 1)
    assert len(closed) == len(calls)
    assert all(limit == len(body) + 1 for limit in reads)
    assert not reads if fault in {"large", "bad-length", "refused", "disconnect"} else reads
    assert exc.value.code == (
        "http-disconnect"
        if fault in {"disconnect", "short"}
        else "transfer-refused"
        if fault == "refused"
        else "transfer-receipt-invalid"
    )


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_completed_receipt_requires_original_cas_bytes(tmp_path: Path, damage: str) -> None:
    from llm_research_os.artifacts.store import storage_key_for

    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        claim = client.poll()
        assert claim is not None
        payload = _payload(world)
        receipt = client.upload_native_output(lease_id=claim["leaseId"], payload=payload)
        before = plane.store.last_sequence()
        path = plane.artifacts.root / storage_key_for(receipt["digest"])
        if damage == "missing":
            path.unlink()
        else:
            path.write_bytes(b"changed")
        with pytest.raises(WorkerError, match="refused"):
            client.upload_native_output(lease_id=claim["leaseId"], payload=payload)
        assert plane.store.last_sequence() == before
        assert not path.exists() if damage == "missing" else path.read_bytes() == b"changed"
    finally:
        server.stop()
        plane.store.close()


def test_output_publication_lock_refuses_concurrent_controller(tmp_path: Path) -> None:
    database = tmp_path / "events.db"
    with (
        native_output.output_lock(database),
        pytest.raises(WorkerError, match="busy"),
        native_output.output_lock(database),
    ):
        pytest.fail("second controller acquired the publication lock")
    with native_output.output_lock(database):
        assert native_output.output_lock_path(database).stat().st_size == 0
