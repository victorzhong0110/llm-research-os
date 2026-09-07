"""Typed secret references. The secret value is never part of this document (TM-007)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from llm_research_os.events.models import EventDocumentModel

SECRET_REF_SCHEMA_ID = "https://researchos.dev/schemas/secret-ref/v0alpha1.schema.json"  # noqa: S105
SECRET_REF_API_VERSION = "researchos.dev/v0alpha1"  # noqa: S105

SecretName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        strip_whitespace=False,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class SecretBackend(StrEnum):
    ENV = "env"
    FILE = "file"
    KEYRING = "keyring"


class SecretRef(EventDocumentModel):
    """Handle to a secret slot. Callers must not place the secret value here."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["SecretRef"]
    backend: SecretBackend
    name: SecretName

    @field_validator("backend", mode="before")
    @classmethod
    def coerce_backend(cls, value: object) -> object:
        if type(value) is str:
            try:
                return SecretBackend(value)
            except ValueError:
                return value
        return value
