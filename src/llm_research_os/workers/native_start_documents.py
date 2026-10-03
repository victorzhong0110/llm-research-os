"""Bounded remote start-record documents; receipts alone never authorize import."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from llm_research_os.execution.native_reviewed_documents import (
    JcsDigest,
    NativeReviewedDocumentModel,
    _require_json_bool,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NativeReviewedPreparationReceipt,
)

LeaseIdentifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"^[!-~]+$")
]


class NativeStartRequest(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeStartRequest"]
    lease_id: LeaseIdentifier = Field(alias="leaseId")
    preparation: NativeReviewedPreparationReceipt
    identity_digest: JcsDigest = Field(alias="identityDigest")


class NativeStartReceipt(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeStartReceipt"]
    lease_id: LeaseIdentifier = Field(alias="leaseId")
    binding_digest: JcsDigest = Field(alias="bindingDigest")
    event_id: str = Field(alias="eventId", min_length=1, max_length=540)
    sequence: int = Field(ge=1)
    launch_allowed: Literal[False] = Field(alias="launchAllowed")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def strict_launch_flag(cls, value: object) -> object:
        return _require_json_bool(value)
