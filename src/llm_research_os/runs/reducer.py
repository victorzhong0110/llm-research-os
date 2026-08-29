"""Pure, replayable Run/Attempt projection over verified ResearchEvents."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from llm_research_os.events.models import EventIdentifier, ResearchEvent
from llm_research_os.runs.errors import RunPayloadError, RunStateError, RunTransitionError
from llm_research_os.runs.models import (
    ATTEMPT_CANCEL_REQUEST_STATUSES,
    ATTEMPT_CANCELLED_STATUSES,
    ATTEMPT_FAILED_STATUSES,
    ATTEMPT_HEARTBEAT_STATUSES,
    ATTEMPT_LIFECYCLE_TYPES,
    ATTEMPT_LOST_STATUSES,
    ATTEMPT_RECOVERED_STATUSES,
    ATTEMPT_START_STATUSES,
    ATTEMPT_SUCCEEDED_STATUSES,
    ATTEMPT_UNKNOWN_STATUSES,
    LIFECYCLE_TYPES,
    RUN_CANCEL_REQUEST_STATUSES,
    RUN_LIFECYCLE_TYPES,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    TYPE_ATTEMPT_CANCEL_REQUESTED,
    TYPE_ATTEMPT_CANCELLED,
    TYPE_ATTEMPT_FAILED,
    TYPE_ATTEMPT_HEARTBEAT,
    TYPE_ATTEMPT_LOST,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_RECOVERED,
    TYPE_ATTEMPT_STARTED,
    TYPE_ATTEMPT_SUCCEEDED,
    TYPE_ATTEMPT_UNKNOWN,
    TYPE_RUN_CANCEL_REQUESTED,
    TYPE_RUN_CANCELLED,
    TYPE_RUN_COMPLETED,
    TYPE_RUN_FAILED,
    TYPE_RUN_QUEUED,
    TYPE_RUN_REVIEWED,
    TYPE_RUN_STARTED,
    UNRESOLVED_ATTEMPT_STATUSES,
    AttemptFailedPayload,
    AttemptQueuedPayload,
    AttemptSnapshot,
    AttemptStatus,
    RunQueuedPayload,
    RunReview,
    RunReviewedPayload,
    RunSnapshot,
    RunStatus,
    assert_run_snapshot_invariants,
    parse_lifecycle_payload,
)

_IDENTIFIER = TypeAdapter(EventIdentifier)
_CURSOR_UNSET = object()


class RunStateProjection:
    """Fold ResearchEvents for one ``(projectId, runId)`` aggregate.

    ``initial_state()`` is ``None``. ``apply`` is a pure function of the previous
    frozen snapshot and one already-validated event. It performs no I/O, does
    not read clocks or randomness, and never emits events.
    """

    def __init__(self, project_id: str, run_id: str) -> None:
        self.project_id = _require_identifier("project_id", project_id)
        self.run_id = _require_identifier("run_id", run_id)

    def initial_state(self) -> None:
        return None

    def apply(self, state: RunSnapshot | None, event: ResearchEvent) -> RunSnapshot | None:
        if not _belongs(event, self.project_id, self.run_id):
            return state
        if event.type not in LIFECYCLE_TYPES:
            return _observe_unrelated(state, event)
        _require_lifecycle_envelope(event)
        payload = parse_lifecycle_payload(event)
        if state is None:
            return _apply_first(event, payload)
        _require_cursor_and_binding(state, event)
        if event.type == TYPE_RUN_REVIEWED:
            return _apply_run_reviewed(state, event, payload)
        if state.status in TERMINAL_RUN_STATUSES:
            raise RunTransitionError(_event_label(event, "terminal run cannot be reopened"))
        if event.type in RUN_LIFECYCLE_TYPES:
            return _apply_run_event(state, event, payload)
        return _apply_attempt_event(state, event, payload)


def _require_identifier(name: str, value: str) -> str:
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError:
        raise RunStateError(f"{name} is not a valid identifier") from None


def _belongs(event: ResearchEvent, project_id: str, run_id: str) -> bool:
    return event.data.project_id == project_id and event.data.run_id == run_id


def _event_label(event: ResearchEvent, message: str) -> str:
    return f"{message} ({event.type}, event id {event.id}, sequence {event.sequence})"


def _require_lifecycle_envelope(event: ResearchEvent) -> None:
    if event.data.block_id is not None:
        raise RunTransitionError(_event_label(event, "lifecycle events require blockId to be null"))
    if event.type in RUN_LIFECYCLE_TYPES and event.data.attempt_id is not None:
        raise RunTransitionError(
            _event_label(event, "run lifecycle events require attemptId to be null")
        )
    if event.type in ATTEMPT_LIFECYCLE_TYPES and event.data.attempt_id is None:
        raise RunTransitionError(
            _event_label(event, "attempt lifecycle events require a non-empty attemptId")
        )


def _require_cursor_and_binding(state: RunSnapshot, event: ResearchEvent) -> None:
    sequence = int(event.sequence)
    if sequence <= state.last_sequence:
        raise RunTransitionError(
            _event_label(
                event,
                "sequence is not strictly increasing for this run aggregate",
            )
        )
    if event.data.experiment_revision != state.experiment_revision:
        raise RunTransitionError(_event_label(event, "experimentRevision binding drifted"))
    if event.data.project_id != state.project_id or event.data.run_id != state.run_id:
        raise RunTransitionError(_event_label(event, "projectId/runId binding drifted"))


def _observe_unrelated(state: RunSnapshot | None, event: ResearchEvent) -> RunSnapshot | None:
    if state is None:
        return None
    _require_cursor_and_binding(state, event)
    return _stamp(state, event)


def _apply_first(event: ResearchEvent, payload: object) -> RunSnapshot:
    if event.type != TYPE_RUN_QUEUED:
        raise RunTransitionError(
            _event_label(event, "run.queued must be the first lifecycle event")
        )
    if not isinstance(payload, RunQueuedPayload):
        raise RunPayloadError(_event_label(event, "invalid payload for lifecycle type"))
    run_id = event.data.run_id
    if run_id is None:
        raise RunTransitionError(_event_label(event, "run.queued requires data.runId"))
    return RunSnapshot.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "RunSnapshot",
            "projectId": event.data.project_id,
            "experimentRevision": event.data.experiment_revision,
            "runId": run_id,
            "workflowId": payload.workflow_id,
            "digests": {
                "spec": payload.spec_digest,
                "registry": payload.registry_digest,
                "plan": payload.plan_digest,
            },
            "maxAttempts": payload.max_attempts,
            "status": RunStatus.QUEUED,
            "cancellationRequested": False,
            "activeAttemptId": None,
            "attempts": (),
            "lastEventId": event.id,
            "lastSequence": int(event.sequence),
            "review": {
                "reviewed": False,
                "eventId": None,
                "sequence": None,
                "decisionId": None,
            },
        }
    )


def _apply_run_event(state: RunSnapshot, event: ResearchEvent, payload: object) -> RunSnapshot:
    if event.type == TYPE_RUN_QUEUED:
        raise RunTransitionError(
            _event_label(event, "run.queued is only valid as the first lifecycle event")
        )
    if event.type == TYPE_RUN_STARTED:
        if state.status is not RunStatus.QUEUED:
            raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
        return _stamp(state, event, status=RunStatus.RUNNING)
    if event.type == TYPE_RUN_CANCEL_REQUESTED:
        if state.status not in RUN_CANCEL_REQUEST_STATUSES:
            raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
        return _stamp(state, event, cancellation_requested=True)
    if event.type == TYPE_RUN_COMPLETED:
        latest = _latest_attempt(state)
        if (
            latest is None
            or latest.status is not AttemptStatus.SUCCEEDED
            or _unresolved_attempt(state) is not None
        ):
            raise RunTransitionError(
                _event_label(
                    event,
                    "run.completed requires the latest attempt to have succeeded",
                )
            )
        return _stamp(state, event, status=RunStatus.COMPLETED, active_attempt_id=None)
    if event.type == TYPE_RUN_FAILED:
        latest = _latest_attempt(state)
        if (
            latest is None
            or latest.status is not AttemptStatus.FAILED
            or _unresolved_attempt(state) is not None
        ):
            raise RunTransitionError(
                _event_label(
                    event,
                    "run.failed requires the latest attempt to have failed",
                )
            )
        return _stamp(state, event, status=RunStatus.FAILED, active_attempt_id=None)
    if event.type == TYPE_RUN_CANCELLED:
        return _apply_run_cancelled(state, event)
    raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))


def _apply_run_cancelled(state: RunSnapshot, event: ResearchEvent) -> RunSnapshot:
    if not state.cancellation_requested:
        raise RunTransitionError(_event_label(event, "cancelled without a cancellation request"))
    if _unresolved_attempt(state) is not None:
        raise RunTransitionError(
            _event_label(event, "run.cancelled requires no unresolved attempt")
        )
    latest = _latest_attempt(state)
    if latest is not None and latest.status is not AttemptStatus.CANCELLED:
        raise RunTransitionError(
            _event_label(
                event,
                "run.cancelled cannot infer cancelled from failed, lost or unknown",
            )
        )
    return _stamp(state, event, status=RunStatus.CANCELLED, active_attempt_id=None)


def _apply_run_reviewed(state: RunSnapshot, event: ResearchEvent, payload: object) -> RunSnapshot:
    if state.status not in TERMINAL_RUN_STATUSES:
        raise RunTransitionError(
            _event_label(event, "run.reviewed is only allowed after a terminal run status")
        )
    if state.review.reviewed:
        raise RunTransitionError(_event_label(event, "run.reviewed can occur only once"))
    if not isinstance(payload, RunReviewedPayload):
        raise RunPayloadError(_event_label(event, "invalid payload for lifecycle type"))
    return _stamp(
        state,
        event,
        review=RunReview.model_validate(
            {
                "reviewed": True,
                "eventId": event.id,
                "sequence": int(event.sequence),
                "decisionId": payload.decision_id,
            }
        ),
    )


def _apply_attempt_event(state: RunSnapshot, event: ResearchEvent, payload: object) -> RunSnapshot:
    attempt_id = event.data.attempt_id
    if attempt_id is None:
        raise RunTransitionError(
            _event_label(event, "attempt lifecycle events require a non-empty attemptId")
        )
    if event.type == TYPE_ATTEMPT_QUEUED:
        return _apply_attempt_queued(state, event, payload, attempt_id)
    existing = _find_attempt(state, attempt_id)
    if existing is not None and existing.status in TERMINAL_ATTEMPT_STATUSES:
        raise RunTransitionError(_event_label(event, "terminal attempt cannot be rewritten"))
    if state.active_attempt_id != attempt_id:
        raise RunTransitionError(
            _event_label(event, "attempt lifecycle must target the active attempt")
        )
    attempt = _require_attempt(state, attempt_id)
    if event.type == TYPE_ATTEMPT_STARTED:
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_START_STATUSES,
            new_status=AttemptStatus.RUNNING,
            run_status=RunStatus.RUNNING,
        )
    if event.type == TYPE_ATTEMPT_HEARTBEAT:
        if attempt.status not in ATTEMPT_HEARTBEAT_STATUSES:
            raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
        sequence = int(event.sequence)
        updated = attempt.model_copy(
            update={
                "last_event_id": event.id,
                "last_sequence": sequence,
                "last_heartbeat_sequence": sequence,
            }
        )
        return _replace_attempt(state, event, updated)
    if event.type == TYPE_ATTEMPT_CANCEL_REQUESTED:
        if attempt.status not in ATTEMPT_CANCEL_REQUEST_STATUSES:
            raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
        updated = attempt.model_copy(
            update={
                "cancellation_requested": True,
                "last_event_id": event.id,
                "last_sequence": int(event.sequence),
            }
        )
        return _replace_attempt(state, event, updated)
    if event.type == TYPE_ATTEMPT_UNKNOWN:
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_UNKNOWN_STATUSES,
            new_status=AttemptStatus.UNKNOWN,
            run_status=RunStatus.UNKNOWN,
        )
    if event.type == TYPE_ATTEMPT_LOST:
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_LOST_STATUSES,
            new_status=AttemptStatus.LOST,
            run_status=RunStatus.LOST,
        )
    if event.type == TYPE_ATTEMPT_RECOVERED:
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_RECOVERED_STATUSES,
            new_status=AttemptStatus.RUNNING,
            run_status=RunStatus.RUNNING,
        )
    if event.type == TYPE_ATTEMPT_SUCCEEDED:
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_SUCCEEDED_STATUSES,
            new_status=AttemptStatus.SUCCEEDED,
            run_status=RunStatus.RUNNING,
            active_attempt_id=None,
        )
    if event.type == TYPE_ATTEMPT_FAILED:
        if not isinstance(payload, AttemptFailedPayload):
            raise RunPayloadError(_event_label(event, "invalid payload for lifecycle type"))
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_FAILED_STATUSES,
            new_status=AttemptStatus.FAILED,
            run_status=RunStatus.RETRY_PENDING,
            active_attempt_id=None,
            retry_hint=payload.retry_hint,
        )
    if event.type == TYPE_ATTEMPT_CANCELLED:
        if not state.cancellation_requested and not attempt.cancellation_requested:
            raise RunTransitionError(
                _event_label(event, "cancelled without a cancellation request")
            )
        return _transition_attempt(
            state,
            event,
            attempt,
            allowed=ATTEMPT_CANCELLED_STATUSES,
            new_status=AttemptStatus.CANCELLED,
            run_status=RunStatus.RUNNING,
            active_attempt_id=None,
        )
    raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))


def _apply_attempt_queued(
    state: RunSnapshot,
    event: ResearchEvent,
    payload: object,
    attempt_id: str,
) -> RunSnapshot:
    if not isinstance(payload, AttemptQueuedPayload):
        raise RunPayloadError(_event_label(event, "invalid payload for lifecycle type"))
    if state.status is RunStatus.QUEUED:
        raise RunTransitionError(
            _event_label(event, "attempt.queued requires the run to have started")
        )
    if state.cancellation_requested:
        raise RunTransitionError(
            _event_label(event, "attempt.queued is forbidden after cancellation was requested")
        )
    unresolved = _unresolved_attempt(state)
    if unresolved is not None:
        if unresolved.status in {AttemptStatus.LOST, AttemptStatus.UNKNOWN}:
            raise RunTransitionError(
                _event_label(event, "retry is forbidden while an attempt is lost or unknown")
            )
        raise RunTransitionError(
            _event_label(event, "attempt.queued requires no unresolved attempt")
        )
    if _find_attempt(state, attempt_id) is not None:
        raise RunTransitionError(_event_label(event, "attempt ID was reused"))
    if len(state.attempts) >= state.max_attempts:
        raise RunTransitionError(_event_label(event, "maxAttempts would be exceeded"))
    latest = _latest_attempt(state)
    if latest is None:
        if (
            payload.ordinal != 1
            or payload.retry_of is not None
            or payload.retry_decision_id is not None
        ):
            raise RunTransitionError(
                _event_label(
                    event,
                    "the first attempt must have ordinal 1 and null retry fields",
                )
            )
        if state.status is not RunStatus.RUNNING:
            raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
    else:
        if latest.status is not AttemptStatus.FAILED:
            raise RunTransitionError(
                _event_label(event, "retry is only allowed after the latest attempt failed")
            )
        if payload.ordinal != latest.ordinal + 1:
            raise RunTransitionError(_event_label(event, "attempt ordinal skipped"))
        if payload.retry_of != latest.attempt_id:
            raise RunTransitionError(
                _event_label(event, "retryOf is not the latest failed attempt")
            )
        if payload.retry_decision_id is None:
            raise RunTransitionError(_event_label(event, "retryDecisionId is required"))
    sequence = int(event.sequence)
    attempt = AttemptSnapshot.model_validate(
        {
            "attemptId": attempt_id,
            "ordinal": payload.ordinal,
            "retryOf": payload.retry_of,
            "retryDecisionId": payload.retry_decision_id,
            "status": AttemptStatus.QUEUED,
            "cancellationRequested": False,
            "retryHint": None,
            "lastEventId": event.id,
            "lastSequence": sequence,
            "lastHeartbeatSequence": None,
        }
    )
    return _stamp(
        state,
        event,
        status=RunStatus.RUNNING,
        active_attempt_id=attempt_id,
        attempts=(*state.attempts, attempt),
    )


def _transition_attempt(
    state: RunSnapshot,
    event: ResearchEvent,
    attempt: AttemptSnapshot,
    *,
    allowed: frozenset[AttemptStatus],
    new_status: AttemptStatus,
    run_status: RunStatus,
    active_attempt_id: str | object | None = _CURSOR_UNSET,
    retry_hint: object = _CURSOR_UNSET,
) -> RunSnapshot:
    if attempt.status not in allowed:
        raise RunTransitionError(_event_label(event, "illegal lifecycle transition"))
    updates: dict[str, Any] = {
        "status": new_status,
        "last_event_id": event.id,
        "last_sequence": int(event.sequence),
    }
    if retry_hint is not _CURSOR_UNSET:
        updates["retry_hint"] = retry_hint
    updated = attempt.model_copy(update=updates)
    next_active = attempt.attempt_id if active_attempt_id is _CURSOR_UNSET else active_attempt_id
    return _replace_attempt(
        state,
        event,
        updated,
        status=run_status,
        active_attempt_id=next_active,
    )


def _stamp(state: RunSnapshot, event: ResearchEvent, **updates: Any) -> RunSnapshot:
    copied = state.model_copy(
        update={
            "last_event_id": event.id,
            "last_sequence": int(event.sequence),
            **updates,
        }
    )
    # model_copy(update=...) does not re-run validators; keep reducer output honest.
    try:
        assert_run_snapshot_invariants(copied)
    except ValueError as exc:
        raise RunTransitionError(_event_label(event, str(exc))) from None
    return copied


def _replace_attempt(
    state: RunSnapshot,
    event: ResearchEvent,
    attempt: AttemptSnapshot,
    *,
    status: RunStatus | None = None,
    active_attempt_id: str | object | None = _CURSOR_UNSET,
) -> RunSnapshot:
    attempts = tuple(
        attempt if item.attempt_id == attempt.attempt_id else item for item in state.attempts
    )
    updates: dict[str, Any] = {"attempts": attempts}
    if status is not None:
        updates["status"] = status
    if active_attempt_id is not _CURSOR_UNSET:
        updates["active_attempt_id"] = active_attempt_id
    return _stamp(state, event, **updates)


def _find_attempt(state: RunSnapshot, attempt_id: str) -> AttemptSnapshot | None:
    for attempt in state.attempts:
        if attempt.attempt_id == attempt_id:
            return attempt
    return None


def _require_attempt(state: RunSnapshot, attempt_id: str) -> AttemptSnapshot:
    attempt = _find_attempt(state, attempt_id)
    if attempt is None:
        raise RunTransitionError("attempt lifecycle must target an existing attempt")
    return attempt


def _latest_attempt(state: RunSnapshot) -> AttemptSnapshot | None:
    if not state.attempts:
        return None
    return state.attempts[-1]


def _unresolved_attempt(state: RunSnapshot) -> AttemptSnapshot | None:
    unresolved = [
        attempt for attempt in state.attempts if attempt.status in UNRESOLVED_ATTEMPT_STATUSES
    ]
    if not unresolved:
        return None
    return unresolved[0]
