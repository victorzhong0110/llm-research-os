"""Strict request document for one OpenAI-compatible generate plus budget facts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Self
from urllib.parse import urlparse

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from llm_research_os.budget.models import (
    TYPE_BUDGET_CONSUMED,
    TYPE_BUDGET_EXCEEDED,
    TYPE_BUDGET_RELEASED,
    TYPE_BUDGET_RESERVED,
)
from llm_research_os.budget.money import ZERO_MONEY, MoneyAmount, parse_money
from llm_research_os.events.models import (
    ActorKind,
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
)
from llm_research_os.policy.capabilities import (
    KernelCapability,
    coerce_kernel_capability,
    require_known_kernel_capabilities,
)
from llm_research_os.providers.capabilities import ModelCapability, sorted_capability_names
from llm_research_os.providers.endpoint import (
    EndpointKind,
    classify_literal_endpoint,
    endpoint_is_loopback,
)
from llm_research_os.providers.errors import ModelRequestError
from llm_research_os.providers.models import (
    MAX_CAPABILITY_LIST,
    TYPE_AI_CALL_COMPLETED,
    TYPE_AI_CALL_FAILED,
    TYPE_AI_CALL_STARTED,
    ProviderDocumentModel,
    _capability_tuple,
)
from llm_research_os.providers.provider import GenerateRequest, ModelIdentity
from llm_research_os.providers.requests import ModelEventIdentity, _actor_document, _event_draft
from llm_research_os.research.models import require_json_array
from llm_research_os.secrets.models import SecretRef
from llm_research_os.spec.io import load_document

OPENAI_COMPAT_GENERATE_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/openai-compat-generate-request/v0alpha1.schema.json"
)
DEFAULT_COMPAT_ENDPOINT = "http://127.0.0.1:8080/v1"
COMPAT_PROVIDER_ID = "openai.compat"
CompatLifecycleType = Literal[
    "ai.call.started",
    "ai.call.completed",
    "ai.call.failed",
    "budget.reserved",
    "budget.consumed",
    "budget.exceeded",
    "budget.released",
]
REQUIRED_COMPAT_EVENTS: frozenset[str] = frozenset(
    {
        TYPE_AI_CALL_STARTED,
        TYPE_AI_CALL_COMPLETED,
        TYPE_AI_CALL_FAILED,
        TYPE_BUDGET_RESERVED,
        TYPE_BUDGET_CONSUMED,
        TYPE_BUDGET_EXCEEDED,
        TYPE_BUDGET_RELEASED,
    }
)
BUDGET_ACTOR = {"id": "researchos.budget", "kind": ActorKind.SYSTEM.value}


class CompatRequestActor(ProviderDocumentModel):
    id: EventIdentifier
    kind: Literal["ai"]
    model_id: EventIdentifier = Field(alias="modelId")


class OpenAICompatGenerateRequestDocument(ProviderDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["OpenAICompatGenerateRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: CompatRequestActor
    call_id: EventIdentifier = Field(alias="callId")
    fixture_id: EventIdentifier = Field(alias="fixtureId")
    provider_id: Literal["openai.compat"] = Field(alias="providerId")
    endpoint: CloudEventsUriReference = DEFAULT_COMPAT_ENDPOINT
    budget_id: EventIdentifier = Field(alias="budgetId")
    budget_cap: MoneyAmount = Field(alias="budgetCap")
    reserve_amount: MoneyAmount = Field(alias="reserveAmount")
    consume_amount: MoneyAmount = Field(alias="consumeAmount")
    granted_kernel_capabilities: tuple[KernelCapability, ...] = Field(
        alias="grantedKernelCapabilities",
        max_length=4,
        json_schema_extra={"uniqueItems": True},
    )
    secret_ref: SecretRef | None = Field(default=None, alias="secretRef")
    requested_capabilities: tuple[ModelCapability, ...] = Field(
        alias="requestedCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    events: Mapping[CompatLifecycleType, ModelEventIdentity] = Field(min_length=7, max_length=7)
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=32,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("requested_capabilities", mode="before")
    @classmethod
    def json_capability_list(cls, value: object) -> object:
        return _capability_tuple(value, "requestedCapabilities")

    @field_validator("granted_kernel_capabilities", mode="before")
    @classmethod
    def json_kernel_capabilities(cls, value: object) -> object:
        items = require_json_array(value, "grantedKernelCapabilities")
        if type(items) is not tuple:
            return items
        return tuple(coerce_kernel_capability(item) for item in items)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def json_evidence_refs(cls, value: object) -> object:
        return require_json_array(value, "evidenceRefs")

    @model_validator(mode="after")
    def local_and_remote_gates_are_closed(self) -> Self:
        if len(self.requested_capabilities) != len(set(self.requested_capabilities)):
            raise ValueError("requestedCapabilities entries must be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        grants = require_known_kernel_capabilities(self.granted_kernel_capabilities)
        object.__setattr__(self, "granted_kernel_capabilities", grants)
        if set(self.events) != REQUIRED_COMPAT_EVENTS:
            raise ValueError(
                "events must include ai.call started/completed/failed "
                "and budget reserved/consumed/exceeded/released"
            )
        event_ids = [identity.id for identity in self.events.values()]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("compat generate event ids must be unique")
        parsed = urlparse(self.endpoint)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("endpoint must not contain userinfo")
        try:
            local = classify_literal_endpoint(self.endpoint) is EndpointKind.LOOPBACK
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        if local:
            if self.secret_ref is not None:
                raise ValueError("loopback endpoints must not carry a secretRef")
            if grants:
                raise ValueError("loopback endpoints must not grant kernel capabilities")
            if self.budget_cap != ZERO_MONEY or self.reserve_amount != ZERO_MONEY:
                raise ValueError("loopback endpoints require a zero CNY cap and reserve")
            if self.consume_amount != ZERO_MONEY:
                raise ValueError("loopback endpoints require a zero CNY consume amount")
        else:
            if parsed.scheme != "https":
                raise ValueError("remote endpoint must use https")
            if self.secret_ref is None:
                raise ValueError("remote endpoints require a SecretRef")
            if KernelCapability.READ_EXTERNAL_API not in grants:
                raise ValueError("remote endpoints require read.external_api")
        cap = parse_money(self.budget_cap)
        reserve = parse_money(self.reserve_amount)
        consume = parse_money(self.consume_amount)
        if not local and (cap <= 0 or reserve <= 0):
            raise ValueError("remote endpoints require a positive CNY cap and reserve")
        if reserve > cap:
            raise ValueError("reserveAmount must not exceed budgetCap")
        if consume > reserve:
            raise ValueError("consumeAmount must not exceed reserveAmount")
        object.__setattr__(self, "events", MappingProxyType(dict(self.events)))
        return self

    @field_serializer("events")
    def serialize_events(
        self,
        events: Mapping[CompatLifecycleType, ModelEventIdentity],
    ) -> dict[CompatLifecycleType, ModelEventIdentity]:
        return dict(events)

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @field_serializer("requested_capabilities")
    def serialize_requested_capabilities(self, values: tuple[ModelCapability, ...]) -> list[str]:
        return [item.value for item in values]

    @field_serializer("granted_kernel_capabilities")
    def serialize_grants(self, values: tuple[KernelCapability, ...]) -> list[str]:
        return [item.value for item in values]

    def generate_request(self) -> GenerateRequest:
        return GenerateRequest(
            fixture_id=self.fixture_id,
            requested=frozenset(self.requested_capabilities),
        )

    def is_loopback(self) -> bool:
        return endpoint_is_loopback(self.endpoint)

    def started_draft(
        self,
        *,
        identity: ModelIdentity,
        prompt_digest: str,
        declared: tuple[str, ...],
        measured: tuple[str, ...],
        allowed: tuple[str, ...],
    ) -> dict[str, Any]:
        event = self.events["ai.call.started"]
        payload = {
            "callId": self.call_id,
            "providerId": identity.provider_id,
            "modelId": identity.model_id,
            "promptDigest": prompt_digest,
            "requestedCapabilities": sorted_capability_names(
                frozenset(self.requested_capabilities)
            ),
            "declaredCapabilities": list(declared),
            "measuredCapabilities": list(measured),
            "allowedCapabilities": list(allowed),
            "local": identity.local,
            "costKnown": identity.cost_known,
            "dataLeavesMachine": identity.data_leaves_machine,
            "contextTokens": identity.context_tokens,
            "maxOutputTokens": identity.max_output_tokens,
        }
        return _event_draft(
            event_id=event.id,
            event_type=TYPE_AI_CALL_STARTED,
            time=event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.model_id),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
        )

    def completed_draft(
        self,
        *,
        output_digest: str,
        declared: tuple[str, ...],
        measured: tuple[str, ...],
        allowed: tuple[str, ...],
        prompt_artifact: str | None,
        output_artifact: str | None,
    ) -> dict[str, Any]:
        event = self.events["ai.call.completed"]
        payload: dict[str, Any] = {
            "callId": self.call_id,
            "outputDigest": output_digest,
            "declaredCapabilities": list(declared),
            "measuredCapabilities": list(measured),
            "allowedCapabilities": list(allowed),
        }
        if prompt_artifact is not None:
            payload["promptArtifact"] = prompt_artifact
        if output_artifact is not None:
            payload["outputArtifact"] = output_artifact
        return _event_draft(
            event_id=event.id,
            event_type=TYPE_AI_CALL_COMPLETED,
            time=event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.model_id),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
        )

    def failed_draft(self, *, reason_code: str) -> dict[str, Any]:
        event = self.events["ai.call.failed"]
        return _event_draft(
            event_id=event.id,
            event_type=TYPE_AI_CALL_FAILED,
            time=event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.model_id),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload={"callId": self.call_id, "reasonCode": reason_code},
            evidence_refs=self.evidence_refs,
        )

    def budget_draft(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = self.events[event_type]  # type: ignore[index]
        return _event_draft(
            event_id=event.id,
            event_type=event_type,
            time=event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=dict(BUDGET_ACTOR),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
        )


def validate_compat_generate_request(document: object) -> OpenAICompatGenerateRequestDocument:
    try:
        return OpenAICompatGenerateRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise ModelRequestError(exc) from None


def load_compat_generate_request(path: str | Path) -> OpenAICompatGenerateRequestDocument:
    return validate_compat_generate_request(load_document(path, reject_symlinks=True))
