"""Strict external request and single-fact Run cancellation boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    RESEARCH_EVENT_SCHEMA_ID,
    CloudEventsString,
    CloudEventsUriReference,
    EventDocumentModel,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.runs.control import RunControl, RunControlResult
from llm_research_os.spec.io import load_document
from llm_research_os.storage.store import EventStore

RUN_CANCELLATION_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/run-cancellation-request/v0alpha1.schema.json"
)
RUN_CANCELLATION_REQUEST_API_VERSION = "researchos.dev/v0alpha1"


class RunCancellationRequestModel(EventDocumentModel):
    """Frozen cancellation documents accept aliases only and never coerce."""

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


class RunCancellationActor(RunCancellationRequestModel):
    """Caller-owned actor identity for the cancellation request fact."""

    id: EventIdentifier


class RunCancellationEventIdentity(RunCancellationRequestModel):
    """Caller-owned CloudEvents identity for the one appended request fact."""

    id: CloudEventsString
    time: Rfc3339Timestamp


class RunCancellationTarget(RunCancellationRequestModel):
    """Request cancellation for the Run aggregate without claiming an outcome."""

    kind: Literal["run"]


class AttemptCancellationTarget(RunCancellationRequestModel):
    """Request cancellation for one active Attempt without claiming it stopped."""

    kind: Literal["attempt"]
    attempt_id: EventIdentifier = Field(alias="attemptId")


CancellationTarget = Annotated[
    RunCancellationTarget | AttemptCancellationTarget,
    Field(discriminator="kind"),
]


class RunCancellationRequestDocument(RunCancellationRequestModel):
    """Versioned external request for exactly one cancellation-request fact."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["RunCancellationRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    run_id: EventIdentifier = Field(alias="runId")
    target: CancellationTarget
    reason_code: EventIdentifier = Field(alias="reasonCode")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: RunCancellationActor
    event: RunCancellationEventIdentity
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def freeze_json_evidence_refs(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("evidenceRefs must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, evidence_refs: tuple[EventIdentifier, ...]) -> list[str]:
        return list(evidence_refs)

    def event_draft(self) -> dict[str, Any]:
        """Build a new ResearchEvent draft without retaining mutable request data."""

        attempt_id: str | None = None
        event_type = "run.cancel.requested"
        if isinstance(self.target, AttemptCancellationTarget):
            attempt_id = self.target.attempt_id
            event_type = "attempt.cancel.requested"
        data: dict[str, Any] = {
            "schemaVersion": "v0alpha1",
            "actor": {"id": self.actor.id},
            "projectId": self.project_id,
            "experimentRevision": self.experiment_revision,
            "runId": self.run_id,
            "payload": {"reasonCode": self.reason_code},
            "evidenceRefs": list(self.evidence_refs),
        }
        if attempt_id is not None:
            data["attemptId"] = attempt_id
        return {
            "specversion": "1.0",
            "id": self.event.id,
            "source": self.source,
            "type": event_type,
            "time": self.event.time,
            "subject": self.subject,
            "dataschema": RESEARCH_EVENT_SCHEMA_ID,
            "datacontenttype": "application/json",
            "streamid": self.stream_id,
            "data": data,
        }


def validate_run_cancellation_request_document(
    document: object,
) -> RunCancellationRequestDocument:
    """Validate an already-decoded external cancellation request."""

    return RunCancellationRequestDocument.model_validate(document)


def load_run_cancellation_request(path: str | Path) -> RunCancellationRequestDocument:
    """Load a local request while rejecting duplicate keys, aliases and symlinks."""

    return validate_run_cancellation_request_document(load_document(path, reject_symlinks=True))


def request_cancellation(
    store: EventStore,
    request: RunCancellationRequestDocument,
) -> RunControlResult:
    """Append exactly one cancellation-request fact through RunControl CAS."""

    control = RunControl(
        store,
        project_id=request.project_id,
        run_id=request.run_id,
    )
    return control.append(request.event_draft())
