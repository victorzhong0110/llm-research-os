from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore
from llm_research_os.workers.binding import brick_execution_digest
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
CORPUS = ROOT / "examples" / "m2-checkpoint"
BRICK = CORPUS / "brick.py"
HMAC_KEY = b"a" * HMAC_KEY_BYTES
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
PROJECT = "example-minimal"
SOURCE = "https://researchos.dev/projects/example-minimal"
AUTH_EVENT_ID = "evt.authorization.example-minimal.1"
TOKEN_IMAGE = "sha256:" + ("0" * 64)
TOKEN_CONFIG = "jcs-sha256:" + ("0" * 64)


def _record_execute_local_authorization(store: EventStore) -> tuple[str, str]:
    spec = load_spec(CORPUS / "spec.yaml")
    report = TrustedKernel(build_registry([CORPUS / "block.json"])).dry_run(
        spec, workflow_id=spec.workflows[0].id
    )
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.local",),
    )
    result = authorize_plan(report, policy)
    document = snapshot_json_document(
        load_document(CORPUS / "authorization-event.json", reject_symlinks=True)
    )
    assert type(document) is dict
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    recorded = record_plan_authorization_event(
        store,
        report,
        policy,
        validate_plan_authorization_event_request_document(document),
    )
    return recorded.stored.event.id, recorded.stored.event.sequence


def _citation(plane: WorkerPlane) -> tuple[str, str]:
    stored = plane.store.get_event(AUTH_EVENT_ID)
    assert stored is not None
    return stored.event.id, stored.event.sequence


def _token_args(plane: WorkerPlane, grant_id: str, **overrides: str) -> dict[str, str]:
    grant = plane.rebuild().grant(grant_id)
    assert grant is not None
    claims = {
        "grant_id": grant.grant_id,
        "grant_event_id": grant.grant_event_id,
        "worker_id": grant.worker_id,
        "task_id": grant.task_id,
        "attempt_id": grant.attempt_id,
        "run_id": grant.run_id,
        "nonce": grant.nonce,
        "expires_at": grant.expires_at,
        "project_id": PROJECT,
        "image_digest": grant.image_digest,
        "config_digest": grant.config_digest,
    }
    claims.update(overrides)
    return claims


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
    artifacts_root.mkdir(parents=True, exist_ok=True)
    store = EventStore(database)
    store.__enter__()
    _record_execute_local_authorization(store)
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
    grant_id: str = "grant.cpu.1",
    worker_id: str = "worker.loopback.1",
    task_id: str = "task.cpu",
    run_id: str = "run.worker.cpu",
    attempt_id: str = "attempt.worker.1",
    nonce: str = "nonce.cpu.1",
    event_id: str = "evt.grant.recorded.1",
    queued_event_id: str = "evt.work.queued.task.cpu",
    required_accelerators: tuple[str, ...] = (),
) -> str:
    event_id_value, sequence = _citation(plane)
    plane.record_grant(
        grant_id=grant_id,
        worker_id=worker_id,
        task_id=task_id,
        run_id=run_id,
        attempt_id=attempt_id,
        nonce=nonce,
        expires_at=expires_at,
        actor_id="researcher.alice",
        event_id=event_id,
        authorization_event_id=event_id_value,
        authorization_sequence=sequence,
        image_digest=image_digest,
        config_digest=brick_execution_digest(image_digest=image_digest),
        time="2026-09-07T12:00:00Z",
    )
    plane.enqueue(
        task_id=task_id,
        run_id=run_id,
        attempt_id=attempt_id,
        image_digest=image_digest,
        event_id=queued_event_id,
        required_accelerators=required_accelerators,
        time="2026-09-07T12:00:00Z",
    )
    return plane.issue_token(grant_id)


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
            **_token_args(plane, "grant.cpu.1"),
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
        assert first.resumed is False
        assert second.resumed is True
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
            **_token_args(plane, "grant.cpu.1", worker_id="worker.other.1"),
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
        token = _grant_and_queue(
            plane,
            image,
            grant_id="grant.gpu.1",
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu",
            nonce="nonce.gpu.1",
            event_id="evt.grant.recorded.gpu",
            queued_event_id="evt.work.queued.task.gpu",
            required_accelerators=("cuda",),
        )
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
        project_id=PROJECT,
        image_digest=TOKEN_IMAGE,
        config_digest=TOKEN_CONFIG,
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


def test_simulate_authorization_cannot_record_an_execution_grant(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        spec = load_spec(ROOT / "examples" / "valid" / "minimal.yaml")
        report = TrustedKernel(build_registry()).dry_run(spec, workflow_id="workflow.simulation")
        assert report.digests.plan is not None
        policy = PlanAuthorizationPolicy(
            spec_digest=report.digests.spec,
            registry_digest=report.digests.registry,
            plan_digest=report.digests.plan,
            granted_capabilities=("simulate",),
        )
        result = authorize_plan(report, policy)
        document = snapshot_json_document(
            load_document(
                ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json",
                reject_symlinks=True,
            )
        )
        assert type(document) is dict
        document["event"] = {"id": "evt.authorization.simulate.1", "time": "2026-09-02T05:00:00Z"}
        document["binding"] = {
            "specDigest": result.spec_digest,
            "registryDigest": result.registry_digest,
            "planDigest": result.plan_digest,
            "decisionDigest": result.decision_digest,
        }
        recorded = record_plan_authorization_event(
            store,
            report,
            policy,
            validate_plan_authorization_event_request_document(document),
        )
        with pytest.raises(WorkerCallError) as captured:
            plane.record_grant(
                grant_id="grant.simulate.1",
                worker_id="worker.loopback.1",
                task_id="task.cpu",
                run_id="run.worker.cpu",
                attempt_id="attempt.worker.1",
                nonce="nonce.simulate.1",
                expires_at="2099-01-01T00:00:00Z",
                actor_id="researcher.alice",
                event_id="evt.grant.recorded.simulate",
                authorization_event_id=recorded.stored.event.id,
                authorization_sequence=recorded.stored.event.sequence,
                image_digest=image,
                config_digest=brick_execution_digest(image_digest=image),
            )
        assert captured.value.code == "authorization-capability-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_swapped_brick_does_not_start_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        event_id, sequence = _citation(plane)
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
            image_digest=image,
            config_digest=brick_execution_digest(image_digest=image),
            time="2026-09-07T12:00:00Z",
        )
        other = tmp_path / "other.py"
        other.write_text("raise SystemExit(2)\n", encoding="utf-8")
        swapped = artifacts.put(other).digest
        plane.enqueue(
            task_id="task.cpu",
            run_id="run.worker.cpu",
            attempt_id="attempt.worker.1",
            image_digest=swapped,
            event_id="evt.work.queued.task.cpu",
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.cpu.1")
        spawned: list[object] = []

        def _forbid(*_args: object, **_kwargs: object) -> object:
            spawned.append(1)
            raise AssertionError("swapped brick must not spawn")

        monkeypatch.setattr("llm_research_os.workers.sandbox.subprocess.Popen", _forbid)
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert captured.value.code == "execution-binding-mismatch"
        assert spawned == []
    finally:
        store.__exit__(None, None, None)


def test_cross_task_token_cannot_complete_or_fail_current_lease(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token_a = _grant_and_queue(plane, image)
        claimed_a = plane.poll(worker_id="worker.loopback.1", grant_token=token_a)
        assert claimed_a is not None
        token_b = _grant_and_queue(
            plane,
            image,
            grant_id="grant.cpu.2",
            task_id="task.other",
            run_id="run.worker.other",
            attempt_id="attempt.worker.other",
            nonce="nonce.cpu.2",
            event_id="evt.grant.recorded.2",
            queued_event_id="evt.work.queued.task.other",
        )
        claimed_b = plane.poll(worker_id="worker.loopback.1", grant_token=token_b)
        assert claimed_b is not None
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        with pytest.raises(WorkerGrantError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token_a,
                lease_id=claimed_b.lease_id,
                result_digest=result.result_digest,
                artifact_digest=record.digest,
            )
        assert captured.value.code == "grant-task-mismatch"
        with pytest.raises(WorkerGrantError) as captured:
            plane.fail(
                worker_id="worker.loopback.1",
                grant_token=token_a,
                lease_id=claimed_b.lease_id,
                reason_code="worker.brick.failed",
            )
        assert captured.value.code == "grant-task-mismatch"
        lease = plane.rebuild().lease(claimed_b.lease_id)
        assert lease is not None
        assert lease.status == "leased"
    finally:
        store.__exit__(None, None, None)
