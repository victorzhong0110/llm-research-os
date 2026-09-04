"""Closed v0alpha1 Run/Attempt snapshot and lifecycle payload models.

External documents use Schema aliases only. Values are not trimmed, coerced,
or widened. Unknown structural fields are rejected.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import (
    SEMANTIC_DIGEST_MAX_LENGTH,
    SEMANTIC_DIGEST_MIN_LENGTH,
    SEMANTIC_DIGEST_PATTERN,
)
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    CloudEventsString,
    EventDocumentModel,
    EventIdentifier,
    ResearchEvent,
    SequenceIntegerString,
)
from llm_research_os.runs.errors import RunPayloadError

RUN_SNAPSHOT_SCHEMA_ID = "https://researchos.dev/schemas/run-state/v0alpha1.schema.json"
RUN_SNAPSHOT_API_VERSION = "researchos.dev/v0alpha1"
MAX_ATTEMPTS = 32

TYPE_RUN_QUEUED = "run.queued"
TYPE_RUN_STARTED = "run.started"
TYPE_RUN_CANCEL_REQUESTED = "run.cancel.requested"
TYPE_RUN_COMPLETED = "run.completed"
TYPE_RUN_FAILED = "run.failed"
TYPE_RUN_CANCELLED = "run.cancelled"
TYPE_RUN_REVIEWED = "run.reviewed"
TYPE_ATTEMPT_QUEUED = "attempt.queued"
TYPE_ATTEMPT_STARTED = "attempt.started"
TYPE_ATTEMPT_HEARTBEAT = "attempt.heartbeat"
TYPE_ATTEMPT_CANCEL_REQUESTED = "attempt.cancel.requested"
TYPE_ATTEMPT_UNKNOWN = "attempt.unknown"
TYPE_ATTEMPT_LOST = "attempt.lost"
TYPE_ATTEMPT_RECOVERED = "attempt.recovered"
TYPE_ATTEMPT_SUCCEEDED = "attempt.succeeded"
TYPE_ATTEMPT_FAILED = "attempt.failed"
TYPE_ATTEMPT_CANCELLED = "attempt.cancelled"

RUN_LIFECYCLE_TYPES = frozenset(
    {
        TYPE_RUN_QUEUED,
        TYPE_RUN_STARTED,
        TYPE_RUN_CANCEL_REQUESTED,
        TYPE_RUN_COMPLETED,
        TYPE_RUN_FAILED,
        TYPE_RUN_CANCELLED,
        TYPE_RUN_REVIEWED,
    }
)
ATTEMPT_LIFECYCLE_TYPES = frozenset(
    {
        TYPE_ATTEMPT_QUEUED,
        TYPE_ATTEMPT_STARTED,
        TYPE_ATTEMPT_HEARTBEAT,
        TYPE_ATTEMPT_CANCEL_REQUESTED,
        TYPE_ATTEMPT_UNKNOWN,
        TYPE_ATTEMPT_LOST,
        TYPE_ATTEMPT_RECOVERED,
        TYPE_ATTEMPT_SUCCEEDED,
        TYPE_ATTEMPT_FAILED,
        TYPE_ATTEMPT_CANCELLED,
    }
)
LIFECYCLE_TYPES = RUN_LIFECYCLE_TYPES | ATTEMPT_LIFECYCLE_TYPES

StrictDigest = Annotated[
    str,
    StringConstraints(
        min_length=SEMANTIC_DIGEST_MIN_LENGTH,
        max_length=SEMANTIC_DIGEST_MAX_LENGTH,
        strip_whitespace=False,
        pattern=SEMANTIC_DIGEST_PATTERN,
    ),
]
MaxAttempts = Annotated[int, Field(ge=1, le=MAX_ATTEMPTS)]
AttemptOrdinal = Annotated[int, Field(ge=1, le=MAX_ATTEMPTS)]
SequenceNumber = Annotated[int, Field(ge=1, le=CLOUD_EVENTS_INTEGER_MAX)]


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_PENDING = "retry_pending"
    LOST = "lost"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    LOST = "lost"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryHint(StrEnum):
    RETRYABLE = "retryable"
    NOT_RETRYABLE = "not-retryable"
    UNKNOWN = "unknown"


UNRESOLVED_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.QUEUED,
        AttemptStatus.RUNNING,
        AttemptStatus.LOST,
        AttemptStatus.UNKNOWN,
    }
)
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
    }
)
TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)
RUN_CANCEL_REQUEST_STATUSES = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.RETRY_PENDING,
        RunStatus.LOST,
        RunStatus.UNKNOWN,
    }
)
ATTEMPT_CANCEL_REQUEST_STATUSES = frozenset(
    {
        AttemptStatus.QUEUED,
        AttemptStatus.RUNNING,
        AttemptStatus.LOST,
        AttemptStatus.UNKNOWN,
    }
)
ATTEMPT_START_STATUSES = frozenset({AttemptStatus.QUEUED})
ATTEMPT_HEARTBEAT_STATUSES = frozenset({AttemptStatus.RUNNING})
ATTEMPT_UNKNOWN_STATUSES = frozenset({AttemptStatus.RUNNING})
ATTEMPT_LOST_STATUSES = frozenset({AttemptStatus.RUNNING, AttemptStatus.UNKNOWN})
ATTEMPT_RECOVERED_STATUSES = frozenset({AttemptStatus.LOST, AttemptStatus.UNKNOWN})
ATTEMPT_SUCCEEDED_STATUSES = frozenset(
    {AttemptStatus.RUNNING, AttemptStatus.LOST, AttemptStatus.UNKNOWN}
)
ATTEMPT_FAILED_STATUSES = frozenset(
    {
        AttemptStatus.QUEUED,
        AttemptStatus.RUNNING,
        AttemptStatus.LOST,
        AttemptStatus.UNKNOWN,
    }
)
ATTEMPT_CANCELLED_STATUSES = frozenset(
    {
        AttemptStatus.QUEUED,
        AttemptStatus.RUNNING,
        AttemptStatus.LOST,
        AttemptStatus.UNKNOWN,
    }
)


def _coerce_strenum(enum_type: type[StrEnum], value: object) -> object:
    if type(value) is str:
        try:
            return enum_type(value)
        except ValueError:
            return value
    return value


class RunStateDocumentModel(EventDocumentModel):
    """Frozen external Run-state documents: aliases only, strict, no trimming."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


class EmptyPayload(RunStateDocumentModel):
    """Closed empty object used by lifecycle types with no fields."""


class ReasonCodePayload(RunStateDocumentModel):
    reason_code: EventIdentifier = Field(alias="reasonCode")


def _reject_null_optional_digest(value: object, field: str) -> object:
    if type(value) is dict and value.get(field, "omitted") is None:
        raise ValueError(f"{field} must be omitted or a semantic digest")
    return value


class RunQueuedPayload(RunStateDocumentModel):
    workflow_id: EventIdentifier = Field(alias="workflowId")
    spec_digest: StrictDigest = Field(alias="specDigest")
    registry_digest: StrictDigest = Field(alias="registryDigest")
    plan_digest: StrictDigest = Field(alias="planDigest")
    decision_digest: StrictDigest | None = Field(default=None, alias="decisionDigest")
    authorization_event_id: CloudEventsString | None = Field(
        default=None, alias="authorizationEventId"
    )
    authorization_sequence: SequenceIntegerString | None = Field(
        default=None, alias="authorizationSequence"
    )
    max_attempts: MaxAttempts = Field(alias="maxAttempts")

    @model_validator(mode="before")
    @classmethod
    def reject_null_optional_queued_fields(cls, value: object) -> object:
        value = _reject_null_optional_digest(value, "decisionDigest")
        value = _reject_null_optional_digest(value, "authorizationEventId")
        return _reject_null_optional_digest(value, "authorizationSequence")

    @model_validator(mode="after")
    def authorization_citation_is_complete(self) -> Self:
        present = (
            self.authorization_event_id is not None,
            self.authorization_sequence is not None,
        )
        if present[0] != present[1]:
            raise ValueError(
                "authorizationEventId and authorizationSequence must both be "
                "present or both omitted"
            )
        return self


class RunReviewedPayload(RunStateDocumentModel):
    decision_id: EventIdentifier = Field(alias="decisionId")


class AttemptQueuedPayload(RunStateDocumentModel):
    ordinal: AttemptOrdinal
    retry_of: EventIdentifier | None = Field(alias="retryOf")
    retry_decision_id: EventIdentifier | None = Field(alias="retryDecisionId")


class AttemptFailedPayload(RunStateDocumentModel):
    reason_code: EventIdentifier = Field(alias="reasonCode")
    retry_hint: RetryHint = Field(alias="retryHint")

    @field_validator("retry_hint", mode="before")
    @classmethod
    def coerce_retry_hint(cls, value: object) -> object:
        return _coerce_strenum(RetryHint, value)


PAYLOAD_MODELS: dict[str, type[RunStateDocumentModel]] = {
    TYPE_RUN_QUEUED: RunQueuedPayload,
    TYPE_RUN_STARTED: EmptyPayload,
    TYPE_RUN_CANCEL_REQUESTED: ReasonCodePayload,
    TYPE_RUN_COMPLETED: EmptyPayload,
    TYPE_RUN_FAILED: ReasonCodePayload,
    TYPE_RUN_CANCELLED: EmptyPayload,
    TYPE_RUN_REVIEWED: RunReviewedPayload,
    TYPE_ATTEMPT_QUEUED: AttemptQueuedPayload,
    TYPE_ATTEMPT_STARTED: EmptyPayload,
    TYPE_ATTEMPT_HEARTBEAT: EmptyPayload,
    TYPE_ATTEMPT_CANCEL_REQUESTED: ReasonCodePayload,
    TYPE_ATTEMPT_UNKNOWN: ReasonCodePayload,
    TYPE_ATTEMPT_LOST: ReasonCodePayload,
    TYPE_ATTEMPT_RECOVERED: EmptyPayload,
    TYPE_ATTEMPT_SUCCEEDED: EmptyPayload,
    TYPE_ATTEMPT_FAILED: AttemptFailedPayload,
    TYPE_ATTEMPT_CANCELLED: EmptyPayload,
}

if set(PAYLOAD_MODELS) != LIFECYCLE_TYPES:
    # Kept as a hard check rather than `assert` so it survives `python -O`.
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the frozen lifecycle catalog")


class RunDigests(RunStateDocumentModel):
    spec: StrictDigest
    registry: StrictDigest
    plan: StrictDigest
    decision_digest: StrictDigest | None = Field(default=None, alias="decisionDigest")

    @model_validator(mode="before")
    @classmethod
    def reject_null_decision_digest(cls, value: object) -> object:
        return _reject_null_optional_digest(value, "decisionDigest")


class ConsumedAuthorization(RunStateDocumentModel):
    """Immutable citation of the local authorization fact this Run consumed."""

    event_id: CloudEventsString = Field(alias="eventId")
    sequence: SequenceNumber


class RunReview(RunStateDocumentModel):
    reviewed: bool
    event_id: CloudEventsString | None = Field(default=None, alias="eventId")
    sequence: SequenceNumber | None = None
    decision_id: EventIdentifier | None = Field(default=None, alias="decisionId")

    @model_validator(mode="after")
    def review_fields_are_consistent(self) -> Self:
        present = (
            self.event_id is not None,
            self.sequence is not None,
            self.decision_id is not None,
        )
        if self.reviewed:
            if not all(present):
                raise ValueError("reviewed runs require eventId, sequence and decisionId")
        elif any(present):
            raise ValueError("unreviewed runs must not record review identity")
        return self


class AttemptSnapshot(RunStateDocumentModel):
    attempt_id: EventIdentifier = Field(alias="attemptId")
    ordinal: AttemptOrdinal
    retry_of: EventIdentifier | None = Field(alias="retryOf")
    retry_decision_id: EventIdentifier | None = Field(alias="retryDecisionId")
    status: AttemptStatus
    cancellation_requested: bool = Field(alias="cancellationRequested")
    retry_hint: RetryHint | None = Field(alias="retryHint")
    last_event_id: CloudEventsString = Field(alias="lastEventId")
    last_sequence: SequenceNumber = Field(alias="lastSequence")
    last_heartbeat_sequence: SequenceNumber | None = Field(
        default=None, alias="lastHeartbeatSequence"
    )

    @field_validator("status", "retry_hint", mode="before")
    @classmethod
    def coerce_attempt_enums(cls, value: object) -> object:
        if value is None:
            return None
        coerced_status = _coerce_strenum(AttemptStatus, value)
        if coerced_status is not value:
            return coerced_status
        return _coerce_strenum(RetryHint, value)

    @model_validator(mode="after")
    def attempt_fields_are_consistent(self) -> Self:
        if self.ordinal == 1:
            if self.retry_of is not None or self.retry_decision_id is not None:
                raise ValueError("the first attempt must not declare retry identity")
        elif self.retry_of is None or self.retry_decision_id is None:
            raise ValueError("retry attempts require retryOf and retryDecisionId")
        if self.status is AttemptStatus.FAILED:
            if self.retry_hint is None:
                raise ValueError("failed attempts require retryHint")
        elif self.retry_hint is not None:
            raise ValueError("retryHint is only recorded on failed attempts")
        if (
            self.last_heartbeat_sequence is not None
            and self.last_heartbeat_sequence > self.last_sequence
        ):
            raise ValueError("lastHeartbeatSequence must not exceed the attempt lastSequence")
        return self


class RunSnapshot(RunStateDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["RunSnapshot"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: Annotated[int, Field(ge=1, le=CLOUD_EVENTS_INTEGER_MAX)] = Field(
        alias="experimentRevision"
    )
    run_id: EventIdentifier = Field(alias="runId")
    workflow_id: EventIdentifier = Field(alias="workflowId")
    digests: RunDigests
    max_attempts: MaxAttempts = Field(alias="maxAttempts")
    status: RunStatus
    cancellation_requested: bool = Field(alias="cancellationRequested")
    active_attempt_id: EventIdentifier | None = Field(alias="activeAttemptId")
    attempts: tuple[AttemptSnapshot, ...] = Field(default=(), max_length=MAX_ATTEMPTS)
    last_event_id: CloudEventsString = Field(alias="lastEventId")
    last_sequence: SequenceNumber = Field(alias="lastSequence")
    review: RunReview
    consumed_authorization: ConsumedAuthorization | None = Field(
        default=None, alias="consumedAuthorization"
    )

    @model_validator(mode="before")
    @classmethod
    def reject_null_consumed_authorization(cls, value: object) -> object:
        if type(value) is dict and value.get("consumedAuthorization", "omitted") is None:
            raise ValueError("consumedAuthorization must be omitted or an object")
        return value

    @field_validator("status", mode="before")
    @classmethod
    def coerce_run_status(cls, value: object) -> object:
        return _coerce_strenum(RunStatus, value)

    @field_validator("attempts", mode="before")
    @classmethod
    def json_attempts_are_tuples(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        return value

    @model_validator(mode="after")
    def snapshot_invariants_hold(self) -> Self:
        assert_run_snapshot_invariants(self)
        return self


def assert_run_snapshot_invariants(snapshot: RunSnapshot) -> None:
    """Raise ValueError if a snapshot violates protocol semantics.

    JSON Schema stays structural. These cross-field rules are enforced here so
    that external documents, checkpoints, and reducer outputs share one check.
    ``model_copy(update=...)`` does not re-run validators, so the reducer must
    call this after internal updates.
    """

    ordinals = [attempt.ordinal for attempt in snapshot.attempts]
    if ordinals != list(range(1, len(snapshot.attempts) + 1)):
        raise ValueError("attempts must be stored by contiguous ordinal starting at 1")
    attempt_ids = [attempt.attempt_id for attempt in snapshot.attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("attempt IDs must be unique")
    unresolved = [
        attempt for attempt in snapshot.attempts if attempt.status in UNRESOLVED_ATTEMPT_STATUSES
    ]
    if len(unresolved) > 1:
        raise ValueError("a run may have at most one unresolved attempt")
    expected_active = unresolved[0].attempt_id if unresolved else None
    if snapshot.active_attempt_id != expected_active:
        raise ValueError("activeAttemptId must match the unresolved attempt")
    if snapshot.review.reviewed and snapshot.status not in TERMINAL_RUN_STATUSES:
        raise ValueError("reviewed is only derived after a terminal run status")
    if len(snapshot.attempts) > snapshot.max_attempts:
        raise ValueError("attempts exceed maxAttempts")
    _assert_run_status_matches_attempts(snapshot, unresolved)
    _assert_retry_chain(snapshot.attempts)
    _assert_sequence_cursors(snapshot)


def _assert_run_status_matches_attempts(
    snapshot: RunSnapshot,
    unresolved: list[AttemptSnapshot],
) -> None:
    latest = snapshot.attempts[-1] if snapshot.attempts else None
    active = unresolved[0] if unresolved else None
    status = snapshot.status
    if status is RunStatus.QUEUED:
        if snapshot.attempts:
            raise ValueError("queued runs must not have attempts")
        if snapshot.active_attempt_id is not None:
            raise ValueError("queued runs must not have an active attempt")
        return
    if status is RunStatus.LOST:
        if active is None or active.status is not AttemptStatus.LOST:
            raise ValueError("lost runs require a unique active lost attempt")
        return
    if status is RunStatus.UNKNOWN:
        if active is None or active.status is not AttemptStatus.UNKNOWN:
            raise ValueError("unknown runs require a unique active unknown attempt")
        return
    if status is RunStatus.RETRY_PENDING:
        if active is not None:
            raise ValueError("retry_pending runs must not have an active attempt")
        if latest is None or latest.status is not AttemptStatus.FAILED:
            raise ValueError("retry_pending runs require the latest attempt to have failed")
        return
    if status is RunStatus.COMPLETED:
        if active is not None:
            raise ValueError("completed runs must not have an active attempt")
        if latest is None or latest.status is not AttemptStatus.SUCCEEDED:
            raise ValueError("completed runs require the latest attempt to have succeeded")
        return
    if status is RunStatus.FAILED:
        if active is not None:
            raise ValueError("failed runs must not have an active attempt")
        if latest is None or latest.status is not AttemptStatus.FAILED:
            raise ValueError("failed runs require the latest attempt to have failed")
        return
    if status is RunStatus.CANCELLED:
        if not snapshot.cancellation_requested:
            raise ValueError("cancelled runs require a cancellation request")
        if active is not None:
            raise ValueError("cancelled runs must not have an active attempt")
        if latest is not None and latest.status is not AttemptStatus.CANCELLED:
            raise ValueError("cancelled runs require no attempts or a latest cancelled attempt")
        return
    if status is RunStatus.RUNNING:
        no_attempts = latest is None
        active_in_progress = active is not None and active.status in {
            AttemptStatus.QUEUED,
            AttemptStatus.RUNNING,
        }
        settled_latest = (
            active is None
            and latest is not None
            and latest.status in {AttemptStatus.SUCCEEDED, AttemptStatus.CANCELLED}
        )
        if not (no_attempts or active_in_progress or settled_latest):
            raise ValueError("running runs only allow reachable intermediate attempt states")
        return
    raise ValueError("unsupported run status")


def _assert_retry_chain(attempts: tuple[AttemptSnapshot, ...]) -> None:
    for index, attempt in enumerate(attempts):
        if index == 0:
            if attempt.retry_of is not None or attempt.retry_decision_id is not None:
                raise ValueError("the first attempt must not declare retry identity")
            continue
        previous = attempts[index - 1]
        if previous.status is not AttemptStatus.FAILED:
            raise ValueError("retry attempts require the previous attempt to have failed")
        if attempt.retry_of != previous.attempt_id:
            raise ValueError("retryOf must equal the previous attempt id")
        if attempt.retry_decision_id is None:
            raise ValueError("retry attempts require retryOf and retryDecisionId")


def _assert_sequence_cursors(snapshot: RunSnapshot) -> None:
    previous_sequence = 0
    for attempt in snapshot.attempts:
        if attempt.last_sequence > snapshot.last_sequence:
            raise ValueError("attempt lastSequence must not exceed the run lastSequence")
        if (
            attempt.last_heartbeat_sequence is not None
            and attempt.last_heartbeat_sequence > attempt.last_sequence
        ):
            raise ValueError("lastHeartbeatSequence must not exceed the attempt lastSequence")
        if attempt.last_sequence <= previous_sequence:
            raise ValueError("attempt lastSequence must strictly increase by ordinal")
        previous_sequence = attempt.last_sequence
    if snapshot.review.reviewed:
        review_sequence = snapshot.review.sequence
        if review_sequence is not None and review_sequence > snapshot.last_sequence:
            raise ValueError("review sequence must not exceed the run lastSequence")


def parse_lifecycle_payload(event: ResearchEvent) -> RunStateDocumentModel:
    """Validate a closed lifecycle payload without echoing its body."""

    model = PAYLOAD_MODELS[event.type]
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = RunPayloadError(_payload_error_message(event))
    else:
        return validated
    # Raise outside the except so ValidationError is not attached as context.
    raise payload_error


def validate_run_snapshot_document(document: dict[str, Any]) -> RunSnapshot:
    """Validate an external RunSnapshot JSON document."""

    return RunSnapshot.model_validate(document)


def run_snapshot_document(snapshot: RunSnapshot) -> dict[str, Any]:
    """Return the deterministic alias-keyed JSON object for a snapshot."""

    payload = snapshot.model_dump(mode="json", by_alias=True)
    digests = payload.get("digests")
    if type(digests) is dict and digests.get("decisionDigest") is None:
        digests.pop("decisionDigest", None)
    if payload.get("consumedAuthorization") is None:
        payload.pop("consumedAuthorization", None)
    return payload


def _payload_error_message(event: ResearchEvent) -> str:
    return (
        f"invalid payload for lifecycle type {event.type} "
        f"(event id {event.id}, sequence {event.sequence})"
    )
