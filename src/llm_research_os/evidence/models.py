"""Closed v0alpha1 payloads for ``evidence.imported`` and citation documents."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import LEGACY_SHA256_PREFIX
from llm_research_os.events.models import (
    ActorKind,
    CloudEventsUriReference,
    EventDocumentModel,
    EventIdentifier,
    ResearchEvent,
)
from llm_research_os.evidence.errors import EvidencePayloadError
from llm_research_os.research.models import JcsDigest, require_json_array
from llm_research_os.spec.models import DataUse, EvidenceSourceType, RightsStatus

TYPE_EVIDENCE_IMPORTED = "evidence.imported"
EVIDENCE_EVENT_TYPES = frozenset({TYPE_EVIDENCE_IMPORTED})
DEFAULT_LICENSE = "LicenseRef-Unknown"
MAX_ALLOWED_USES = 4
ARTIFACT_DIGEST_LENGTH = len(LEGACY_SHA256_PREFIX) + 64
EVIDENCE_CITATION_SCHEMA_ID = (
    "https://researchos.dev/schemas/evidence-citation/v0alpha1.schema.json"
)
LicenseExpression = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        strip_whitespace=False,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$",
    ),
]
ArtifactDigest = Annotated[
    str,
    StringConstraints(
        min_length=ARTIFACT_DIGEST_LENGTH,
        max_length=ARTIFACT_DIGEST_LENGTH,
        strip_whitespace=False,
        pattern=rf"^{LEGACY_SHA256_PREFIX}[0-9a-f]{{64}}$",
    ),
]


def _coerce_strenum(enum_type: type[StrEnum], value: object) -> object:
    if type(value) is str:
        try:
            return enum_type(value)
        except ValueError:
            return value
    return value


class EvidenceDocumentModel(EventDocumentModel):
    """Frozen evidence documents: aliases only, strict, no trimming."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


class EvidenceImportedPayload(EvidenceDocumentModel):
    evidence_id: EventIdentifier = Field(alias="evidenceId")
    source_uri: CloudEventsUriReference = Field(alias="sourceUri")
    media_type: Literal["text/markdown", "application/pdf"] = Field(alias="mediaType")
    source_type: EvidenceSourceType = Field(alias="sourceType")
    snapshot_digest: ArtifactDigest = Field(alias="snapshotDigest")
    text_digest: JcsDigest = Field(alias="textDigest")
    text_artifact: ArtifactDigest = Field(alias="textArtifact")
    license: LicenseExpression
    rights: RightsStatus
    allowed_uses: tuple[DataUse, ...] = Field(
        alias="allowedUses",
        min_length=1,
        max_length=MAX_ALLOWED_USES,
        json_schema_extra={"uniqueItems": True},
    )
    byte_length: int = Field(alias="byteLength", ge=1, le=8_388_608)
    text_characters: int = Field(alias="textCharacters", ge=1, le=400_000)

    @field_validator("rights", mode="before")
    @classmethod
    def coerce_rights(cls, value: object) -> object:
        return _coerce_strenum(RightsStatus, value)

    @field_validator("source_type", mode="before")
    @classmethod
    def coerce_source_type(cls, value: object) -> object:
        return _coerce_strenum(EvidenceSourceType, value)

    @field_validator("allowed_uses", mode="before")
    @classmethod
    def json_allowed_uses(cls, value: object) -> object:
        items = require_json_array(value, "allowedUses")
        if type(items) is not tuple:
            return items
        return tuple(_coerce_strenum(DataUse, item) for item in items)

    @model_validator(mode="after")
    def unknown_rights_cannot_train(self) -> Self:
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ValueError("allowedUses entries must be unique")
        prohibited = {DataUse.TRAINING, DataUse.REDISTRIBUTION}
        if self.rights is RightsStatus.UNKNOWN and prohibited.intersection(self.allowed_uses):
            raise ValueError("unknown rights cannot authorize training or redistribution")
        return self


class EvidenceSpan(EvidenceDocumentModel):
    start: int = Field(ge=0, le=400_000)
    end: int = Field(ge=1, le=400_000)

    @model_validator(mode="after")
    def start_precedes_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("span start must be less than end")
        return self


class EvidenceCitation(EvidenceDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["EvidenceCitation"]
    evidence_id: EventIdentifier = Field(alias="evidenceId")
    snapshot_digest: ArtifactDigest = Field(alias="snapshotDigest")
    span: EvidenceSpan


PAYLOAD_MODELS: dict[str, type[EvidenceDocumentModel]] = {
    TYPE_EVIDENCE_IMPORTED: EvidenceImportedPayload,
}

if set(PAYLOAD_MODELS) != EVIDENCE_EVENT_TYPES:
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the evidence event catalog")


def parse_evidence_payload(event: ResearchEvent) -> EvidenceDocumentModel:
    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        raise EvidencePayloadError(
            f"event type is not an evidence type (event id {event.id})",
            code="unknown-evidence-type",
        )
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = EvidencePayloadError(
            f"invalid payload for evidence type {event.type} "
            f"(event id {event.id}, sequence {event.sequence})",
            code="invalid-payload",
        )
    else:
        return validated
    raise payload_error


def require_evidence_actor(event: ResearchEvent) -> None:
    kind = event.data.actor.kind
    if kind is None:
        raise EvidencePayloadError(
            f"actor kind is required for {event.type} (event id {event.id})",
            code="actor-kind-required",
        )
    if kind not in {ActorKind.HUMAN, ActorKind.SYSTEM}:
        raise EvidencePayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
