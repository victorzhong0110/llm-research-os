"""Closed index of the exact bytes for one remote native preparation."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from llm_research_os.artifacts.store import MAX_PUT_BYTES
from llm_research_os.execution.native_reviewed import request_digest
from llm_research_os.execution.native_reviewed_documents import (
    ByteDigest,
    JcsDigest,
    NativeReviewedDocumentModel,
    NativeReviewedExecutionRequest,
    ReviewedIdentifier,
    _require_json_bool,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    MAX_PREPARATION_FILES,
    PreparedFileRecord,
)


class NativeMaterialFile(PreparedFileRecord):
    byte_digest: ByteDigest = Field(alias="byteDigest")
    size_bytes: int = Field(alias="sizeBytes", ge=0, le=MAX_PUT_BYTES)

    @model_validator(mode="after")
    def byte_identity_matches(self) -> Self:
        if self.byte_digest != "sha256:" + self.digest.split(":", 1)[1]:
            raise ValueError("material byte identity differs")
        return self


class NativeMaterialIndex(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeMaterialIndex"]
    request: NativeReviewedExecutionRequest
    request_digest: JcsDigest = Field(alias="requestDigest")
    grant_id: ReviewedIdentifier = Field(alias="grantId")
    files: tuple[NativeMaterialFile, ...] = Field(min_length=1, max_length=MAX_PREPARATION_FILES)
    launch_allowed: Literal[False] = Field(alias="launchAllowed")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def launch_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)

    @field_validator("files", mode="before")
    @classmethod
    def freeze_files(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("material files must be an array")
        return tuple(value)

    @model_validator(mode="after")
    def material_matches_request(self) -> Self:
        if self.request_digest != request_digest(self.request):
            raise ValueError("material request digest differs")
        if len(self.files) != len({item.relative_path for item in self.files}):
            raise ValueError("material paths must be unique")
        expected = {
            "material/bundle": ("bundle", self.request.code.bundle_digest),
            "material/config.json": ("config", self.request.config_digest),
            "material/environment/interpreter": (
                "interpreter",
                self.request.environment.interpreter_digest,
            ),
            "material/environment/dependency-lock": (
                "dependency-lock",
                self.request.environment.dependency_lock_digest,
            ),
            "material/environment/inventory": (
                "inventory",
                self.request.environment.inventory_digest,
            ),
            "material/environment/review": ("review", self.request.code.review.citation_digest),
            **{
                f"material/inputs/{item.name}": ("input", item.digest)
                for item in self.request.inputs
            },
        }
        actual = {
            item.relative_path: (item.role, item.digest)
            for item in self.files
            if item.role != "code"
        }
        if actual != expected or not any(item.role == "code" for item in self.files):
            raise ValueError("material index does not match the request")
        by_path = {item.relative_path: item for item in self.files}
        for item in self.request.inputs:
            if by_path[f"material/inputs/{item.name}"].size_bytes != item.size_bytes:
                raise ValueError("material input size differs")
        return self
