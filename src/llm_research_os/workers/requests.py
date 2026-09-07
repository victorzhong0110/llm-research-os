"""Strict request documents for Worker registration and HMAC grant recording."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_serializer, field_validator

from llm_research_os.events.models import (
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.research.models import require_json_array
from llm_research_os.spec.io import load_document
from llm_research_os.workers.drafts import grant_recorded_draft, registered_draft
from llm_research_os.workers.errors import WorkerRequestError
from llm_research_os.workers.models import MAX_ACCELERATORS, WorkerDocumentModel

WORKER_REGISTER_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/worker-register-request/v0alpha1.schema.json"
)
AUTHORIZATION_GRANT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/authorization-grant-request/v0alpha1.schema.json"
)
WORKER_REGISTER_REQUEST_API_VERSION = "researchos.dev/v0alpha1"


class WorkerEventIdentity(WorkerDocumentModel):
    id: CloudEventsString
    time: Rfc3339Timestamp


class WorkerRequestActor(WorkerDocumentModel):
    id: EventIdentifier
    kind: Literal["human"]


class WorkerRegisterRequestDocument(WorkerDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["WorkerRegisterRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    worker_id: EventIdentifier = Field(alias="workerId")
    actor: WorkerRequestActor
    event: WorkerEventIdentity
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

    def event_draft(self) -> dict[str, Any]:
        return registered_draft(
            project_id=self.project_id,
            worker_id=self.worker_id,
            event_id=self.event.id,
            time=self.event.time,
            source=self.source,
            actor_id=self.actor.id,
            accelerators=self.accelerators,
            experiment_revision=self.experiment_revision,
        )


class AuthorizationGrantRequestDocument(WorkerDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["AuthorizationGrantRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    grant_id: EventIdentifier = Field(alias="grantId")
    worker_id: EventIdentifier = Field(alias="workerId")
    task_id: EventIdentifier = Field(alias="taskId")
    run_id: EventIdentifier = Field(alias="runId")
    attempt_id: EventIdentifier = Field(alias="attemptId")
    nonce: EventIdentifier
    expires_at: Rfc3339Timestamp = Field(alias="expiresAt")
    actor: WorkerRequestActor
    event: WorkerEventIdentity

    def event_draft(self) -> dict[str, Any]:
        return grant_recorded_draft(
            project_id=self.project_id,
            grant_id=self.grant_id,
            worker_id=self.worker_id,
            task_id=self.task_id,
            run_id=self.run_id,
            attempt_id=self.attempt_id,
            nonce=self.nonce,
            expires_at=self.expires_at,
            event_id=self.event.id,
            time=self.event.time,
            source=self.source,
            actor_id=self.actor.id,
            experiment_revision=self.experiment_revision,
        )


def validate_worker_register_request(document: object) -> WorkerRegisterRequestDocument:
    try:
        return WorkerRegisterRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise WorkerRequestError(exc) from None


def load_worker_register_request(path: str | Path) -> WorkerRegisterRequestDocument:
    return validate_worker_register_request(load_document(path, reject_symlinks=True))


def validate_authorization_grant_request(document: object) -> AuthorizationGrantRequestDocument:
    try:
        return AuthorizationGrantRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise WorkerRequestError(exc) from None


def load_authorization_grant_request(path: str | Path) -> AuthorizationGrantRequestDocument:
    return validate_authorization_grant_request(load_document(path, reject_symlinks=True))
