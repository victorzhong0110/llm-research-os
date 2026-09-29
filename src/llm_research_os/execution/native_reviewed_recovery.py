"""Conservative observation and cancellation of an already claimed reviewed Attempt.

Every call rebuilds Worker and Run facts. A launch intent is never permission to
start a child; missing identity or missing outcome stays unknown.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_research_os.execution.native_reviewed import request_digest
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_runtime import NativeLaunchError, _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.storage.errors import DuplicateEventError, EventSequenceConflictError
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import run_cancel_requested
from llm_research_os.workers.supervise import (
    OBSERVATION_EXITED,
    OBSERVATION_RUNNING,
    OBSERVED_STOP,
    load_execution_identity,
    observe_and_stop,
    observe_process,
    observe_process_group,
    posix_start_token,
)

NativeObservation = Literal["unclaimed", "running", "unknown", "cancelled", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class NativeReconciliation:
    disposition: NativeObservation
    lease_id: str | None


def reconcile_reviewed_native(
    *,
    request: NativeReviewedExecutionRequest,
    plane: WorkerPlane,
    state_dir: Path,
    grant_token: str,
) -> NativeReconciliation:
    """Observe an existing Attempt after a crash or while cancellation is pending.

    A cancellation fact or a consumed, revoked grant authorizes TERM, a fixed
    three-second grace, then KILL. Only the reused process-group observer may
    certify stop; a missing or mismatched start identity cannot be signaled.
    """

    if (
        request.project_id != plane.project_id
        or int(request.revision_id) != plane.experiment_revision
    ):
        raise NativeLaunchError("request project or revision does not match Worker")
    identity = f"{request.project_id}:{request.run_id}:{request.attempt_id}"
    name = hashlib.sha256(identity.encode()).hexdigest()
    intent = state_dir / f"{name}.intent"
    if intent.is_symlink():
        raise NativeLaunchError("launch intent is a symlink")
    try:
        document = json.loads(intent.read_bytes())
    except (OSError, ValueError):
        raise NativeLaunchError("durable launch intent is missing or invalid") from None
    expected = {
        "requestDigest": request_digest(request),
        "runId": request.run_id,
        "attemptId": request.attempt_id,
    }
    if type(document) is not dict or (
        {key: document.get(key) for key in expected} != expected
        or set(document) - {*expected, "restore"}
    ):
        raise NativeLaunchError("launch intent does not bind the request")
    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
    snapshot = run.rebuild().snapshot
    if snapshot is None:
        return NativeReconciliation("unknown", None)
    fold = plane.rebuild()
    matches = [
        g for g in fold.grants if g.run_id == request.run_id and g.attempt_id == request.attempt_id
    ]
    consumed = [g for g in matches if g.consumed_lease_id is not None]
    if len(consumed) != 1:
        return NativeReconciliation("unclaimed" if not consumed else "unknown", None)
    grant = consumed[0]
    lease_id = grant.consumed_lease_id
    if lease_id is None:
        return NativeReconciliation("unknown", None)
    if grant.worker_id != request.worker_id or grant.config_digest != request.config_digest:
        raise NativeLaunchError("consumed grant does not bind reviewed request")
    lease = fold.lease(lease_id)
    if lease is None or lease.run_id != request.run_id or lease.attempt_id != request.attempt_id:
        return NativeReconciliation("unknown", lease_id)
    if snapshot.status == RunStatus.COMPLETED:
        return NativeReconciliation("completed", lease_id)
    if snapshot.status == RunStatus.CANCELLED:
        return NativeReconciliation("cancelled", lease_id)
    if snapshot.status == RunStatus.FAILED:
        return NativeReconciliation("failed", lease_id)
    attempt = next((a for a in snapshot.attempts if a.attempt_id == request.attempt_id), None)
    if attempt is None:
        return NativeReconciliation("unknown", lease_id)
    recorded_identity = load_execution_identity(state_dir / "identities", lease_id)
    observed = "unknown"
    if (
        recorded_identity is not None
        and recorded_identity.pid is not None
        and recorded_identity.pgid is not None
    ):
        # A start token is mandatory for any new signal after a restart.
        if recorded_identity.start_token is not None:
            current = posix_start_token(recorded_identity.pid)
            group = observe_process_group(recorded_identity.pgid, recorded_identity.pid)
            if group == OBSERVATION_EXITED:
                observed = "exited"
            elif group == OBSERVATION_RUNNING and (
                current == recorded_identity.start_token
                or observe_process(recorded_identity.pid) == OBSERVATION_EXITED
            ):
                observed = "running"
        else:
            # Still allow passive observation of an empty group.
            if (
                observe_process_group(recorded_identity.pgid, recorded_identity.pid)
                == OBSERVATION_EXITED
            ):
                observed = "exited"
    requested = run_cancel_requested(
        plane.store,
        project_id=request.project_id,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
    )
    revocation_recorded = False
    if (
        grant.revoked
        and not requested
        and snapshot.status in {RunStatus.RUNNING, RunStatus.UNKNOWN}
    ):
        _append_once(run, request, "run.cancel.requested", {"reasonCode": "grant-revoked"})
        requested = True
        revocation_recorded = True
    if requested and not snapshot.cancellation_requested and not revocation_recorded:
        _append_once(run, request, "run.cancel.requested", {"reasonCode": "native-cancellation"})
    if requested and lease.status not in {"completed", "failed", "expired"}:
        if observed == "running" and recorded_identity is not None:
            if observe_and_stop(recorded_identity) == OBSERVED_STOP:
                observed = "exited"
            else:
                observed = "unknown"
        if observed == "exited":
            plane.fail_observed_cancellation(
                worker_id=request.worker_id, grant_token=grant_token, lease_id=lease_id
            )
            lease = plane.rebuild().lease(lease_id)
    if lease is not None and lease.status == "completed" and observed == "exited":
        _append_once(run, request, "attempt.succeeded", {}, attempt=True)
        _append_once(run, request, "run.completed", {})
        return NativeReconciliation("completed", lease_id)
    if lease is not None and lease.status == "failed" and observed == "exited":
        if lease.reason_code == "cancel-observed" and requested:
            _append_once(run, request, "attempt.cancelled", {}, attempt=True)
            _append_once(run, request, "run.cancelled", {})
            return NativeReconciliation("cancelled", lease_id)
        if lease.reason_code == "native-task-failed":
            _append_once(
                run,
                request,
                "attempt.failed",
                {"reasonCode": "native-task-failed", "retryHint": "not-retryable"},
                attempt=True,
            )
            _append_once(run, request, "run.failed", {"reasonCode": "native-task-failed"})
            return NativeReconciliation("failed", lease_id)
    if observed == "running" and not requested:
        return NativeReconciliation("running", lease_id)
    if attempt.status in {AttemptStatus.QUEUED, AttemptStatus.RUNNING}:
        if attempt.status == AttemptStatus.QUEUED:
            _append_once(run, request, "attempt.started", {}, attempt=True)
        _append_once(
            run,
            request,
            "attempt.unknown",
            {"reasonCode": "native-outcome-uncertain"},
            attempt=True,
        )
    return NativeReconciliation("unknown", lease_id)


def _append_once(
    run: RunControl,
    request: NativeReviewedExecutionRequest,
    event_type: str,
    payload: dict[str, object],
    *,
    attempt: bool = False,
) -> None:
    event_id = f"evt.native.{request.run_id}.{request.attempt_id}.{event_type}"
    for _ in range(3):
        if run._store.get_event(event_id) is not None:
            return
        try:
            _lifecycle(run, request, event_type, payload, attempt=attempt)
            return
        except (DuplicateEventError, EventSequenceConflictError, RunControlError) as exc:
            if run._store.get_event(event_id) is not None:
                return
            if isinstance(exc, RunControlError):
                raise
    raise NativeLaunchError("concurrent lifecycle reconciliation did not settle")
