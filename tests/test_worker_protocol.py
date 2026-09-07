from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage import EventStore
from llm_research_os.workers.errors import WorkerCallError, WorkerError, WorkerGrantError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick
from llm_research_os.workers.schema import (
    authorization_grant_request_schema_matches,
    worker_register_request_schema_matches,
    write_authorization_grant_request_schema,
    write_worker_register_request_schema,
)
from llm_research_os.workers.tokens import (
    HMAC_KEY_BYTES,
    issue_grant_token,
    parse_rfc3339,
    require_hmac_key,
    verify_grant_token,
    verify_worker_session,
)

ROOT = Path(__file__).parents[1]
BRICK = ROOT / "examples" / "m2-checkpoint" / "brick.py"
HMAC_KEY = b"a" * HMAC_KEY_BYTES
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
PROJECT = "example-minimal"
SOURCE = "https://researchos.dev/projects/example-minimal"


class FrozenClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


def _plane(
    tmp_path: Path,
    *,
    clock: FrozenClock | None = None,
    lease_seconds: int = 60,
    accelerators: tuple[str, ...] = (),
) -> tuple[EventStore, LocalArtifactStore, WorkerPlane, str]:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    store = EventStore(database)
    store.__enter__()
    artifacts = LocalArtifactStore(artifacts_root)
    image = artifacts.put(BRICK)
    plane = WorkerPlane(
        store,
        artifacts=artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
        clock=clock or FrozenClock(NOW),
        lease_seconds=lease_seconds,
    )
    plane.register(
        worker_id="worker.loopback.1",
        actor_id="researcher.alice",
        event_id="evt.worker.registered.1",
        accelerators=accelerators,
        time="2026-09-07T12:00:00Z",
    )
    return store, artifacts, plane, image.digest


def _grant_and_queue(
    plane: WorkerPlane,
    image_digest: str,
    *,
    expires_at: str = "2099-01-01T00:00:00Z",
) -> str:
    plane.record_grant(
        grant_id="grant.cpu.1",
        worker_id="worker.loopback.1",
        task_id="task.cpu",
        run_id="run.worker.cpu",
        attempt_id="attempt.worker.1",
        nonce="nonce.cpu.1",
        expires_at=expires_at,
        actor_id="researcher.alice",
        event_id="evt.grant.recorded.1",
        time="2026-09-07T12:00:00Z",
    )
    plane.enqueue(
        task_id="task.cpu",
        run_id="run.worker.cpu",
        attempt_id="attempt.worker.1",
        image_digest=image_digest,
        event_id="evt.work.queued.task.cpu",
        time="2026-09-07T12:00:00Z",
    )
    return plane.issue_token("grant.cpu.1")


def test_hmac_grant_is_not_a_jwt_and_binds_attempt(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        assert token.startswith("rg1.")
        assert token.count(".") == 2
        claims = verify_grant_token(HMAC_KEY, token, now=NOW)
        assert claims["attemptId"] == "attempt.worker.1"
        assert claims["workerId"] == "worker.loopback.1"
        forged = issue_grant_token(
            b"b" * HMAC_KEY_BYTES,
            grant_id="grant.cpu.1",
            grant_event_id="evt.grant.recorded.1",
            worker_id="worker.loopback.1",
            task_id="task.cpu",
            attempt_id="attempt.worker.1",
            run_id="run.worker.cpu",
            nonce="nonce.cpu.1",
            expires_at="2099-01-01T00:00:00Z",
        )
        with pytest.raises(WorkerGrantError) as captured:
            verify_grant_token(HMAC_KEY, forged, now=NOW)
        assert captured.value.code == "grant-hmac-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_claim_is_idempotent_and_foreign_worker_is_rejected(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        first = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        second = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert first is not None and second is not None
        assert first.lease_id == second.lease_id
        types = [item.event.type for item in store.read_events(limit=40)]
        assert types.count("work.leased") == 1
        assert types.count("work.claimed") == 1
        plane.register(
            worker_id="worker.other.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.2",
            time="2026-09-07T12:00:00Z",
        )
        other = issue_grant_token(
            HMAC_KEY,
            grant_id="grant.cpu.1",
            grant_event_id="evt.grant.recorded.1",
            worker_id="worker.other.1",
            task_id="task.cpu",
            attempt_id="attempt.worker.1",
            run_id="run.worker.cpu",
            nonce="nonce.cpu.1",
            expires_at="2099-01-01T00:00:00Z",
        )
        with pytest.raises(WorkerGrantError) as captured:
            plane.poll(worker_id="worker.other.1", grant_token=other)
        assert captured.value.code == "grant-worker-mismatch"
        result = execute_python_brick(artifacts, image)
        assert result.disposition is SandboxDisposition.SUCCEEDED
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        first_complete = plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=first.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
        second_complete = plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=first.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
        assert first_complete.event.id == second_complete.event.id
    finally:
        store.__exit__(None, None, None)


def test_revoked_grant_cannot_be_consumed(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        plane.revoke_grant(
            grant_id="grant.cpu.1",
            actor_id="researcher.alice",
            event_id="evt.grant.revoked.1",
            time="2026-09-07T12:00:01Z",
        )
        with pytest.raises(WorkerGrantError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert captured.value.code == "grant-revoked"
    finally:
        store.__exit__(None, None, None)


def test_cuda_work_is_refused_without_accelerator_advertisement(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        plane.record_grant(
            grant_id="grant.gpu.1",
            worker_id="worker.loopback.1",
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu",
            nonce="nonce.gpu.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.gpu",
            time="2026-09-07T12:00:00Z",
        )
        plane.enqueue(
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu",
            image_digest=image,
            event_id="evt.work.queued.task.gpu",
            required_accelerators=("cuda",),
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.gpu.1")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert captured.value.code == "accelerator-missing"
    finally:
        store.__exit__(None, None, None)


def test_loopback_bind_rejects_public_addresses(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    with pytest.raises(WorkerError) as captured:
        LoopbackWorkerServer(
            tmp_path / "research.db",
            LocalArtifactStore(artifacts_root),
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            host="0.0.0.0",
        )
    assert captured.value.code == "bind-not-loopback"
    with pytest.raises(WorkerError) as captured:
        LoopbackWorkerServer(
            tmp_path / "research.db",
            LocalArtifactStore(artifacts_root),
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            host="localhost",
        )
    assert captured.value.code == "bind-not-loopback"


def test_worker_request_schemas_round_trip(tmp_path: Path) -> None:
    worker_schema = tmp_path / "worker-register-request.json"
    grant_schema = tmp_path / "authorization-grant-request.json"
    write_worker_register_request_schema(worker_schema)
    write_authorization_grant_request_schema(grant_schema)
    assert worker_register_request_schema_matches(worker_schema)
    assert authorization_grant_request_schema_matches(grant_schema)
    assert worker_register_request_schema_matches(tmp_path / "missing.json") is False
    assert authorization_grant_request_schema_matches(tmp_path / "missing.json") is False


def test_expired_grant_cannot_be_polled(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image, expires_at="2020-01-01T00:00:00Z")
        with pytest.raises(WorkerGrantError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert captured.value.code == "grant-expired"
    finally:
        store.__exit__(None, None, None)


def test_failed_lease_cannot_complete(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        failed = plane.fail(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            reason_code="worker.brick.failed",
        )
        assert failed.event.type == "work.failed"
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id=claimed.lease_id,
                result_digest=result.result_digest,
                artifact_digest=record.digest,
            )
        assert captured.value.code == "lease-terminal"
        lease = plane.rebuild().lease(claimed.lease_id)
        assert lease is not None
        assert lease.status == "failed"
    finally:
        store.__exit__(None, None, None)


def test_hmac_tokens_and_timestamps_fail_closed() -> None:
    with pytest.raises(WorkerGrantError) as captured:
        require_hmac_key(b"short")
    assert captured.value.code == "hmac-key-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        parse_rfc3339("not-rfc3339")
    assert captured.value.code == "grant-exp-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        parse_rfc3339(1)  # type: ignore[arg-type]
    assert captured.value.code == "grant-exp-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        parse_rfc3339("2026-09-07T12:00:00")
    assert captured.value.code == "grant-exp-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, "rg1", now=NOW)
    assert captured.value.code == "grant-token-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, "ws1.abc.def", now=NOW)
    assert captured.value.code == "grant-token-invalid"
    with pytest.raises(WorkerGrantError) as captured:
        verify_worker_session(HMAC_KEY, "rg1.abc.def")
    assert captured.value.code == "grant-token-invalid"
    token = issue_grant_token(
        HMAC_KEY,
        grant_id="grant.cpu.1",
        grant_event_id="evt.grant.recorded.1",
        worker_id="worker.loopback.1",
        task_id="task.cpu",
        attempt_id="attempt.worker.1",
        run_id="run.worker.cpu",
        nonce="nonce.cpu.1",
        expires_at="2020-01-01T00:00:00Z",
    )
    with pytest.raises(WorkerGrantError) as captured:
        verify_grant_token(HMAC_KEY, token, now=NOW)
    assert captured.value.code == "grant-expired"


def test_duplicate_worker_and_unknown_grant_are_rejected(tmp_path: Path) -> None:
    store, _artifacts, plane, _image = _plane(tmp_path)
    try:
        with pytest.raises(WorkerCallError) as captured:
            plane.register(
                worker_id="worker.loopback.1",
                actor_id="researcher.alice",
                event_id="evt.worker.registered.dup",
                time="2026-09-07T12:00:00Z",
            )
        assert captured.value.code == "duplicate-worker-id"
        with pytest.raises(WorkerGrantError) as captured:
            plane.issue_token("grant.missing")
        assert captured.value.code == "unknown-grant"
    finally:
        store.__exit__(None, None, None)
