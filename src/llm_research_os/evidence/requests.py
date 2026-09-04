"""Strict request document for one local Markdown or PDF import."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    RESEARCH_EVENT_SCHEMA_ID,
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.evidence.errors import EvidenceRequestError
from llm_research_os.evidence.models import (
    DEFAULT_LICENSE,
    MAX_ALLOWED_USES,
    TYPE_EVIDENCE_IMPORTED,
    EvidenceCitation,
    EvidenceDocumentModel,
    LicenseExpression,
    _coerce_strenum,
)
from llm_research_os.research.models import require_json_array
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import DataUse, EvidenceSourceType, RightsStatus

EVIDENCE_IMPORT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/evidence-import-request/v0alpha1.schema.json"
)


class EvidenceEventIdentity(EvidenceDocumentModel):
    id: CloudEventsString
    time: Rfc3339Timestamp


class EvidenceRequestActor(EvidenceDocumentModel):
    id: EventIdentifier
    kind: Literal["human", "system"]


class EvidenceImportRequestDocument(EvidenceDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["EvidenceImportRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: EvidenceRequestActor
    event: EvidenceEventIdentity
    evidence_id: EventIdentifier = Field(alias="evidenceId")
    source_uri: CloudEventsUriReference = Field(alias="sourceUri")
    media_type: Literal["text/markdown", "application/pdf"] = Field(alias="mediaType")
    source_type: EvidenceSourceType = Field(alias="sourceType")
    license: LicenseExpression = DEFAULT_LICENSE
    rights: RightsStatus = RightsStatus.UNKNOWN
    allowed_uses: tuple[DataUse, ...] = Field(
        default=(DataUse.RESEARCH_READ,),
        alias="allowedUses",
        min_length=1,
        max_length=MAX_ALLOWED_USES,
        json_schema_extra={"uniqueItems": True},
    )
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=32,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("source_type", mode="before")
    @classmethod
    def coerce_source_type(cls, value: object) -> object:
        return _coerce_strenum(EvidenceSourceType, value)

    @field_validator("rights", mode="before")
    @classmethod
    def coerce_rights(cls, value: object) -> object:
        return _coerce_strenum(RightsStatus, value)

    @field_validator("allowed_uses", mode="before")
    @classmethod
    def json_allowed_uses(cls, value: object) -> object:
        items = require_json_array(value, "allowedUses")
        if type(items) is not tuple:
            return items
        return tuple(_coerce_strenum(DataUse, item) for item in items)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def json_evidence_refs(cls, value: object) -> object:
        return require_json_array(value, "evidenceRefs")

    @model_validator(mode="after")
    def identifiers_and_rights_are_closed(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ValueError("allowedUses entries must be unique")
        prohibited = {DataUse.TRAINING, DataUse.REDISTRIBUTION}
        if self.rights is RightsStatus.UNKNOWN and prohibited.intersection(self.allowed_uses):
            raise ValueError("unknown rights cannot authorize training or redistribution")
        return self

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @field_serializer("allowed_uses")
    def serialize_allowed_uses(self, values: tuple[DataUse, ...]) -> list[str]:
        return [item.value for item in values]

    def event_draft(
        self,
        *,
        snapshot_digest: str,
        text_digest: str,
        text_artifact: str,
        byte_length: int,
        text_characters: int,
    ) -> dict[str, Any]:
        payload = {
            "evidenceId": self.evidence_id,
            "sourceUri": self.source_uri,
            "mediaType": self.media_type,
            "sourceType": self.source_type.value,
            "snapshotDigest": snapshot_digest,
            "textDigest": text_digest,
            "textArtifact": text_artifact,
            "license": self.license,
            "rights": self.rights.value,
            "allowedUses": [item.value for item in self.allowed_uses],
            "byteLength": byte_length,
            "textCharacters": text_characters,
        }
        return {
            "specversion": "1.0",
            "id": self.event.id,
            "source": self.source,
            "type": TYPE_EVIDENCE_IMPORTED,
            "time": self.event.time,
            "subject": self.subject,
            "dataschema": RESEARCH_EVENT_SCHEMA_ID,
            "datacontenttype": "application/json",
            "streamid": self.stream_id,
            "data": {
                "schemaVersion": "v0alpha1",
                "actor": {"id": self.actor.id, "kind": self.actor.kind},
                "projectId": self.project_id,
                "experimentRevision": self.experiment_revision,
                "payload": payload,
                "evidenceRefs": list(self.evidence_refs),
            },
        }


def validate_evidence_import_request(document: object) -> EvidenceImportRequestDocument:
    try:
        return EvidenceImportRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise EvidenceRequestError(exc) from None


def load_evidence_import_request(path: str | Path) -> EvidenceImportRequestDocument:
    return validate_evidence_import_request(load_document(path, reject_symlinks=True))


def validate_evidence_citation(document: object) -> EvidenceCitation:
    try:
        return EvidenceCitation.model_validate(document)
    except ValidationError as exc:
        raise EvidenceRequestError(exc) from None
