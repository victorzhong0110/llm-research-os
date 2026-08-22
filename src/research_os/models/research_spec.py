"""``ResearchSpec v0alpha1`` — the versioned, comparable, reviewable description
of *why*, *what*, *how*, and *how to judge* a piece of research.

This is the M0 minimal subset of the charter's spec. Fields that the charter
lists as open containers (evidence, datasets, models, workflows, evaluations,
resources, policies) are accepted as free-form structures for now so the schema
can evolve without breaking the append-only event stream.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_os import API_VERSION

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class SpecMetadata(BaseModel):
    """Identity and revision of a research project document."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable, slug-like project identifier.")
    revision: int = Field(ge=1, description="Monotonic revision; drafts bump this.")
    title: str = Field(min_length=1, description="Human-readable project title.")

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError(
                "id must be a lowercase slug of 3-64 chars using [a-z0-9-] "
                "and not start or end with '-'"
            )
        return value


class Hypothesis(BaseModel):
    """A falsifiable claim that evidence can support or refute."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Hypothesis identifier, unique within the spec.")
    statement: str = Field(min_length=1, description="The claim under test.")
    prediction: str | None = Field(
        default=None, description="Pre-registered expected outcome, if any."
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("hypothesis id must be a lowercase slug of 3-64 chars using [a-z0-9-]")
        return value


class ResearchSpec(BaseModel):
    """Versioned research project definition (``kind: ResearchProject``)."""

    model_config = ConfigDict(extra="forbid")

    apiVersion: str = Field(default=API_VERSION)
    kind: str = Field(default="ResearchProject")
    metadata: SpecMetadata
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    models: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)

    @field_validator("apiVersion")
    @classmethod
    def _validate_api_version(cls, value: str) -> str:
        if value != API_VERSION:
            raise ValueError(f"apiVersion must be {API_VERSION!r}, got {value!r}")
        return value

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        if value != "ResearchProject":
            raise ValueError(f"kind must be 'ResearchProject', got {value!r}")
        return value

    @field_validator("hypotheses")
    @classmethod
    def _unique_hypothesis_ids(cls, value: list[Hypothesis]) -> list[Hypothesis]:
        ids = [h.id for h in value]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate hypothesis ids: {sorted(duplicates)}")
        return value
