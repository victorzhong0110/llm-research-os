"""Versioned machine-readable reports for local artifact object commands."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, NonNegativeInt, StringConstraints, model_validator

from llm_research_os.artifacts.models import ArtifactRecord
from llm_research_os.artifacts.store import storage_key_for
from llm_research_os.spec.models import StrictModel

ArtifactDigest = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]
ArtifactStorageKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=r"^objects/sha256/[0-9a-f]{2}/[0-9a-f]{62}$",
    ),
]


class ArtifactObjectReport(StrictModel):
    """One successfully imported or independently verified artifact object."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        strict=True,
        str_strip_whitespace=False,
        validate_by_alias=True,
        validate_by_name=False,
    )

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ArtifactObjectReport"]
    operation: Literal["put", "verify"]
    digest: ArtifactDigest
    size_bytes: NonNegativeInt = Field(alias="sizeBytes")
    storage_key: ArtifactStorageKey = Field(alias="storageKey")

    @model_validator(mode="after")
    def storage_key_matches_digest(self) -> Self:
        if self.storage_key != storage_key_for(self.digest):
            raise ValueError("storageKey does not match digest")
        return self

    @classmethod
    def from_record(
        cls,
        record: ArtifactRecord,
        *,
        operation: Literal["put", "verify"],
    ) -> ArtifactObjectReport:
        """Build the external report without including caller filesystem paths."""

        return cls(
            apiVersion="researchos.dev/v0alpha1",
            kind="ArtifactObjectReport",
            operation=operation,
            digest=record.digest,
            sizeBytes=record.size_bytes,
            storageKey=record.storage_key,
        )
