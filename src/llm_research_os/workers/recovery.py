"""Reconcile Worker lease facts with Run/Attempt snapshots (ADR-0046).

A CAS artifact is not success. Unknown work is not auto-rerun.
"""

from __future__ import annotations

from llm_research_os.execution.models import DryRunReport
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunSnapshot, RunStatus
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.control import LeaseRecord, WorkerFold
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.runtime import WorkerRuntime

CANCEL_OBSERVED = "cancel-observed"


def run_cancel_requested(
    store: EventStore,
    *,
    project_id: str,
    run_id: str,
    attempt_id: str,
) -> bool:
    """True when a cancel request exists. Does not mean the process stopped."""

    snapshot = RunControl(store, project_id=project_id, run_id=run_id).rebuild().snapshot
    if snapshot is None:
        return False
    if snapshot.cancellation_requested:
        return True
    attempt = next((item for item in snapshot.attempts if item.attempt_id == attempt_id), None)
    return attempt is not None and attempt.cancellation_requested


def lease_for_attempt(fold: WorkerFold, attempt_id: str) -> LeaseRecord | None:
    matches = [item for item in fold.leases if item.attempt_id == attempt_id]
    if not matches:
        return None
    return matches[-1]


def reconcile_worker_run(
    store: EventStore,
    runtime: WorkerRuntime,
    fold: WorkerFold,
    *,
    project_id: str,
    run_id: str,
    attempt_id: str,
    report: DryRunReport | None = None,
    revision: int,
) -> RunSnapshot:
    """Drive Run/Attempt to the outcome already recorded on the Worker lease.

    Refuses to mark success from unknown or from a CAS object without
    ``work.completed``.
    """

    snapshot = RunControl(store, project_id=project_id, run_id=run_id).rebuild().snapshot
    if snapshot is None:
        raise WorkerCallError("run is not recorded", code="run-missing")
    attempt = next((item for item in snapshot.attempts if item.attempt_id == attempt_id), None)
    if attempt is None:
        raise WorkerCallError("attempt is not recorded", code="attempt-missing")
    lease = lease_for_attempt(fold, attempt_id)
    if lease is not None and lease.status == "completed":
        if attempt.status in {
            AttemptStatus.RUNNING,
            AttemptStatus.LOST,
            AttemptStatus.UNKNOWN,
        }:
            return runtime.succeed(report=report, revision=revision)
        if attempt.status is AttemptStatus.SUCCEEDED and snapshot.status is RunStatus.RUNNING:
            return runtime.succeed(report=report, revision=revision)
        return snapshot
    if lease is not None and lease.status == "failed":
        requested = run_cancel_requested(
            store,
            project_id=project_id,
            run_id=run_id,
            attempt_id=attempt_id,
        )
        if lease.reason_code == CANCEL_OBSERVED and requested:
            if attempt.status in {
                AttemptStatus.QUEUED,
                AttemptStatus.RUNNING,
                AttemptStatus.LOST,
                AttemptStatus.UNKNOWN,
            }:
                return runtime.cancelled(revision=revision)
            if attempt.status is AttemptStatus.CANCELLED and snapshot.status is RunStatus.RUNNING:
                return runtime.cancelled(revision=revision)
            return snapshot
        if attempt.status in {
            AttemptStatus.QUEUED,
            AttemptStatus.RUNNING,
            AttemptStatus.LOST,
            AttemptStatus.UNKNOWN,
        }:
            return runtime.failed(
                reason_code=lease.reason_code or "worker.brick.failed",
                revision=revision,
            )
        return snapshot
    if attempt.status is AttemptStatus.UNKNOWN:
        raise WorkerCallError(
            "unknown execution cannot be marked success",
            code="attempt-unknown",
        )
    return snapshot
