"""Closed v0alpha1 payloads for Worker, work-lease, and HMAC grant facts."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, field_serializer, field_validator

from llm_research_os.events.models import (
    ActorKind,
    CloudEventsString,
    EventDocumentModel,
    EventIdentifier,
    ResearchEvent,
    Rfc3339Timestamp,
)
from llm_research_os.research.models import require_json_array
from llm_research_os.workers.errors import WorkerPayloadError

TYPE_WORKER_REGISTERED = "worker.registered"
TYPE_WORK_QUEUED = "work.queued"
TYPE_WORK_LEASED = "work.leased"
TYPE_WORK_CLAIMED = "work.claimed"
TYPE_WORK_COMPLETED = "work.completed"
TYPE_WORK_FAILED = "work.failed"
TYPE_WORK_LEASE_EXPIRED = "work.lease.expired"
TYPE_GRANT_RECORDED = "authorization.grant.recorded"
TYPE_GRANT_REVOKED = "authorization.grant.revoked"
TYPE_GRANT_CONSUMED = "authorization.grant.consumed"
WORKER_EVENT_TYPES = frozenset(
    {
        TYPE_WORKER_REGISTERED,
        TYPE_WORK_QUEUED,
        TYPE_WORK_LEASED,
        TYPE_WORK_CLAIMED,
        TYPE_WORK_COMPLETED,
        TYPE_WORK_FAILED,
        TYPE_WORK_LEASE_EXPIRED,
        TYPE_GRANT_RECORDED,
        TYPE_GRANT_REVOKED,
        TYPE_GRANT_CONSUMED,
    }
)
WORKER_RUNTIME_PYTHON_SANDBOX: Literal["python-sandbox"] = "python-sandbox"
WORKER_PROTOCOL_LONGPOLL: Literal["researchos.worker-longpoll/v0alpha1"] = (
    "researchos.worker-longpoll/v0alpha1"
)
IMAGE_MEDIA_PYTHON_BRICK: Literal["researchos.python-brick/v0alpha1"] = (
    "researchos.python-brick/v0alpha1"
)
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
MAX_ACCELERATORS = 8


class WorkerDocumentModel(EventDocumentModel):
    """Frozen Worker documents: aliases only, strict, no trimming."""

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


class WorkerRegisteredPayload(WorkerDocumentModel):
    worker_id: EventIdentifier = Field(alias="workerId")
    runtime: Literal["python-sandbox"] = WORKER_RUNTIME_PYTHON_SANDBOX
    protocol: Literal["researchos.worker-longpoll/v0alpha1"] = WORKER_PROTOCOL_LONGPOLL
    accelerators: tuple[EventIdentifier, ...] = Field(default=())

    @field_validator("accelerators", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "accelerators")

    @field_validator("accelerators")
    @classmethod
    def accelerators_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_ACCELERATORS:
            raise ValueError("accelerators exceeds the closed list limit")
        if len(value) != len(set(value)):
            raise ValueError("accelerators entries must be unique")
        return value

    @field_serializer("accelerators")
    def serialize_accelerators(self, values: tuple[str, ...]) -> list[str]:
        return list(values)


class WorkQueuedPayload(WorkerDocumentModel):
    task_id: EventIdentifier = Field(alias="taskId")
    image_digest: CloudEventsString = Field(alias="imageDigest", pattern=DIGEST_PATTERN)
    image_media_type: Literal["researchos.python-brick/v0alpha1"] = Field(
        default=IMAGE_MEDIA_PYTHON_BRICK,
        alias="imageMediaType",
    )
    runtime: Literal["python-sandbox"] = WORKER_RUNTIME_PYTHON_SANDBOX
    required_accelerators: tuple[EventIdentifier, ...] = Field(
        default=(),
        alias="requiredAccelerators",
    )

    @field_validator("required_accelerators", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "requiredAccelerators")

    @field_validator("required_accelerators")
    @classmethod
    def accelerators_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_ACCELERATORS:
            raise ValueError("requiredAccelerators exceeds the closed list limit")
        if len(value) != len(set(value)):
            raise ValueError("requiredAccelerators entries must be unique")
        return value

    @field_serializer("required_accelerators")
    def serialize_accelerators(self, values: tuple[str, ...]) -> list[str]:
        return list(values)


class WorkLeasedPayload(WorkerDocumentModel):
    lease_id: EventIdentifier = Field(alias="leaseId")
    worker_id: EventIdentifier = Field(alias="workerId")
    task_id: EventIdentifier = Field(alias="taskId")
    grant_id: EventIdentifier = Field(alias="grantId")
    expires_at: Rfc3339Timestamp = Field(alias="expiresAt")


class WorkClaimedPayload(WorkerDocumentModel):
    lease_id: EventIdentifier = Field(alias="leaseId")
    worker_id: EventIdentifier = Field(alias="workerId")
    nonce: EventIdentifier


class WorkCompletedPayload(WorkerDocumentModel):
    lease_id: EventIdentifier = Field(alias="leaseId")
    result_digest: CloudEventsString = Field(alias="resultDigest", pattern=DIGEST_PATTERN)
    artifact_digest: CloudEventsString = Field(alias="artifactDigest", pattern=DIGEST_PATTERN)


class WorkFailedPayload(WorkerDocumentModel):
    lease_id: EventIdentifier = Field(alias="leaseId")
    reason_code: EventIdentifier = Field(alias="reasonCode")


class WorkLeaseExpiredPayload(WorkerDocumentModel):
    lease_id: EventIdentifier = Field(alias="leaseId")
    reason_code: EventIdentifier = Field(alias="reasonCode")


class GrantRecordedPayload(WorkerDocumentModel):
    grant_id: EventIdentifier = Field(alias="grantId")
    worker_id: EventIdentifier = Field(alias="workerId")
    task_id: EventIdentifier = Field(alias="taskId")
    nonce: EventIdentifier
    expires_at: Rfc3339Timestamp = Field(alias="expiresAt")
    key_id: Literal["local.hmac.1"] = Field(alias="keyId")


class GrantRevokedPayload(WorkerDocumentModel):
    grant_id: EventIdentifier = Field(alias="grantId")
    reason_code: EventIdentifier = Field(alias="reasonCode")


class GrantConsumedPayload(WorkerDocumentModel):
    grant_id: EventIdentifier = Field(alias="grantId")
    lease_id: EventIdentifier = Field(alias="leaseId")
    nonce: EventIdentifier


PAYLOAD_MODELS: dict[str, type[WorkerDocumentModel]] = {
    TYPE_WORKER_REGISTERED: WorkerRegisteredPayload,
    TYPE_WORK_QUEUED: WorkQueuedPayload,
    TYPE_WORK_LEASED: WorkLeasedPayload,
    TYPE_WORK_CLAIMED: WorkClaimedPayload,
    TYPE_WORK_COMPLETED: WorkCompletedPayload,
    TYPE_WORK_FAILED: WorkFailedPayload,
    TYPE_WORK_LEASE_EXPIRED: WorkLeaseExpiredPayload,
    TYPE_GRANT_RECORDED: GrantRecordedPayload,
    TYPE_GRANT_REVOKED: GrantRevokedPayload,
    TYPE_GRANT_CONSUMED: GrantConsumedPayload,
}

if set(PAYLOAD_MODELS) != WORKER_EVENT_TYPES:
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the Worker event catalog")

_HUMAN_TYPES = frozenset({TYPE_WORKER_REGISTERED, TYPE_GRANT_RECORDED, TYPE_GRANT_REVOKED})
_SYSTEM_TYPES = WORKER_EVENT_TYPES - _HUMAN_TYPES


def parse_worker_payload(event: ResearchEvent) -> WorkerDocumentModel:
    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        raise WorkerPayloadError(
            f"event type is not a worker type (event id {event.id})",
            code="unknown-worker-type",
        )
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = WorkerPayloadError(
            f"invalid payload for worker type {event.type} "
            f"(event id {event.id}, sequence {event.sequence})",
            code="invalid-payload",
        )
    else:
        return validated
    raise payload_error


def require_worker_actor(event: ResearchEvent) -> None:
    kind = event.data.actor.kind
    if kind is None:
        raise WorkerPayloadError(
            f"actor kind is required for {event.type} (event id {event.id})",
            code="actor-kind-required",
        )
    if event.type in _HUMAN_TYPES and kind is not ActorKind.HUMAN:
        raise WorkerPayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
    if event.type in _SYSTEM_TYPES and kind is not ActorKind.SYSTEM:
        raise WorkerPayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
