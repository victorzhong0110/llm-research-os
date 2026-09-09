from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
from datetime import timedelta
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlparse

import pytest
from test_worker_protocol import (
    HMAC_KEY,
    NOW,
    PROJECT,
    SOURCE,
    TOKEN_CONFIG,
    TOKEN_IMAGE,
    FrozenClock,
    _citation,
    _cpu_spec_with_image,
    _grant_and_queue,
    _plan_args,
    _plane,
    _record_execute_local_authorization,
    _token_args,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli.m2_commands import run_m2
from llm_research_os.cli.worker_commands import run_grants, run_workers
from llm_research_os.events.models import validate_event_document
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.storage import EventStore
from llm_research_os.workers.binding import brick_execution_digest
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.drafts import registered_draft, work_completed_draft
from llm_research_os.workers.errors import (
    WorkerCallError,
    WorkerError,
    WorkerGrantError,
    WorkerPayloadError,
    WorkerRequestError,
    WorkerSandboxError,
)
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.models import (
    MAX_ACCELERATORS,
    WorkerRegisteredPayload,
    parse_worker_payload,
    require_worker_actor,
)
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.requests import validate_worker_register_request
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick
from llm_research_os.workers.tokens import (
    GRANT_TOKEN_VERSION,
    WORKER_SESSION_VERSION,
    _sign,
    issue_grant_token,
    issue_worker_session,
    verify_grant_token,
    verify_worker_session,
)

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-checkpoint"
DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)


def _claims(**overrides: str) -> dict[str, str]:
    base = {
        "v": GRANT_TOKEN_VERSION,
        "keyId": "local.hmac.1",
        "grantId": "grant.cpu.1",
        "grantEventId": "evt.grant.recorded.1",
        "workerId": "worker.loopback.1",
        "taskId": "task.cpu",
        "attemptId": "attempt.worker.1",
        "runId": "run.worker.cpu",
        "nonce": "nonce.cpu.1",
        "exp": "2099-01-01T00:00:00Z",
        "projectId": PROJECT,
        "imageDigest": TOKEN_IMAGE,
        "configDigest": TOKEN_CONFIG,
    }
    base.update(overrides)
    return base


def _raw_token(payload: bytes, *, version: str = GRANT_TOKEN_VERSION) -> str:
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    mac = hmac.new(HMAC_KEY, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{version}.{encoded}.{mac}"


def test_hmac_token_claim_and_encoding_edges() -> None:
    missing_exp = dict(_claims())
    del missing_exp["exp"]
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, _sign(HMAC_KEY, GRANT_TOKEN_VERSION, missing_exp), now=NOW)
    assert captured.value.code == "grant-token-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(
            HMAC_KEY,
            _sign(HMAC_KEY, GRANT_TOKEN_VERSION, _claims(grantId="")),
            now=NOW,
        )
    assert captured.value.code == "grant-token-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(
            HMAC_KEY,
            _sign(HMAC_KEY, GRANT_TOKEN_VERSION, _claims(keyId="other.hmac.1")),
            now=NOW,
        )
    assert captured.value.code == "grant-key-unknown"
    with pytest.raises(WorkerGrantError) as captured:
        verify_worker_session(
            HMAC_KEY,
            _sign(HMAC_KEY, WORKER_SESSION_VERSION, {"v": WORKER_SESSION_VERSION, "workerId": ""}),
        )
    assert captured.value.code == "worker-session-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, _raw_token(b"{"), now=NOW)
    assert captured.value.code == "grant-token-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, _raw_token(b"[1]"), now=NOW)
    assert captured.value.code == "grant-token-invalid"
    bad = "rg1." + ("@" * 8) + "." + ("0" * 64)
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, bad, now=NOW)
    assert captured.value.code in {"grant-hmac-mismatch", "grant-token-invalid"}


def test_plane_unknown_revoke_revoked_issue_and_empty_poll(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        with pytest.raises(WorkerCallError) as captured:
            plane.revoke_grant(
                grant_id="grant.missing",
                actor_id="researcher.alice",
                event_id="evt.grant.revoked.missing",
            )
        assert captured.value.code == "unknown-grant"
        _grant_and_queue(plane, image)
        plane.revoke_grant(
            grant_id="grant.cpu.1",
            actor_id="researcher.alice",
            event_id="evt.grant.revoked.1",
        )
        with pytest.raises(WorkerGrantError) as captured_grant:
            plane.issue_token("grant.cpu.1")
        assert captured_grant.value.code == "grant-revoked"
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        empty_store, _empty_artifacts, empty_plane, _empty_image = _plane(empty_root)
        try:
            event_id, sequence = _citation(empty_plane)
            empty_plane.record_grant(
                grant_id="grant.cpu.1",
                worker_id="worker.loopback.1",
                task_id="task.cpu",
                run_id="run.worker.cpu",
                attempt_id="attempt.worker.1",
                nonce="nonce.cpu.1",
                expires_at="2099-01-01T00:00:00Z",
                actor_id="researcher.alice",
                event_id="evt.grant.recorded.1",
                authorization_event_id=event_id,
                authorization_sequence=sequence,
                image_digest=_empty_image,
                config_digest=brick_execution_digest(image_digest=_empty_image),
                **_plan_args(),
            )
            idle_token = empty_plane.issue_token("grant.cpu.1")
            assert empty_plane.poll(worker_id="worker.loopback.1", grant_token=idle_token) is None
        finally:
            empty_store.__exit__(None, None, None)
    finally:
        store.__exit__(None, None, None)


def test_heartbeat_and_complete_ownership_edges(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        session = issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1")
        foreign = issue_worker_session(HMAC_KEY, worker_id="worker.other.1")
        with pytest.raises(WorkerGrantError) as captured:
            plane.heartbeat(
                worker_id="worker.loopback.1",
                session=foreign,
                lease_id=claimed.lease_id,
            )
        assert captured.value.code == "worker-session-mismatch"
        with pytest.raises(WorkerCallError) as captured:
            plane.heartbeat(
                worker_id="worker.loopback.1",
                session=session,
                lease_id="lease.missing",
            )
        assert captured.value.code == "unknown-lease"
        with pytest.raises(WorkerCallError) as captured:
            plane.expire_lease(lease_id="lease.missing")
        assert captured.value.code == "unknown-lease"
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id="lease.missing",
                result_digest=DIGEST_A,
                artifact_digest=DIGEST_A,
            )
        assert captured.value.code == "unknown-lease"
        with pytest.raises(WorkerCallError) as captured:
            plane.fail(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id="lease.missing",
                reason_code="worker.brick.failed",
            )
        assert captured.value.code == "unknown-lease"
        plane.register(
            worker_id="worker.other.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.2",
        )
        event_id, sequence = _citation(plane)
        plane.record_grant(
            grant_id="grant.cpu.2",
            worker_id="worker.other.1",
            task_id="task.cpu",
            run_id="run.worker.cpu",
            attempt_id="attempt.worker.1",
            nonce="nonce.cpu.2",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.2",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=image,
            config_digest=brick_execution_digest(image_digest=image),
            **_plan_args(),
        )
        other_token = plane.issue_token("grant.cpu.2")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.other.1", grant_token=other_token)
        assert captured.value.code == "lease-conflict"
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.other.1",
                grant_token=other_token,
                lease_id=claimed.lease_id,
                result_digest=DIGEST_A,
                artifact_digest=DIGEST_A,
            )
        assert captured.value.code == "lease-worker-mismatch"
        result = artifacts.put_bytes(b'{"kind":"PythonBrickReport","status":"ok"}')
        first = plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=DIGEST_A,
            artifact_digest=result.digest,
        )
        assert first.event.type == "work.completed"
        other_artifact = artifacts.put_bytes(b'{"kind":"PythonBrickReport","status":"other"}')
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id=claimed.lease_id,
                result_digest=DIGEST_B,
                artifact_digest=other_artifact.digest,
            )
        assert captured.value.code == "complete-mismatch"
        assert plane.poll(worker_id="worker.loopback.1", grant_token=token) is None
        with pytest.raises(WorkerGrantError) as captured_grant:
            plane.poll(worker_id="worker.other.1", grant_token=token)
        assert captured_grant.value.code == "grant-worker-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_stale_lease_is_expired_before_foreign_claim(tmp_path: Path) -> None:
    clock = FrozenClock(NOW)
    store, _artifacts, plane, image = _plane(tmp_path, clock=clock, lease_seconds=1)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        plane.register(
            worker_id="worker.other.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.2",
        )
        event_id, sequence = _citation(plane)
        plane.record_grant(
            grant_id="grant.cpu.2",
            worker_id="worker.other.1",
            task_id="task.cpu",
            run_id="run.worker.cpu",
            attempt_id="attempt.worker.1",
            nonce="nonce.cpu.2",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.2",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=image,
            config_digest=brick_execution_digest(image_digest=image),
            **_plan_args(),
        )
        clock.instant = NOW + timedelta(seconds=120)
        other_token = plane.issue_token("grant.cpu.2")
        resumed = plane.poll(worker_id="worker.other.1", grant_token=other_token)
        assert resumed is not None
        assert resumed.worker_id == "worker.other.1"
        types = [item.event.type for item in store.read_events(limit=40)]
        assert "work.lease.expired" in types
    finally:
        store.__exit__(None, None, None)


def test_grant_token_binding_mismatches(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        _grant_and_queue(plane, image)
        forged_event = issue_grant_token(
            HMAC_KEY,
            **_token_args(plane, "grant.cpu.1", grant_event_id="evt.grant.recorded.other"),
        )
        with pytest.raises(WorkerGrantError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=forged_event)
        assert captured.value.code == "grant-event-mismatch"
        forged_nonce = issue_grant_token(
            HMAC_KEY,
            **_token_args(plane, "grant.cpu.1", nonce="nonce.other"),
        )
        with pytest.raises(WorkerGrantError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=forged_nonce)
        assert captured.value.code == "grant-nonce-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_worker_control_rejects_invalid_drafts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        with pytest.raises(ValueError, match="page_size"):
            WorkerControl(store, project_id=PROJECT, page_size=0)
        with pytest.raises(ValueError, match="page_size"):
            WorkerControl(store, project_id=PROJECT, page_size=True)  # type: ignore[arg-type]
        control = WorkerControl(store, project_id=PROJECT)
        draft = registered_draft(
            project_id=PROJECT,
            worker_id="worker.loopback.1",
            event_id="evt.worker.registered.1",
            time="2026-09-07T12:00:00Z",
            source=SOURCE,
            actor_id="researcher.alice",
        )
        assigned = dict(draft)
        assigned["sequence"] = "1"
        with pytest.raises(WorkerCallError) as captured:
            control.append(assigned)
        assert captured.value.code == "store-assigned-fields"
        with pytest.raises(WorkerPayloadError) as captured_payload:
            control.append({"id": "evt.invalid"})
        assert captured_payload.value.code == "invalid-event"
        foreign = registered_draft(
            project_id="other-project",
            worker_id="worker.loopback.1",
            event_id="evt.worker.registered.1",
            time="2026-09-07T12:00:00Z",
            source=SOURCE,
            actor_id="researcher.alice",
        )
        with pytest.raises(WorkerCallError) as captured:
            control.append(foreign)
        assert captured.value.code == "project-mismatch"
        stored = control.append(draft)
        event = stored.event
        parsed = parse_worker_payload(event)
        assert isinstance(parsed, WorkerRegisteredPayload)
        require_worker_actor(event)
        with pytest.raises(WorkerPayloadError) as captured_payload:
            parse_worker_payload(
                validate_event_document(
                    {
                        **draft,
                        "type": "work.completed",
                        "id": "evt.work.completed.bad",
                        "sequence": "2",
                        "sequencetype": "Integer",
                        "streamversion": 0,
                        "data": {
                            **draft["data"],
                            "actor": {"id": "control.plane", "kind": "system"},
                            "payload": {"leaseId": "lease.x"},
                            "runId": "run.worker.cpu",
                            "attemptId": "attempt.worker.1",
                        },
                    }
                )
            )
        assert captured_payload.value.code == "invalid-payload"
        completed = work_completed_draft(
            project_id=PROJECT,
            lease_id="lease.missing",
            worker_id="worker.loopback.1",
            result_digest=DIGEST_A,
            artifact_digest=DIGEST_A,
            run_id="run.worker.cpu",
            attempt_id="attempt.worker.1",
            event_id="evt.work.completed.missing",
            time="2026-09-07T12:00:00Z",
            source=SOURCE,
        )
        with pytest.raises(WorkerCallError) as captured:
            control.append(completed)
        assert captured.value.code == "unknown-lease"


def test_duplicate_grant_and_work_and_actor_kind(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        _grant_and_queue(plane, image)
        event_id, sequence = _citation(plane)
        with pytest.raises(WorkerCallError) as captured:
            plane.record_grant(
                grant_id="grant.cpu.1",
                worker_id="worker.loopback.1",
                task_id="task.cpu",
                run_id="run.worker.cpu",
                attempt_id="attempt.worker.1",
                nonce="nonce.cpu.1",
                expires_at="2099-01-01T00:00:00Z",
                actor_id="researcher.alice",
                event_id="evt.grant.recorded.dup",
                authorization_event_id=event_id,
                authorization_sequence=sequence,
                image_digest=image,
                config_digest=brick_execution_digest(image_digest=image),
                **_plan_args(),
            )
        assert captured.value.code == "duplicate-grant-id"
        with pytest.raises(WorkerCallError) as captured:
            plane.record_grant(
                grant_id="grant.cpu.missing-worker",
                worker_id="worker.missing.1",
                task_id="task.cpu",
                run_id="run.worker.cpu",
                attempt_id="attempt.worker.1",
                nonce="nonce.cpu.x",
                expires_at="2099-01-01T00:00:00Z",
                actor_id="researcher.alice",
                event_id="evt.grant.recorded.missing",
                authorization_event_id=event_id,
                authorization_sequence=sequence,
                image_digest=image,
                config_digest=brick_execution_digest(image_digest=image),
                **_plan_args(),
            )
        assert captured.value.code == "unknown-worker"
        with pytest.raises(WorkerCallError) as captured:
            plane.enqueue(
                task_id="task.cpu",
                run_id="run.worker.cpu",
                attempt_id="attempt.worker.1",
                image_digest=image,
                event_id="evt.work.queued.dup",
            )
        assert captured.value.code == "duplicate-work"
        plane.revoke_grant(
            grant_id="grant.cpu.1",
            actor_id="researcher.alice",
            event_id="evt.grant.revoked.1",
        )
        with pytest.raises(WorkerCallError) as captured:
            plane.revoke_grant(
                grant_id="grant.cpu.1",
                actor_id="researcher.alice",
                event_id="evt.grant.revoked.2",
            )
        assert captured.value.code == "grant-already-revoked"
    finally:
        store.__exit__(None, None, None)


def test_http_poll_empty_and_client_error_codes(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    with EventStore(database) as store:
        event_id, sequence = _record_execute_local_authorization(store)
        image = artifacts.put(CORPUS / "brick.py")
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.loopback.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.1",
        )
        plane.record_grant(
            grant_id="grant.cpu.1",
            worker_id="worker.loopback.1",
            task_id="task.cpu",
            run_id="run.worker.cpu",
            attempt_id="attempt.worker.1",
            nonce="nonce.cpu.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.1",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=image.digest,
            config_digest=brick_execution_digest(image_digest=image.digest),
            **_plan_args(),
        )
        token = plane.issue_token("grant.cpu.1")
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        with pytest.raises(WorkerError) as captured:
            server.start()
        assert captured.value.code == "server-started"
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
        )
        assert client.poll() is None
        assert client.run_once(artifacts) is None
        with pytest.raises(WorkerError) as captured:
            client.complete(
                lease_id="lease.missing",
                result_digest=DIGEST_A,
                artifact_digest=DIGEST_A,
            )
        assert captured.value.code == "http-complete-failed"
        bad = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token="rg1.x.y",
        )
        with pytest.raises(WorkerError) as captured:
            bad.poll()
        assert captured.value.code == "http-poll-failed"
        unsigned = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session="ws1.x.y",
            grant_token=token,
        )
        with pytest.raises(WorkerError) as captured:
            unsigned.put_artifact(b"payload")
        assert captured.value.code == "http-artifact-failed"
        parsed = urlparse(server.base_url)
        connection = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            connection.request(
                "POST",
                "/v0alpha1/work/poll",
                body=b"[]",
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/json",
                    "Content-Length": "2",
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 400
            assert payload["code"] == "http-invalid"
        finally:
            connection.close()
        length = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            length.request(
                "POST",
                "/v0alpha1/work/poll",
                body=b"{}",
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/json",
                    "Content-Length": "nope",
                },
            )
            length_response = length.getresponse()
            length_payload = json.loads(length_response.read().decode("utf-8"))
            assert length_response.status == 400
            assert length_payload["code"] == "http-invalid"
        finally:
            length.close()
        huge = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            huge.request(
                "POST",
                "/v0alpha1/artifacts",
                body=b"",
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(268_435_457),
                },
            )
            huge_response = huge.getresponse()
            huge_payload = json.loads(huge_response.read().decode("utf-8"))
            assert huge_response.status == 400
            assert huge_payload["code"] == "http-too-large"
        finally:
            huge.close()
        mismatch = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            body = json.dumps(
                {"workerId": "worker.other.1", "grantToken": token, "waitSeconds": 0},
                ensure_ascii=True,
            ).encode("utf-8")
            mismatch.request(
                "POST",
                "/v0alpha1/work/poll",
                body=body,
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            mismatch_response = mismatch.getresponse()
            mismatch_payload = json.loads(mismatch_response.read().decode("utf-8"))
            assert mismatch_response.status == 401
            assert mismatch_payload["code"] == "worker-session-mismatch"
        finally:
            mismatch.close()
        missing_field = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            empty = json.dumps({"workerId": "", "grantToken": token}, ensure_ascii=True).encode(
                "utf-8"
            )
            missing_field.request(
                "POST",
                "/v0alpha1/work/poll",
                body=empty,
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(empty)),
                },
            )
            missing_response = missing_field.getresponse()
            missing_payload = json.loads(missing_response.read().decode("utf-8"))
            assert missing_response.status == 400
            assert missing_payload["code"] == "http-invalid"
        finally:
            missing_field.close()
    finally:
        server.stop()


def test_run_once_failed_and_unknown_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    fail_brick = tmp_path / "fail.py"
    fail_brick.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    image = artifacts.put(fail_brick)
    spec = _cpu_spec_with_image(image.digest)
    registry = build_registry([CORPUS / "block.json"])
    with EventStore(database) as store:
        _record_execute_local_authorization(store, spec, registry)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.loopback.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.1",
        )
        token = _grant_and_queue(plane, image.digest, spec=spec, registry=registry)
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
        )
        with pytest.raises(WorkerError) as captured:
            client.run_once(artifacts)
        assert captured.value.code == "worker.brick.failed"
    finally:
        server.stop()

    class _Unknown:
        disposition = SandboxDisposition.UNKNOWN
        reason_code = "worker.process.timeout"
        result_digest = None
        stdout = b""

    monkeypatch.setattr(
        "llm_research_os.workers.client.execute_python_brick",
        lambda *_args, **_kwargs: _Unknown(),
    )
    database_b = tmp_path / "unknown.db"
    with EventStore(database_b) as store:
        _record_execute_local_authorization(store, spec, registry)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.loopback.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.1",
        )
        token = _grant_and_queue(plane, image.digest, spec=spec, registry=registry)
    server = LoopbackWorkerServer(
        database_b,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
        )
        with pytest.raises(WorkerError) as captured:
            client.run_once(artifacts)
        assert captured.value.code == "worker.process.timeout"
    finally:
        server.stop()


def test_sandbox_oserror_too_large_and_output_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "ok.py"
    brick.write_text("print('x')\n", encoding="utf-8")
    digest = artifacts.put(brick).digest

    def _raise_oserror(*_args: object, **_kwargs: object) -> object:
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "Popen", _raise_oserror)
    lost = execute_python_brick(artifacts, digest)
    assert lost.disposition is SandboxDisposition.UNKNOWN
    assert lost.reason_code == "worker.process.lost"
    monkeypatch.undo()
    huge = tmp_path / "huge.py"
    huge.write_bytes(b"x" * 70_000)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_python_brick(artifacts, artifacts.put(huge).digest)
    assert captured.value.code == "brick-too-large"
    noisy = tmp_path / "noisy.py"
    noisy.write_text("print('x' * 70000)\n", encoding="utf-8")
    overflow = execute_python_brick(artifacts, artifacts.put(noisy).digest)
    assert overflow.reason_code == "worker.brick.output-too-large"


def test_request_accelerators_must_be_unique() -> None:
    document = json.loads((CORPUS / "worker.json").read_text(encoding="utf-8"))
    document["accelerators"] = ["cuda", "cuda"]
    with pytest.raises(WorkerRequestError):
        validate_worker_register_request(document)
    document["accelerators"] = ["cuda"] * (MAX_ACCELERATORS + 1)
    with pytest.raises(WorkerRequestError):
        validate_worker_register_request(document)


def test_cli_unhandled_commands_and_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    with pytest.raises(AssertionError, match="unhandled m2"):
        run_m2(argparse.Namespace(m2_command="nope"))
    with pytest.raises(AssertionError, match="unhandled workers"):
        run_workers(argparse.Namespace(workers_command="nope"))
    with pytest.raises(AssertionError, match="unhandled grants"):
        run_grants(argparse.Namespace(grants_command="nope"))

    def _checkpoint(*_args: object, **_kwargs: object) -> object:
        raise M2CheckpointError("denied", code="authorization-denied")

    monkeypatch.setattr("llm_research_os.cli.m2_commands.prove_cpu_loop", _checkpoint)
    assert (
        run_m2(
            argparse.Namespace(
                m2_command="prove",
                corpus=tmp_path,
                database=tmp_path / "research.db",
                artifacts=None,
                format="text",
            )
        )
        == 2
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    def _worker(*_args: object, **_kwargs: object) -> object:
        raise WorkerError("plane failed", code="worker")

    monkeypatch.setattr("llm_research_os.cli.m2_commands.prove_cpu_loop", _worker)
    assert (
        run_m2(
            argparse.Namespace(
                m2_command="prove",
                corpus=tmp_path,
                database=tmp_path / "research.db",
                artifacts=tmp_path / "artifacts",
                format="text",
            )
        )
        == 1
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    def _raise_request(*_args: object, **_kwargs: object) -> object:
        validate_worker_register_request({})
        raise AssertionError("invalid worker request must fail closed")

    monkeypatch.setattr("llm_research_os.cli.m2_commands.prove_cpu_loop", _raise_request)
    assert (
        run_m2(
            argparse.Namespace(
                m2_command="prove",
                corpus=tmp_path,
                database=tmp_path / "research.db",
                artifacts=tmp_path / "artifacts",
                format="text",
            )
        )
        == 2
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    def _value(*_args: object, **_kwargs: object) -> object:
        raise ValueError("bad input")

    monkeypatch.setattr("llm_research_os.cli.m2_commands.prove_cpu_loop", _value)
    assert (
        run_m2(
            argparse.Namespace(
                m2_command="prove",
                corpus=tmp_path,
                database=tmp_path / "research.db",
                artifacts=tmp_path / "artifacts",
                format="text",
            )
        )
        == 2
    )


def test_cli_duplicate_register_is_worker_error(tmp_path: Path, capsys: object) -> None:
    from llm_research_os.cli import main

    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert main(["workers", "register", str(CORPUS / "worker.json"), str(database)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["workers", "register", str(CORPUS / "worker.json"), str(database)]) == 1
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "error:" in err
    assert (
        main(
            [
                "grants",
                "record",
                str(CORPUS / "spec.yaml"),
                str(CORPUS / "grant.json"),
                str(database),
                "--registry",
                str(CORPUS / "block.json"),
            ]
        )
        == 1
    )
    capsys.readouterr()  # type: ignore[attr-defined]
    bad_worker = tmp_path / "bad-worker.json"
    bad_worker.write_text("{}", encoding="utf-8")
    assert main(["workers", "register", str(bad_worker), str(database)]) == 2
