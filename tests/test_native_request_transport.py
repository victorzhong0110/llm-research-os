"""Full native request context is reconstructed without creating launch authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_native_output_transport import _payload, _start_run, _transport
from test_native_reviewed_preparation import PROJECT
from test_native_reviewed_runtime import _world

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import request_digest
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers import native_transfer
from llm_research_os.workers.client import WorkerClient, _connection
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_request import native_request_from_binding
from llm_research_os.workers.tokens import parse_rfc3339


def test_bound_request_fetch_preserves_scope_and_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: pytest.fail("request fetch spawned a process")
    )
    expected = world.request.model_dump(mode="json", by_alias=True, exclude_none=True)
    try:
        before = plane.store.last_sequence()
        assert client.fetch_native_request() == expected
        assert client.fetch_native_request() == expected
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        assert request_digest(world.request) == content_digest(expected)
        assert (
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)
            .rebuild()
            .snapshot
            is None
        )
        claim = client.poll()
        assert claim is not None
        after_claim = plane.store.last_sequence()
        assert client.fetch_native_request() == expected
        assert plane.store.last_sequence() == after_claim
        payload = json.loads(_payload(world))
        payload["requestDigest"] = "jcs-sha256:" + "0" * 64
        bad = canonical_json(payload).encode()
        with pytest.raises(WorkerError, match="refused"):
            client.upload_native_output(lease_id=claim["leaseId"], payload=bad)
        assert plane.store.last_sequence() == after_claim
        assert not plane.artifacts.exists("sha256:" + hashlib.sha256(bad).hexdigest())
        with pytest.raises(WorkerError, match="binding differs"):
            replace(client, worker_id="worker.other").fetch_native_request()
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["revoked", "expired", "cancelled", "session", "claim-expired", "completed"]
)
def test_request_refuses_inactive_authority(tmp_path: Path, fault: str) -> None:
    world, plane, _, clock, server, client = _transport(tmp_path)
    try:
        if fault == "revoked":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.request",
            )
        elif fault == "expired":
            grant = plane.rebuild().grant("grant.native")
            assert grant is not None
            clock[0] = parse_rfc3339(grant.expires_at)
        elif fault == "cancelled":
            run = RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)
            _start_run(run, world.request)
            _lifecycle(run, world.request, "run.cancel.requested", {"reasonCode": "user-requested"})
        elif fault == "session":
            client = replace(client, session=server.session_for("worker.other"))
        else:
            claim = client.poll()
            assert claim is not None
            if fault == "claim-expired":
                clock[0] += timedelta(seconds=61)
            else:
                client.upload_native_output(lease_id=claim["leaseId"], payload=_payload(world))
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            client.fetch_native_request()
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "sequence",
        "project",
        "image",
        "task",
        "config",
        "runtime",
        "inputs",
        "nonhuman",
        "capability",
        "type",
    ],
)
def test_request_rebuild_refuses_substitution(tmp_path: Path, fault: str) -> None:
    _, plane, _, _ = _world(tmp_path)
    try:
        fold = plane.rebuild()
        grant = fold.grant("grant.native")
        assert grant is not None
        queued = fold.queued_work(grant.task_id, grant.attempt_id)
        assert queued is not None
        project = PROJECT
        if fault in {"nonhuman", "capability"}:
            from test_native_reviewed_preparation import _authorization_event

            old = plane.store.get_event(grant.authorization_event_id)
            assert old is not None
            data = old.event.data.payload
            document = _authorization_event(
                data["binding"]["specDigest"],
                data["binding"]["registryDigest"],
                data["binding"]["planDigest"],
                "execute.local" if fault == "capability" else "execute.native",
            )
            document["id"] = "evt.auth.substitution"
            if fault == "nonhuman":
                document["data"]["actor"] = {"id": "agent.untrusted", "kind": "ai"}
            stored = plane.store.append(document)
            grant = replace(
                grant,
                authorization_event_id=stored.event.id,
                authorization_sequence=str(stored.sequence),
            )
        elif fault == "type":
            grant = replace(
                grant, authorization_event_id="evt.worker.native", authorization_sequence="2"
            )
        elif fault == "missing":
            grant = replace(grant, authorization_event_id="evt.missing")
        elif fault == "sequence":
            grant = replace(grant, authorization_sequence="2")
        elif fault == "project":
            project = "project.foreign"
        elif fault == "image":
            grant = replace(grant, image_digest="sha256:" + "0" * 64)
        elif fault == "task":
            queued = replace(queued, task_id="task.foreign")
        elif fault == "config":
            config = json.loads(json.dumps(queued.config))
            config["limits"]["wallTimeSeconds"] += 1
            queued = replace(queued, config=config)
        elif fault == "runtime":
            queued = replace(queued, runtime="python-sandbox")
        else:
            queued = replace(queued, inputs={"injected": "value"})
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="native request"):
            native_request_from_binding(plane.store, project_id=project, grant=grant, queued=queued)
        assert plane.store.last_sequence() == before
    finally:
        plane.store.close()


@pytest.mark.parametrize(
    "fault",
    ["disconnect", "short", "oversize", "refused", "digest", "invalid", "noncanonical", "size"],
)
def test_request_client_bounds_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    world, plane, _, _ = _world(tmp_path)
    try:
        document = world.request.model_dump(mode="json", by_alias=True, exclude_none=True)
        body = canonical_json(document).encode()
        if fault == "invalid":
            document["unreviewed"] = True
            body = canonical_json(document).encode()
        elif fault == "noncanonical":
            body = b" " + body
        calls, reads, closed = [], [], []

        class Response:
            status = 403 if fault == "refused" else 200

            def getheader(self, name: str, default: str) -> str:
                if name == "Content-Length":
                    return "65537" if fault == "size" else str(len(body))
                return "jcs-sha256:" + "0" * 64 if fault == "digest" else content_digest(document)

            def read(self, limit: int) -> bytes:
                reads.append(limit)
                return (
                    body[:-1] if fault == "short" else body + b" " if fault == "oversize" else body
                )

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
        client = WorkerClient(
            "https://host", world.request.worker_id, "session", "grant", retries=99
        )
        with pytest.raises(WorkerError):
            client.fetch_native_request()
        assert len(calls) == (3 if fault in {"disconnect", "short"} else 1)
        assert len(calls) == len(closed)
        assert all(limit == len(body) + 1 for limit in reads)
        assert not reads if fault in {"size", "refused", "disconnect"} else reads
    finally:
        plane.store.close()


def test_new_results_refuse_a_different_controller_revision(tmp_path: Path) -> None:
    world, plane, _, _ = _world(tmp_path)
    try:
        before = plane.store.last_sequence()
        plane.experiment_revision = 2
        with pytest.raises(WorkerError, match="binding differs"):
            plane.native_reviewed_request(
                worker_id=world.request.worker_id, grant_token=world.token
            )
        plane.experiment_revision = 1
        claim = plane.poll(worker_id=world.request.worker_id, grant_token=world.token)
        assert claim is not None
        claimed_sequence = plane.store.last_sequence()
        plane.experiment_revision = 2
        payload = _payload(world)
        with pytest.raises(WorkerError, match="binding differs"):
            plane.authorize_native_output(
                worker_id=world.request.worker_id,
                grant_token=world.token,
                lease_id=claim.lease_id,
                digest="sha256:" + hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            )
        assert plane.store.last_sequence() == claimed_sequence > before
        plane.experiment_revision = 1
        from llm_research_os.workers.native_output import complete_native_output

        receipt = complete_native_output(
            plane,
            worker_id=world.request.worker_id,
            grant_token=world.token,
            lease_id=claim.lease_id,
            digest="sha256:" + hashlib.sha256(payload).hexdigest(),
            payload=payload,
        )
        plane.experiment_revision = 2
        assert (
            complete_native_output(
                plane,
                worker_id=world.request.worker_id,
                grant_token=world.token,
                lease_id=claim.lease_id,
                digest=receipt["digest"],
                payload=payload,
            )
            == receipt
        )
        assert plane.store.last_sequence() == claimed_sequence + 1
    finally:
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["body", "deep", "encoding", "media", "duplicate", "query", "size"]
)
def test_request_wire_refuses_ambiguous_or_invalid_requests(tmp_path: Path, fault: str) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    connection = _connection(
        native_transfer._origin(client), client.ca_path, client.tls_fingerprint
    )
    try:
        body = (
            b'{"scope":"all"}'
            if fault == "body"
            else b"[" * 1100 + b"]" * 1100
            if fault == "deep"
            else b"{}"
        )
        path = (
            "/v0alpha1/native/request?scope=all" if fault == "query" else "/v0alpha1/native/request"
        )
        before = plane.store.last_sequence()
        connection.putrequest("POST", path)
        connection.putheader("Authorization", f"Bearer {client.session}")
        if fault == "duplicate":
            connection.putheader("Authorization", f"Bearer {client.session}")
        connection.putheader("X-ResearchOS-Grant", client.grant_token)
        connection.putheader(
            "Content-Type", "text/plain" if fault == "media" else "application/json"
        )
        connection.putheader("Content-Length", "4097" if fault == "size" else str(len(body)))
        if fault == "encoding":
            connection.putheader("Transfer-Encoding", "")
        connection.endheaders(body)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        connection.close()
        server.stop()
        plane.store.close()
