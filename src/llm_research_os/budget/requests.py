"""Strict request document for one human-recorded project budget limit."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_serializer, field_validator

from llm_research_os.budget.errors import BudgetRequestError
from llm_research_os.budget.models import TYPE_BUDGET_LIMIT_RECORDED, BudgetDocumentModel
from llm_research_os.budget.money import CURRENCY_CNY, MoneyAmount
from llm_research_os.events.models import (
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.providers.requests import _event_draft
from llm_research_os.research.models import require_json_array
from llm_research_os.spec.io import load_document

BUDGET_LIMIT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/budget-limit-request/v0alpha1.schema.json"
)
BUDGET_LIMIT_REQUEST_API_VERSION = "researchos.dev/v0alpha1"


class BudgetLimitEventIdentity(BudgetDocumentModel):
    id: CloudEventsString
    time: Rfc3339Timestamp


class BudgetLimitRequestActor(BudgetDocumentModel):
    id: EventIdentifier
    kind: Literal["human"]


class BudgetLimitRequestDocument(BudgetDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["BudgetLimitRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: BudgetLimitRequestActor
    event: BudgetLimitEventIdentity
    cap: MoneyAmount
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=32,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "evidenceRefs")

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    def event_draft(self) -> dict[str, Any]:
        return _event_draft(
            event_id=self.event.id,
            event_type=TYPE_BUDGET_LIMIT_RECORDED,
            time=self.event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor={"id": self.actor.id, "kind": self.actor.kind},
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload={"currency": CURRENCY_CNY, "cap": self.cap},
            evidence_refs=self.evidence_refs,
        )


def validate_budget_limit_request(document: object) -> BudgetLimitRequestDocument:
    try:
        return BudgetLimitRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise BudgetRequestError(exc) from None


def load_budget_limit_request(path: str | Path) -> BudgetLimitRequestDocument:
    return validate_budget_limit_request(load_document(path, reject_symlinks=True))


def budget_limit_draft(
    *,
    project_id: str,
    cap: str,
    event_id: str = "evt.budget.limit.1",
    time: str = "2026-09-07T00:00:00Z",
    actor_id: str = "researcher.alice",
    experiment_revision: int = 1,
    source: str = "https://researchos.dev/projects/example-minimal",
) -> dict[str, Any]:
    """Build a human-actor ``budget.limit.recorded`` draft for tests and helpers."""

    return _event_draft(
        event_id=event_id,
        event_type=TYPE_BUDGET_LIMIT_RECORDED,
        time=time,
        source=source,
        subject=f"budget.limit.{project_id}",
        stream_id="stream.budget",
        actor={"id": actor_id, "kind": "human"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"currency": CURRENCY_CNY, "cap": cap},
        evidence_refs=(),
    )
