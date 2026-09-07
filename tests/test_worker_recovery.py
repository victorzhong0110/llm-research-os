from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_worker_protocol import (
    HMAC_KEY,
    NOW,
    PROJECT,
    SOURCE,
    FrozenClock,
    _grant_and_queue,
    _plane,
    _record_execute_local_authorization,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import TrustedKernel, authorize_plan
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.runs.cancellation import (
    request_cancellation,
    validate_run_cancellation_request_document,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.spec.io import load_spec
from llm_research_os.storage import EventStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerCallError, WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import reconcile_worker_run
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick
from llm_research_os.workers.tokens import issue_worker_session

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-checkpoint"
RESUME_BRICK = ROOT / "examples" / "m2-checkpoint-resume" / "brick.py"
TIME = "2026-09-07T12:00:00Z"
RUN_ID = "run.worker.cpu"
ATTEMPT_ID = "attempt.worker.1"


def _identities() -> dict[str, tuple[str, str]]:
    document = json.loads((CORPUS / "run-events.json").read_text(encoding="utf-8"))
    events = document["events"]
    identities = {
        event_type: (identity["id"], identity["time"]) for event_type, identity in events.items()
    }
    identities.update(
        {
            "attempt.cancelled": ("evt.attempt.cancelled.worker.cpu", TIME),
            "run.cancelled": ("evt.run.cancelled.worker.cpu", TIME),
            "attempt.failed": ("evt.attempt.failed.worker.cpu", TIME),
            "run.failed": ("evt.run.failed.worker.cpu", TIME),
            "attempt.recovered": ("evt.attempt.recovered.worker.cpu", TIME),
        }
    )
    return identities


def _start_runtime(store: EventStore) -> tuple[WorkerRuntime, object]:
    spec = load_spec(CORPUS / "spec.yaml")
    registry = build_registry([CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.local",),
    )
    authorization = authorize_plan(report, policy)
    stored = store.get_event("evt.authorization.example-minimal.1")
    assert stored is not None
    runtime = WorkerRuntime(
        store,
        project_id=PROJECT,
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        source=SOURCE,
        subject=RUN_ID,
        stream_id=RUN_ID,
        actor_id="researcher.alice",
        events=_identities(),
    )
    runtime.start(
        report=report,
        authorization=authorization,
        citation={"eventId": stored.event.id, "sequence": stored.event.sequence},
        revision=1,
    )
    return runtime, report


def _request_run_cancel(store: EventStore, *, event_id: str) -> None:
    request_cancellation(
        store,
        validate_run_cancellation_request_document(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "RunCancellationRequest",
                "projectId": PROJECT,
                "experimentRevision": 1,
                "runId": RUN_ID,
                "target": {"kind": "run"},
                "reasonCode": "researcher.requested",
                "source": SOURCE,
                "subject": RUN_ID,
                "streamid": RUN_ID,
                "actor": {"id": "researcher.alice"},
                "event": {"id": event_id, "time": "2026-09-07T12:00:02Z"},
                "evidenceRefs": [],
            }
        ),
    )


def test_cancel_request_is_not_observed_stop(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        _start_runtime(store)
        token = _grant_and_queue(plane, image)
        _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        snapshot = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert snapshot is not None
        assert snapshot.status is RunStatus.RUNNING
        assert snapshot.cancellation_requested is True
        assert snapshot.attempts[0].status is AttemptStatus.RUNNING
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is None
        session = issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1")
        with pytest.raises(WorkerCallError) as captured:
            plane.heartbeat(
                worker_id="worker.loopback.1",
                session=session,
                lease_id="lease.grant.cpu.1",
            )
        assert captured.value.code == "unknown-lease"
        types = {item.event.type for item in store.read_events(limit=80)}
        assert "attempt.cancelled" not in types
        assert "run.cancelled" not in types
    finally:
        store.__exit__(None, None, None)


def test_observed_stop_records_cancelled_outcomes(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        session = issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1")
        assert (
            plane.heartbeat(
                worker_id="worker.loopback.1",
                session=session,
                lease_id=claimed.lease_id,
            )
            is True
        )
        resumed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert resumed is not None
        assert resumed.resumed is True
        assert resumed.cancel_requested is True
        plane.fail(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            reason_code="cancel-observed",
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.CANCELLED
        assert snapshot.attempts[0].status is AttemptStatus.CANCELLED
        types = [item.event.type for item in store.read_events(limit=80)]
        assert "work.failed" in types
        assert "attempt.cancelled" in types
        assert "run.cancelled" in types
        again = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert again.last_sequence == snapshot.last_sequence
    finally:
        store.__exit__(None, None, None)


def test_completed_work_wins_over_retained_cancel_request(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.COMPLETED
        assert snapshot.attempts[0].status is AttemptStatus.SUCCEEDED
        types = {item.event.type for item in store.read_events(limit=80)}
        assert "work.completed" in types
        assert "attempt.cancelled" not in types
        assert "run.cancelled" not in types
    finally:
        store.__exit__(None, None, None)


def test_unknown_cannot_be_marked_success_or_rerun(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        sleep = tmp_path / "sleep.py"
        sleep.write_text("import sys, time\ntime.sleep(30)\nsys.exit(2)\n", encoding="utf-8")
        timeout_digest = artifacts.put(sleep).digest
        result = execute_python_brick(artifacts, timeout_digest, timeout_seconds=1)
        assert result.disposition is SandboxDisposition.UNKNOWN
        runtime.unknown(reason_code="worker.process.timeout", revision=1)
        resumed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert resumed is not None
        assert resumed.resumed is True
        with pytest.raises(WorkerCallError) as captured:
            reconcile_worker_run(
                store,
                runtime,
                plane.rebuild(),
                project_id=PROJECT,
                run_id=RUN_ID,
                attempt_id=ATTEMPT_ID,
                report=report,
                revision=1,
            )
        assert captured.value.code == "attempt-unknown"
        snapshot = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert snapshot is not None
        assert snapshot.status is RunStatus.UNKNOWN
        assert claimed.lease_id == resumed.lease_id
    finally:
        store.__exit__(None, None, None)


def test_completed_fact_reconciles_run_without_rerun(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
        running = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert running is not None
        assert running.status is RunStatus.RUNNING
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.COMPLETED
        again = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert again.last_sequence == snapshot.last_sequence
        resumed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert resumed is None
    finally:
        store.__exit__(None, None, None)


def test_artifact_without_complete_is_not_success(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        artifacts.put_bytes(result.stdout)
        still = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert still is not None
        assert still.status is RunStatus.RUNNING
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.RUNNING
        types = [item.event.type for item in store.read_events(limit=80)]
        assert "work.completed" not in types
        assert "attempt.succeeded" not in types
        assert claimed.lease_id.startswith("lease.")
        assert token.startswith("rg1.")
    finally:
        store.__exit__(None, None, None)


def test_cpu_checkpoint_is_inspectable_and_not_an_unknown_rerun(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(RESUME_BRICK)
    first = execute_python_brick(artifacts, brick.digest, inputs={"step": 0})
    assert first.disposition is SandboxDisposition.SUCCEEDED
    assert first.result_digest is not None
    checkpoint = json.loads(first.stdout.decode("utf-8"))
    assert checkpoint["outputs"]["checkpoint"] == {"step": 1, "status": "inspectable"}
    store, plane_artifacts, plane, image = _plane(tmp_path / "plane")
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        runtime.unknown(reason_code="worker.process.timeout", revision=1)
        recovered = runtime.recovered(revision=1)
        assert recovered.attempts[0].status is AttemptStatus.RUNNING
        resumed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert resumed is not None
        assert resumed.resumed is True
        second = execute_python_brick(
            artifacts,
            brick.digest,
            inputs={"step": checkpoint["outputs"]["step"]},
        )
        assert second.disposition is SandboxDisposition.SUCCEEDED
        continued = json.loads(second.stdout.decode("utf-8"))
        assert continued["outputs"]["checkpoint"]["step"] == 2
        record = plane_artifacts.put_bytes(first.stdout)
        plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=first.result_digest,
            artifact_digest=record.digest,
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.COMPLETED
        inspectable = json.loads(plane_artifacts.open(record.digest).read().decode("utf-8"))
        assert inspectable["outputs"]["checkpoint"]["status"] == "inspectable"
        assert image.startswith("sha256:")
    finally:
        store.__exit__(None, None, None)


def test_control_plane_restart_rebuilds_the_same_run(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    image = artifacts.put(CORPUS / "brick.py")
    with EventStore(database) as store:
        _record_execute_local_authorization(store)
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
            time="2026-09-07T12:00:00Z",
        )
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image.digest)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        result = execute_python_brick(artifacts, image.digest)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        plane.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
    with EventStore(database, require_existing=True) as store:
        restarted = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        runtime = WorkerRuntime(
            store,
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            source=SOURCE,
            subject=RUN_ID,
            stream_id=RUN_ID,
            actor_id="researcher.alice",
            events=_identities(),
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            restarted.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.COMPLETED
        replayed = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert replayed is not None
        assert replayed.status is snapshot.status
        assert replayed.last_sequence == snapshot.last_sequence


def test_failed_work_reconciles_run_failed(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        plane.fail(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            reason_code="worker.brick.failed",
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.FAILED
        assert snapshot.attempts[0].status is AttemptStatus.FAILED
        again = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert again.last_sequence == snapshot.last_sequence
    finally:
        store.__exit__(None, None, None)


def test_reconcile_without_lease_leaves_run_running(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        _grant_and_queue(plane, image)
        snapshot = reconcile_worker_run(
            store,
            runtime,
            plane.rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=report,
            revision=1,
        )
        assert snapshot.status is RunStatus.RUNNING
        types = {item.event.type for item in store.read_events(limit=80)}
        assert "attempt.succeeded" not in types
        assert "work.leased" not in types
    finally:
        store.__exit__(None, None, None)


def test_reconcile_missing_run_or_attempt_fails(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        runtime, report = _start_runtime(store)
        with pytest.raises(WorkerCallError) as missing_attempt:
            reconcile_worker_run(
                store,
                runtime,
                plane.rebuild(),
                project_id=PROJECT,
                run_id=RUN_ID,
                attempt_id="attempt.missing.1",
                report=report,
                revision=1,
            )
        assert missing_attempt.value.code == "attempt-missing"
        empty = tmp_path / "empty.db"
        with EventStore(empty) as other:
            with pytest.raises(WorkerCallError) as missing_run:
                reconcile_worker_run(
                    other,
                    runtime,
                    plane.rebuild(),
                    project_id=PROJECT,
                    run_id=RUN_ID,
                    attempt_id=ATTEMPT_ID,
                    report=report,
                    revision=1,
                )
            assert missing_run.value.code == "run-missing"
        assert image.startswith("sha256:")
    finally:
        store.__exit__(None, None, None)


def test_resumed_cancel_fails_lease_without_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    database = tmp_path / "research.db"
    try:
        _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
    finally:
        store.__exit__(None, None, None)

    def _forbid(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("resume must not spawn")

    monkeypatch.setattr("llm_research_os.workers.sandbox.subprocess.Popen", _forbid)
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
        clock=FrozenClock(NOW),
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
        assert captured.value.code == "execution-unobserved"
    finally:
        server.stop()
    with EventStore(database, require_existing=True) as store:
        types = {item.event.type for item in store.read_events(limit=80)}
        assert "work.failed" not in types
        assert "work.completed" not in types
