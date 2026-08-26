"""Versioned, machine-readable diagnostics for invalid CLI inputs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from llm_research_os.spec.models import NonEmptyText, StrictModel

JsonPointer = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False,
        pattern=r"^(?:/(?:[^~/]|~[01])*)*$",
    ),
]


class FrozenProblemModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class ProblemDetail(FrozenProblemModel):
    path: JsonPointer = ""
    message: NonEmptyText
    type: NonEmptyText


class ProblemReport(FrozenProblemModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ProblemReport"]
    valid: Literal[False]
    errors: tuple[ProblemDetail, ...] = Field(min_length=1)
