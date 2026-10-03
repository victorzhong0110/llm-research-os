"""Controller-side reviewed-native dispatch binding and restart-safe Run queueing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.events.models import RESEARCH_EVENT_SCHEMA_ID
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage.errors import DuplicateEventError, EventSequenceConflictError
from llm_research_os.workers.binding import require_authorized_execution_binding
from llm_research_os.workers.errors import WorkerCallError, WorkerGrantError
from llm_research_os.workers.models import WORKER_RUNTIME_NATIVE_REVIEWED
from llm_research_os.workers.plane import ClaimedWork, WorkerPlane
from llm_research_os.workers.tokens import verify_grant_token


@dataclass(frozen=True, slots=True)
class NativeControllerContext:
    """Trusted controller inputs; never populated from a Worker request body."""

    spec: ResearchSpec
    registry: BlockRegistry


def is_native_claim(plane: WorkerPlane, *, worker_id: str, grant_token: str) -> bool:
    claims = verify_grant_token(plane.hmac_key, grant_token, now=plane.clock())
    if claims["workerId"] != worker_id:
        raise WorkerGrantError("grant worker does not match", code="grant-worker-mismatch")
    fold = plane.rebuild()
    grant = fold.grant(claims["grantId"])
    if grant is None:
        raise WorkerGrantError("grant is not recorded", code="unknown-grant")
    queued = fold.queued_work(grant.task_id, grant.attempt_id)
    return queued is not None and queued.runtime == WORKER_RUNTIME_NATIVE_REVIEWED


def claim_native(
    plane: WorkerPlane,
    *,
    context: NativeControllerContext | None,
    worker_id: str,
    grant_token: str,
) -> ClaimedWork | None:
    """Queue one Run/Attempt, then consume or resume the existing Worker grant.

    The HTTP caller holds the cross-controller publication lock. No PID is
    observed here. In particular, queued/claimed does not imply user code started.
    """
    if context is None:
        raise WorkerCallError(
            "native dispatch requires controller spec and registry", code="native-context-required"
        )
    request = plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
    _require_binding(plane, context, request)
    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
    queued_id = _event_id(request, "run.queued")
    if run.rebuild().snapshot is not None and plane.store.get_event(queued_id) is None:
        raise WorkerCallError("Run belongs to another dispatch", code="native-run-conflict")
    rows: tuple[tuple[str, dict[str, Any], bool], ...] = (
        (
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
            False,
        ),
        ("run.started", {}, False),
        ("attempt.queued", {"ordinal": 1, "retryOf": None, "retryDecisionId": None}, True),
    )
    for event_type, payload, attempt in rows:
        _append_bound(run, plane, request, event_type, payload, attempt=attempt)
    snapshot = run.rebuild().snapshot
    lease = plane.rebuild().lease_for_worker(request.task_id, request.attempt_id, worker_id)
    if snapshot is None or snapshot.status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }:
        raise WorkerCallError("native Run is terminal", code="native-run-conflict")
    if lease is None and (
        snapshot.status is not RunStatus.RUNNING
        or len(snapshot.attempts) != 1
        or snapshot.attempts[0].status is not AttemptStatus.QUEUED
    ):
        raise WorkerCallError("native Attempt cannot be dispatched", code="native-run-conflict")
    # Re-authorize after lifecycle I/O. Revocation/cancellation cannot be masked
    # by a partially persisted Run. Existing grants/leases remain the only authority.
    plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
    _require_binding(plane, context, request)
    # Even an unclaimed persisted lease is a restart boundary, not fresh launch
    # permission. Decide inside the plane's fold, including a racing local caller.
    return plane.poll(worker_id=worker_id, grant_token=grant_token, resume_existing=True)


def _require_binding(
    plane: WorkerPlane,
    context: NativeControllerContext,
    request: NativeReviewedExecutionRequest,
) -> None:
    require_authorized_execution_binding(
        plane.store,
        context.spec,
        context.registry,
        project_id=request.project_id,
        experiment_revision=plane.experiment_revision,
        planned_task_id=request.task_id,
        event_id=request.authorization_event_id,
        sequence=request.authorization_sequence,
        image_digest=request.code.bundle_digest,
        config_digest=request.config_digest,
        workflow_id=request.workflow_id,
    )


def _event_id(request: NativeReviewedExecutionRequest, event_type: str) -> str:
    return f"evt.native.remote.{request.run_id}.{request.attempt_id}.{event_type}"


def _append_bound(
    run: RunControl,
    plane: WorkerPlane,
    request: NativeReviewedExecutionRequest,
    event_type: str,
    payload: dict[str, Any],
    *,
    attempt: bool,
) -> None:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": request.worker_id, "kind": "system"},
        "projectId": request.project_id,
        "experimentRevision": int(request.revision_id),
        "runId": request.run_id,
        "payload": payload,
        "evidenceRefs": [],
    }
    if attempt:
        data["attemptId"] = request.attempt_id
    event_id = _event_id(request, event_type)
    for _ in range(3):
        stored = plane.store.get_event(event_id)
        if stored is not None:
            recorded = stored.event.data.model_dump(mode="json", by_alias=True, exclude_none=True)
            if stored.event.type != event_type or recorded != data:
                raise WorkerCallError(
                    "native lifecycle binding differs", code="native-run-conflict"
                )
            return
        head = run.rebuild()
        try:
            run.append(
                {
                    "specversion": "1.0",
                    "id": event_id,
                    "source": f"https://researchos.dev/projects/{request.project_id}",
                    "type": event_type,
                    "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "subject": request.run_id,
                    "dataschema": RESEARCH_EVENT_SCHEMA_ID,
                    "datacontenttype": "application/json",
                    "streamid": request.project_id,
                    "data": data,
                },
                expected_last_sequence=head.last_sequence,
            )
            return
        except (DuplicateEventError, EventSequenceConflictError):
            continue
    raise WorkerCallError("native lifecycle did not settle", code="native-run-conflict")
