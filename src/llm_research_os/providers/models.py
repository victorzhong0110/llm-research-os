"""Closed v0alpha1 payloads for ``ai.call.*`` facts and fixture documents."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import LEGACY_SHA256_PREFIX
from llm_research_os.events.models import (
    ActorKind,
    CloudEventsString,
    EventDocumentModel,
    EventIdentifier,
    EventPayload,
    ResearchEvent,
)
from llm_research_os.providers.capabilities import ModelCapability, coerce_capability
from llm_research_os.providers.errors import ModelPayloadError
from llm_research_os.research.models import JcsDigest, require_json_array

TYPE_AI_CALL_STARTED = "ai.call.started"
TYPE_AI_CALL_COMPLETED = "ai.call.completed"
TYPE_AI_CALL_FAILED = "ai.call.failed"
AI_CALL_EVENT_TYPES = frozenset({TYPE_AI_CALL_STARTED, TYPE_AI_CALL_COMPLETED, TYPE_AI_CALL_FAILED})
INLINE_MODEL_KEYS = frozenset(
    {
        "choices",
        "completion",
        "delta",
        "input",
        "messages",
        "output",
        "prompt",
        "response",
    }
)
MAX_CAPABILITY_LIST = 8
ARTIFACT_DIGEST_LENGTH = len(LEGACY_SHA256_PREFIX) + 64
MODEL_FIXTURE_SCHEMA_ID = "https://researchos.dev/schemas/model-fixture/v0alpha1.schema.json"

ArtifactDigest = Annotated[
    str,
    StringConstraints(
        min_length=ARTIFACT_DIGEST_LENGTH,
        max_length=ARTIFACT_DIGEST_LENGTH,
        strip_whitespace=False,
        pattern=rf"^{LEGACY_SHA256_PREFIX}[0-9a-f]{{64}}$",
    ),
]


def _capability_tuple(value: object, field: str) -> object:
    items = require_json_array(value, field)
    if type(items) is not tuple:
        return items
    return tuple(coerce_capability(item) for item in items)


class ProviderDocumentModel(EventDocumentModel):
    """Frozen provider documents: aliases only, strict, no trimming."""

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


class ModelFixtureDocument(ProviderDocumentModel):
    """Local fixture used by ``DeterministicMockProvider``. Prompt/output stay off events."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ModelFixture"]
    id: EventIdentifier
    prompt: EventPayload
    output: EventPayload


class AiCallStartedPayload(ProviderDocumentModel):
    call_id: EventIdentifier = Field(alias="callId")
    provider_id: EventIdentifier = Field(alias="providerId")
    model_id: EventIdentifier = Field(alias="modelId")
    prompt_digest: JcsDigest = Field(alias="promptDigest")
    requested_capabilities: tuple[ModelCapability, ...] = Field(
        alias="requestedCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    declared_capabilities: tuple[ModelCapability, ...] = Field(
        alias="declaredCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    measured_capabilities: tuple[ModelCapability, ...] = Field(
        alias="measuredCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    allowed_capabilities: tuple[ModelCapability, ...] = Field(
        alias="allowedCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    local: bool
    cost_known: bool = Field(alias="costKnown")
    data_leaves_machine: bool = Field(alias="dataLeavesMachine")
    context_tokens: int = Field(alias="contextTokens", ge=1, le=2_147_483_647)
    max_output_tokens: int = Field(alias="maxOutputTokens", ge=1, le=2_147_483_647)

    @field_validator(
        "requested_capabilities",
        "declared_capabilities",
        "measured_capabilities",
        "allowed_capabilities",
        mode="before",
    )
    @classmethod
    def json_capability_lists(cls, value: object) -> object:
        return _capability_tuple(value, "capabilities")

    @model_validator(mode="after")
    def capability_lists_are_unique_and_sorted(self) -> Self:
        for name, values in (
            ("requestedCapabilities", self.requested_capabilities),
            ("declaredCapabilities", self.declared_capabilities),
            ("measuredCapabilities", self.measured_capabilities),
            ("allowedCapabilities", self.allowed_capabilities),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} entries must be unique")
            names = tuple(item.value for item in values)
            if names != tuple(sorted(names)):
                raise ValueError(f"{name} entries must be sorted")
        return self


class AiCallCompletedPayload(ProviderDocumentModel):
    call_id: EventIdentifier = Field(alias="callId")
    output_digest: JcsDigest = Field(alias="outputDigest")
    declared_capabilities: tuple[ModelCapability, ...] = Field(
        alias="declaredCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    measured_capabilities: tuple[ModelCapability, ...] = Field(
        alias="measuredCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    allowed_capabilities: tuple[ModelCapability, ...] = Field(
        alias="allowedCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    prompt_artifact: ArtifactDigest | None = Field(default=None, alias="promptArtifact")
    output_artifact: ArtifactDigest | None = Field(default=None, alias="outputArtifact")

    @field_validator(
        "declared_capabilities",
        "measured_capabilities",
        "allowed_capabilities",
        mode="before",
    )
    @classmethod
    def json_capability_lists(cls, value: object) -> object:
        return _capability_tuple(value, "capabilities")

    @model_validator(mode="after")
    def capability_lists_are_unique_and_sorted(self) -> Self:
        for name, values in (
            ("declaredCapabilities", self.declared_capabilities),
            ("measuredCapabilities", self.measured_capabilities),
            ("allowedCapabilities", self.allowed_capabilities),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} entries must be unique")
            names = tuple(item.value for item in values)
            if names != tuple(sorted(names)):
                raise ValueError(f"{name} entries must be sorted")
        return self


class AiCallFailedPayload(ProviderDocumentModel):
    call_id: EventIdentifier = Field(alias="callId")
    reason_code: CloudEventsString = Field(alias="reasonCode")


PAYLOAD_MODELS: dict[str, type[ProviderDocumentModel]] = {
    TYPE_AI_CALL_STARTED: AiCallStartedPayload,
    TYPE_AI_CALL_COMPLETED: AiCallCompletedPayload,
    TYPE_AI_CALL_FAILED: AiCallFailedPayload,
}

if set(PAYLOAD_MODELS) != AI_CALL_EVENT_TYPES:
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the ai.call catalog")


def parse_ai_call_payload(event: ResearchEvent) -> ProviderDocumentModel:
    """Validate a closed ``ai.call.*`` payload without echoing fixture text."""

    _reject_inline_model_keys(event.data.payload)
    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        raise ModelPayloadError(
            f"event type is not an ai.call type (event id {event.id})",
            code="unknown-ai-call-type",
        )
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = ModelPayloadError(
            f"invalid payload for ai.call type {event.type} "
            f"(event id {event.id}, sequence {event.sequence})",
            code="invalid-payload",
        )
    else:
        return validated
    raise payload_error


def require_ai_actor(event: ResearchEvent) -> None:
    kind = event.data.actor.kind
    if kind is None:
        raise ModelPayloadError(
            f"actor kind is required for {event.type} (event id {event.id})",
            code="actor-kind-required",
        )
    if kind is not ActorKind.AI:
        raise ModelPayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
    if event.data.actor.model_id is None:
        raise ModelPayloadError(
            f"modelId is required for {event.type} (event id {event.id})",
            code="model-id-required",
        )


def _reject_inline_model_keys(payload: dict[str, Any]) -> None:
    stack: list[object] = [payload]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            blocked = sorted(key for key in current if key in INLINE_MODEL_KEYS)
            if blocked:
                raise ModelPayloadError(
                    "ai.call payload must not embed prompt or output text; "
                    f"forbidden keys: {blocked}",
                    code="inline-model-text",
                )
            stack.extend(current.values())
        elif type(current) is list:
            stack.extend(current)
