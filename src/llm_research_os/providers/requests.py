"""Strict request document for one deterministic mock generate recorded as two facts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    RESEARCH_EVENT_SCHEMA_ID,
    ActorKind,
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.providers.capabilities import (
    ModelCapability,
    sorted_capability_names,
)
from llm_research_os.providers.errors import ModelRequestError
from llm_research_os.providers.models import (
    MAX_CAPABILITY_LIST,
    TYPE_AI_CALL_COMPLETED,
    TYPE_AI_CALL_STARTED,
    ModelFixtureDocument,
    ProviderDocumentModel,
    _capability_tuple,
)
from llm_research_os.providers.provider import GenerateRequest, ModelIdentity
from llm_research_os.research.models import require_json_array
from llm_research_os.spec.io import load_document

MODEL_GENERATE_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/model-generate-request/v0alpha1.schema.json"
)
MODEL_GENERATE_REQUEST_API_VERSION = "researchos.dev/v0alpha1"
AiCallLifecycleType = Literal["ai.call.started", "ai.call.completed"]
REQUIRED_AI_CALL_EVENTS: frozenset[str] = frozenset({TYPE_AI_CALL_STARTED, TYPE_AI_CALL_COMPLETED})


class ModelEventIdentity(ProviderDocumentModel):
    id: CloudEventsString
    time: Rfc3339Timestamp


class ModelRequestActor(ProviderDocumentModel):
    id: EventIdentifier
    kind: Literal["ai"]
    model_id: EventIdentifier = Field(alias="modelId")


class ModelGenerateRequestDocument(ProviderDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ModelGenerateRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: ModelRequestActor
    call_id: EventIdentifier = Field(alias="callId")
    fixture_id: EventIdentifier = Field(alias="fixtureId")
    provider_id: EventIdentifier = Field(alias="providerId")
    requested_capabilities: tuple[ModelCapability, ...] = Field(
        alias="requestedCapabilities",
        min_length=1,
        max_length=MAX_CAPABILITY_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    events: Mapping[AiCallLifecycleType, ModelEventIdentity] = Field(min_length=2, max_length=2)
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=32,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("requested_capabilities", mode="before")
    @classmethod
    def json_capability_list(cls, value: object) -> object:
        return _capability_tuple(value, "requestedCapabilities")

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def json_evidence_refs(cls, value: object) -> object:
        return require_json_array(value, "evidenceRefs")

    @model_validator(mode="after")
    def identifiers_and_events_are_closed(self) -> Self:
        if len(self.requested_capabilities) != len(set(self.requested_capabilities)):
            raise ValueError("requestedCapabilities entries must be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        if set(self.events) != REQUIRED_AI_CALL_EVENTS:
            raise ValueError("events must include ai.call.started and ai.call.completed")
        event_ids = [identity.id for identity in self.events.values()]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("model generate event ids must be unique")
        object.__setattr__(self, "events", MappingProxyType(dict(self.events)))
        return self

    @field_serializer("events")
    def serialize_events(
        self,
        events: Mapping[AiCallLifecycleType, ModelEventIdentity],
    ) -> dict[AiCallLifecycleType, ModelEventIdentity]:
        return dict(events)

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @field_serializer("requested_capabilities")
    def serialize_requested_capabilities(self, values: tuple[ModelCapability, ...]) -> list[str]:
        return [item.value for item in values]

    def generate_request(self) -> GenerateRequest:
        return GenerateRequest(
            fixture_id=self.fixture_id,
            requested=frozenset(self.requested_capabilities),
        )

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


def validate_model_generate_request(document: object) -> ModelGenerateRequestDocument:
    try:
        return ModelGenerateRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise ModelRequestError(exc) from None


def validate_model_fixture(document: object) -> ModelFixtureDocument:
    try:
        return ModelFixtureDocument.model_validate(document)
    except ValidationError as exc:
        raise ModelRequestError(exc) from None


def load_model_generate_request(path: str | Path) -> ModelGenerateRequestDocument:
    return validate_model_generate_request(load_document(path, reject_symlinks=True))


def load_model_fixture(path: str | Path) -> ModelFixtureDocument:
    return validate_model_fixture(load_document(path, reject_symlinks=True))


def _actor_document(actor_id: str, model_id: str) -> dict[str, str]:
    return {"id": actor_id, "kind": ActorKind.AI.value, "modelId": model_id}


def _event_draft(
    *,
    event_id: str,
    event_type: str,
    time: str,
    source: str,
    subject: str,
    stream_id: str,
    actor: dict[str, str],
    project_id: str,
    experiment_revision: int,
    payload: dict[str, Any],
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": event_type,
        "time": time,
        "subject": subject,
        "dataschema": RESEARCH_EVENT_SCHEMA_ID,
        "datacontenttype": "application/json",
        "streamid": stream_id,
        "data": {
            "schemaVersion": "v0alpha1",
            "actor": actor,
            "projectId": project_id,
            "experimentRevision": experiment_revision,
            "payload": payload,
            "evidenceRefs": list(evidence_refs),
        },
    }
