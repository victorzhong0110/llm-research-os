"""Strict external request contract for deterministic simulated runs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Self

from pydantic import ConfigDict, Field, field_serializer, model_validator

from llm_research_os.events.models import (
    CloudEventsString,
    CloudEventsUriReference,
    EventDocumentModel,
    EventIdentifier,
    Rfc3339Timestamp,
    SequenceIntegerString,
)
from llm_research_os.spec.io import load_document

if TYPE_CHECKING:
    from llm_research_os.execution.simulated import SimulationRequest

SIMULATION_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/simulation-request/v0alpha1.schema.json"
)
SIMULATION_REQUEST_API_VERSION = "researchos.dev/v0alpha1"

SimulationLifecycleType = Literal[
    "run.queued",
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "attempt.queued",
    "attempt.started",
    "attempt.succeeded",
    "attempt.failed",
    "attempt.unknown",
    "attempt.cancelled",
    "training.step",
    "evaluation.metric",
]


class SimulationRequestModel(EventDocumentModel):
    """Frozen request documents accept aliases only and never coerce or trim."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=False,
        str_strip_whitespace=False,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
    )


class SimulationActor(SimulationRequestModel):
    """Caller-owned actor identity used on emitted lifecycle events."""

    id: EventIdentifier


class SimulationEventIdentityDocument(SimulationRequestModel):
    """Caller-owned CloudEvents identity for one lifecycle fact."""

    id: CloudEventsString
    time: Rfc3339Timestamp


class SimulationAuthorizationCitation(SimulationRequestModel):
    """Local EventStore citation of one ``plan.authorization.evaluated`` fact."""

    event_id: CloudEventsString = Field(alias="eventId")
    sequence: SequenceIntegerString


class SimulationRequestDocument(SimulationRequestModel):
    """Versioned external request for one deterministic simulated Run."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["SimulationRequest"]
    run_id: EventIdentifier = Field(alias="runId")
    workflow_id: EventIdentifier = Field(alias="workflowId")
    attempt_id: EventIdentifier = Field(alias="attemptId")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: SimulationActor
    authorization: SimulationAuthorizationCitation
    events: Mapping[SimulationLifecycleType, SimulationEventIdentityDocument] = Field(max_length=13)

    @model_validator(mode="after")
    def event_ids_are_unique(self) -> Self:
        identities = self.events.values()
        event_ids = [identity.id for identity in identities]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("simulation event ids must be unique")
        object.__setattr__(self, "events", MappingProxyType(dict(self.events)))
        return self

    @field_serializer("events")
    def serialize_events(
        self,
        events: Mapping[SimulationLifecycleType, SimulationEventIdentityDocument],
    ) -> dict[SimulationLifecycleType, SimulationEventIdentityDocument]:
        return dict(events)

    def runtime_request(self) -> SimulationRequest:
        """Return the existing in-process request without retaining mutable input."""

        from llm_research_os.execution.simulated import (
            SimulationEventIdentity,
            SimulationRequest,
        )

        return SimulationRequest(
            workflow_id=self.workflow_id,
            attempt_id=self.attempt_id,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor_id=self.actor.id,
            authorization_event_id=self.authorization.event_id,
            authorization_sequence=self.authorization.sequence,
            events={
                event_type: SimulationEventIdentity(id=identity.id, time=identity.time)
                for event_type, identity in self.events.items()
            },
        )


def validate_simulation_request_document(document: object) -> SimulationRequestDocument:
    """Validate an already-decoded external simulation request."""

    return SimulationRequestDocument.model_validate(document)


def load_simulation_request(path: str | Path) -> SimulationRequestDocument:
    """Load a local request while rejecting duplicate keys, aliases and symlinks."""

    return validate_simulation_request_document(load_document(path, reject_symlinks=True))
