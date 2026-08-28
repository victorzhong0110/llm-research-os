"""Pydantic authoring models for ResearchEvent v0alpha1.

The generated JSON Schema is the external, language-neutral contract. The envelope
follows CloudEvents 1.0 structured JSON mapping; versioned domain fields live in
``data``. Callers must supply identity, time and sequence explicitly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from llm_research_os.spec.models import (
    Identifier,
    JsonObject,
    NonEmptyText,
    StrictModel,
)

RESEARCH_EVENT_SCHEMA_ID = "https://researchos.dev/schemas/research-event/v0alpha1.schema.json"
INLINE_BODY_KEYS = frozenset(
    {
        "body",
        "bytes",
        "content",
        "fileBytes",
        "inlineContent",
        "rawBody",
    }
)
NonNegativeInt = Annotated[int, Field(ge=0)]
CloudEventsUriReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2048,
        pattern=r"^[^\s\\]+$",
    ),
]


def _reject_embedded_bodies(value: dict[str, Any]) -> dict[str, Any]:
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            blocked = sorted(key for key in current if key in INLINE_BODY_KEYS)
            if blocked:
                raise ValueError(
                    "payload must not embed file bytes or document bodies; "
                    f"forbidden keys: {blocked}"
                )
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return value


EventPayload = Annotated[JsonObject, AfterValidator(_reject_embedded_bodies)]


class EventActor(StrictModel):
    """Closed actor identity. Additional actor facets are not part of v0alpha1."""

    id: Identifier


class ResearchEventData(StrictModel):
    """Versioned ResearchEvent domain payload carried in CloudEvents ``data``."""

    schema_version: Literal["v0alpha1"] = Field(alias="schemaVersion")
    actor: EventActor
    project_id: Identifier = Field(alias="projectId")
    experiment_revision: PositiveInt = Field(alias="experimentRevision")
    run_id: Identifier | None = Field(default=None, alias="runId")
    attempt_id: Identifier | None = Field(default=None, alias="attemptId")
    block_id: Identifier | None = Field(default=None, alias="blockId")
    payload: EventPayload
    evidence_refs: list[Identifier] = Field(alias="evidenceRefs")

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self


class ResearchEvent(StrictModel):
    """CloudEvents 1.0 compatible structured JSON envelope for ResearchEvent."""

    specversion: Literal["1.0"]
    id: NonEmptyText
    source: CloudEventsUriReference
    type: Identifier
    time: AwareDatetime
    subject: NonEmptyText
    dataschema: Literal["https://researchos.dev/schemas/research-event/v0alpha1.schema.json"]
    datacontenttype: Literal["application/json"]
    data: ResearchEventData
    sequence: NonNegativeInt
    streamid: Identifier
    streamversion: NonNegativeInt
    correlationid: NonEmptyText | None = None
    causationid: NonEmptyText | None = None
