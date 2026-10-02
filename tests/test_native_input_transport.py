"""Real pinned HTTPS transport with independent controller and worker material."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_native_reviewed_preparation import NOW, PROJECT, SOURCE
from test_native_reviewed_runtime import _world

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers import native_transfer
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.tls import load_or_create_loopback_tls


def test_https_download_is_scoped_and_does_not_claim(tmp_path: Path) -> None:
    world, plane, _, _ = _world(tmp_path)
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    server = LoopbackWorkerServer(
        world.database,
        plane.artifacts,
        hmac_key=world.hmac_key,
        project_id=PROJECT,
        source=SOURCE,
        clock=lambda: NOW,
        tls=tls,
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
    before = plane.store.last_sequence()
    item = world.request.inputs[0]
    try:
        bad_pin = replace(client, tls_fingerprint="sha256:" + "0" * 64)
        with pytest.raises(WorkerError) as exc:
            bad_pin.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes)
        assert exc.value.code == "tls-fingerprint-mismatch"
        for digest in (
            world.request.code.bundle_digest,
            world.request.environment.dependency_lock_digest,
            world.request.environment.inventory_digest,
        ):
            with plane.artifacts.open(digest) as handle:
                material = handle.read()
            assert client.fetch_native_input(digest=digest, size_bytes=len(material)) == material
        payload = client.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes)
        (tmp_path / "worker-cas").mkdir()
        worker_cas = LocalArtifactStore(tmp_path / "worker-cas")
        assert worker_cas.put_bytes(payload).digest == item.digest
        # Response-loss replay has no claim, grant consumption or process start.
        assert client.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes) == payload
        other = plane.artifacts.put_bytes(b"unplanned")
        with pytest.raises(WorkerError, match="refused"):
            client.fetch_native_input(digest=other.digest, size_bytes=other.size_bytes)
        with pytest.raises(WorkerError, match="refused"):
            client.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes + 1)
        wrong = replace(client, session=server.session_for("worker.other"))
        with pytest.raises(WorkerError, match="refused"):
            wrong.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes)
        assert plane.store.last_sequence() == before
        plane.revoke_grant(
            grant_id="grant.native",
            actor_id=world.request.actor_id,
            event_id="evt.revoke",
        )
        with pytest.raises(WorkerError, match="refused"):
            client.fetch_native_input(digest=item.digest, size_bytes=item.size_bytes)
    finally:
        server.stop()
        plane.store.close()


def test_claimed_expired_lease_cannot_fetch(tmp_path: Path) -> None:
    world, plane, _, _ = _world(tmp_path)
    assert plane.poll(worker_id=world.request.worker_id, grant_token=world.token) is not None
    plane.clock = lambda: NOW + timedelta(seconds=61)
    item = world.request.inputs[0]
    with pytest.raises(WorkerError) as exc:
        plane.authorize_native_input_fetch(
            worker_id=world.request.worker_id,
            grant_token=world.token,
            digest=item.digest,
            size_bytes=item.size_bytes,
        )
    assert exc.value.code == "lease-expired"
    plane.store.close()


def test_cancelled_run_denies_fetch_without_claim(tmp_path: Path) -> None:
    world, plane, _, _ = _world(tmp_path)
    request = world.request
    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
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
    _lifecycle(run, request, "run.cancel.requested", {"reasonCode": "user-requested"})
    before = plane.store.last_sequence()
    item = request.inputs[0]
    with pytest.raises(WorkerError) as exc:
        plane.authorize_native_input_fetch(
            worker_id=request.worker_id,
            grant_token=world.token,
            digest=item.digest,
            size_bytes=item.size_bytes,
        )
    assert exc.value.code == "transfer-cancel-requested"
    assert plane.store.last_sequence() == before
    plane.store.close()


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1", "https://user:secret@host", "https://host/?x=1"]
)
def test_credentials_require_tls_origin(url: str) -> None:
    client = WorkerClient(url, "worker", "session", "grant")
    with pytest.raises(WorkerError) as exc:
        client.fetch_native_input(digest="sha256:" + "0" * 64, size_bytes=0)
    assert exc.value.code == "tls-required"


@pytest.mark.parametrize("fault", ["disconnect", "short", "oversize", "digest", "refused"])
def test_retry_and_response_bounds(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    calls: list[int] = []
    reads: list[int] = []
    closed: list[int] = []

    class Response:
        status = 403 if fault == "refused" else 200

        def getheader(self, name: str) -> str:
            return "1000000000" if fault == "oversize" else "4"

        def read(self, limit: int) -> bytes:
            reads.append(limit)
            return b"" if fault == "short" else b"evil"

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
        client.fetch_native_input(
            digest="sha256:" + hashlib.sha256(b"good").hexdigest(), size_bytes=4
        )
    transient = fault in {"disconnect", "short"}
    assert len(calls) == (3 if transient else 1)
    assert len(closed) == len(calls)
    assert all(limit == 5 for limit in reads)
    assert (
        exc.value.code
        == {
            "disconnect": "http-disconnect",
            "short": "http-disconnect",
            "oversize": "transfer-size-mismatch",
            "digest": "transfer-digest-mismatch",
            "refused": "transfer-refused",
        }[fault]
    )
