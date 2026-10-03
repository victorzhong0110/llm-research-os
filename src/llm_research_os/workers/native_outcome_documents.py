"""Authenticated Worker observations for the already-bound remote native Attempt."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from llm_research_os.execution.native_reviewed_documents import (
    JcsDigest,
    NativeReviewedDocumentModel,
    _require_json_bool,
)
from llm_research_os.workers.native_start_documents import LeaseIdentifier, NativeStartRequest


class NativeOutcomeRequest(NativeReviewedDocumentModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"outcome": {"enum": ["completed", "failed", "cancelled"]}},
                        "required": ["outcome"],
                    },
                    "then": {"properties": {"observation": {"const": "exited"}}},
                }
            ]
        }
    )
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeOutcomeRequest"]
    start: NativeStartRequest
    observation: Literal["running", "exited", "unknown"]
    outcome: Literal["completed", "failed", "cancelled", "unknown"]

    @model_validator(mode="after")
    def terminal_requires_observed_exit(self) -> Self:
        if self.outcome != "unknown" and self.observation != "exited":
            raise ValueError("terminal outcome requires observed exit")
        return self


class NativeOutcomeReceipt(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeOutcomeReceipt"]
    lease_id: LeaseIdentifier = Field(alias="leaseId")
    binding_digest: JcsDigest = Field(alias="bindingDigest")
    disposition: Literal["completed", "failed", "cancelled", "unknown", "running"]
    event_id: str = Field(alias="eventId", min_length=1, max_length=540)
    sequence: int = Field(ge=1)
    launch_allowed: Literal[False] = Field(alias="launchAllowed")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def strict_launch_flag(cls, value: object) -> object:
        return _require_json_bool(value)
