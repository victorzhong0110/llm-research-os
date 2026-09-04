"""Strict request documents for one proposal, dissent, or decision fact."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    RESEARCH_EVENT_SCHEMA_ID,
    ActorKind,
    CloudEventsString,
    CloudEventsUriReference,
    EventIdentifier,
    ExperimentRevision,
    Rfc3339Timestamp,
)
from llm_research_os.research.errors import ResearchRequestError
from llm_research_os.research.models import (
    MAX_DECISION_LIST,
    TYPE_DECISION_RECORDED,
    TYPE_DISSENT_RECORDED,
    TYPE_PROPOSAL_SUBMITTED,
    DecisionItemText,
    DecisionOutcome,
    DecisionTargetKind,
    DecisionText,
    DissentObjection,
    DissentTargetKind,
    JcsDigest,
    ProposalPrediction,
    ResearchDocumentModel,
    RiskAssessment,
    require_json_array,
)
from llm_research_os.spec.io import load_document

PROPOSAL_SUBMIT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/proposal-submit-request/v0alpha1.schema.json"
)
DISSENT_RECORD_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/dissent-record-request/v0alpha1.schema.json"
)
DECISION_RECORD_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/decision-record-request/v0alpha1.schema.json"
)
RESEARCH_REQUEST_API_VERSION = "researchos.dev/v0alpha1"


class ResearchEventIdentity(ResearchDocumentModel):
    id: CloudEventsString
    time: Rfc3339Timestamp


class ProposalRequestActor(ResearchDocumentModel):
    id: EventIdentifier
    kind: Literal["human", "ai"]
    model_id: EventIdentifier | None = Field(default=None, alias="modelId")

    @model_validator(mode="after")
    def model_id_requires_ai_kind(self) -> Self:
        if self.model_id is not None and self.kind != ActorKind.AI.value:
            raise ValueError("modelId is only valid when actor kind is ai")
        return self


class DecisionRequestActor(ResearchDocumentModel):
    id: EventIdentifier
    kind: Literal["human", "policy"]


class ProposalSubmitRequestDocument(ResearchDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ProposalSubmitRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: ProposalRequestActor
    event: ResearchEventIdentity
    proposal_id: EventIdentifier = Field(alias="proposalId")
    spec_diff_digest: JcsDigest = Field(alias="specDiffDigest")
    proposed_spec_digest: JcsDigest = Field(alias="proposedSpecDigest")
    rationale: DecisionText
    predictions: tuple[ProposalPrediction, ...] = Field(min_length=1, max_length=MAX_DECISION_LIST)
    falsification_conditions: tuple[DecisionItemText, ...] = Field(
        alias="falsificationConditions",
        min_length=1,
        max_length=MAX_DECISION_LIST,
    )
    risk_assessment: RiskAssessment = Field(alias="riskAssessment")
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=MAX_DECISION_LIST,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("predictions", "falsification_conditions", "evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "list")

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        prediction_ids = tuple(item.id for item in self.predictions)
        if len(prediction_ids) != len(set(prediction_ids)):
            raise ValueError("prediction ids must be unique")
        if len(self.falsification_conditions) != len(set(self.falsification_conditions)):
            raise ValueError("falsificationConditions entries must be unique")
        return self

    @field_serializer("evidence_refs", "falsification_conditions")
    def serialize_string_tuples(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    def event_draft(self) -> dict[str, Any]:
        payload = {
            "proposalId": self.proposal_id,
            "baseRevision": self.experiment_revision,
            "specDiffDigest": self.spec_diff_digest,
            "proposedSpecDigest": self.proposed_spec_digest,
            "rationale": self.rationale,
            "predictions": [
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in self.predictions
            ],
            "falsificationConditions": list(self.falsification_conditions),
            "riskAssessment": self.risk_assessment.model_dump(mode="json", by_alias=True),
            "evidenceRefs": list(self.evidence_refs),
        }
        return _event_draft(
            event_id=self.event.id,
            event_type=TYPE_PROPOSAL_SUBMITTED,
            time=self.event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.kind, self.actor.model_id),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
        )


class DissentRecordRequestDocument(ResearchDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["DissentRecordRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: ProposalRequestActor
    event: ResearchEventIdentity
    dissent_id: EventIdentifier = Field(alias="dissentId")
    target_kind: DissentTargetKind = Field(alias="targetKind")
    target_id: EventIdentifier = Field(alias="targetId")
    objections: tuple[DissentObjection, ...] = Field(min_length=1, max_length=MAX_DECISION_LIST)
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=MAX_DECISION_LIST,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("target_kind", mode="before")
    @classmethod
    def coerce_target_kind(cls, value: object) -> object:
        if type(value) is str:
            try:
                return DissentTargetKind(value)
            except ValueError:
                return value
        return value

    @field_validator("objections", "evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "list")

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, evidence_refs: tuple[EventIdentifier, ...]) -> list[str]:
        return list(evidence_refs)

    def event_draft(self) -> dict[str, Any]:
        payload = {
            "dissentId": self.dissent_id,
            "targetKind": self.target_kind.value,
            "targetId": self.target_id,
            "objections": [item.model_dump(mode="json", by_alias=True) for item in self.objections],
            "evidenceRefs": list(self.evidence_refs),
        }
        return _event_draft(
            event_id=self.event.id,
            event_type=TYPE_DISSENT_RECORDED,
            time=self.event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.kind, self.actor.model_id),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
        )


class DecisionRecordRequestDocument(ResearchDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["DecisionRecordRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: DecisionRequestActor
    event: ResearchEventIdentity
    decision_id: EventIdentifier = Field(alias="decisionId")
    target_kind: DecisionTargetKind = Field(alias="targetKind")
    target_id: EventIdentifier = Field(alias="targetId")
    outcome: DecisionOutcome
    rationale: DecisionText
    overridden_dissent_ids: tuple[EventIdentifier, ...] = Field(
        alias="overriddenDissentIds",
        max_length=MAX_DECISION_LIST,
        json_schema_extra={"uniqueItems": True},
    )
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=MAX_DECISION_LIST,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("target_kind", mode="before")
    @classmethod
    def coerce_target_kind(cls, value: object) -> object:
        if type(value) is str:
            try:
                return DecisionTargetKind(value)
            except ValueError:
                return value
        return value

    @field_validator("outcome", mode="before")
    @classmethod
    def coerce_outcome(cls, value: object) -> object:
        if type(value) is str:
            try:
                return DecisionOutcome(value)
            except ValueError:
                return value
        return value

    @field_validator("overridden_dissent_ids", "evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return require_json_array(value, "list")

    @model_validator(mode="after")
    def identifier_lists_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        if len(self.overridden_dissent_ids) != len(set(self.overridden_dissent_ids)):
            raise ValueError("overriddenDissentIds entries must be unique")
        return self

    @field_serializer("overridden_dissent_ids", "evidence_refs")
    def serialize_id_tuples(self, values: tuple[EventIdentifier, ...]) -> list[str]:
        return list(values)

    def event_draft(self) -> dict[str, Any]:
        payload = {
            "decisionId": self.decision_id,
            "targetKind": self.target_kind.value,
            "targetId": self.target_id,
            "outcome": self.outcome.value,
            "rationale": self.rationale,
            "overriddenDissentIds": list(self.overridden_dissent_ids),
            "evidenceRefs": list(self.evidence_refs),
        }
        run_id = self.target_id if self.target_kind is DecisionTargetKind.RUN else None
        return _event_draft(
            event_id=self.event.id,
            event_type=TYPE_DECISION_RECORDED,
            time=self.event.time,
            source=self.source,
            subject=self.subject,
            stream_id=self.stream_id,
            actor=_actor_document(self.actor.id, self.actor.kind, None),
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            payload=payload,
            evidence_refs=self.evidence_refs,
            run_id=run_id,
        )


def validate_proposal_submit_request(document: object) -> ProposalSubmitRequestDocument:
    try:
        return ProposalSubmitRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise ResearchRequestError(exc) from None


def validate_dissent_record_request(document: object) -> DissentRecordRequestDocument:
    try:
        return DissentRecordRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise ResearchRequestError(exc) from None


def validate_decision_record_request(document: object) -> DecisionRecordRequestDocument:
    try:
        return DecisionRecordRequestDocument.model_validate(document)
    except ValidationError as exc:
        raise ResearchRequestError(exc) from None


def load_proposal_submit_request(path: str | Path) -> ProposalSubmitRequestDocument:
    return validate_proposal_submit_request(load_document(path, reject_symlinks=True))


def load_dissent_record_request(path: str | Path) -> DissentRecordRequestDocument:
    return validate_dissent_record_request(load_document(path, reject_symlinks=True))


def load_decision_record_request(path: str | Path) -> DecisionRecordRequestDocument:
    return validate_decision_record_request(load_document(path, reject_symlinks=True))


def _actor_document(actor_id: str, kind: str, model_id: str | None) -> dict[str, str]:
    actor = {"id": actor_id, "kind": kind}
    if model_id is not None:
        actor["modelId"] = model_id
    return actor


def _event_draft(
    *,
    event_id: str,
    event_type: str,
    time: str,
    source: str,
    subject: str,
    stream_id: str,
    actor: dict[str, str],
    project_id: str,
    experiment_revision: int,
    payload: dict[str, Any],
    evidence_refs: tuple[str, ...],
    run_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": actor,
        "projectId": project_id,
        "experimentRevision": experiment_revision,
        "payload": payload,
        "evidenceRefs": list(evidence_refs),
    }
    if run_id is not None:
        data["runId"] = run_id
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": event_type,
        "time": time,
        "subject": subject,
        "dataschema": RESEARCH_EVENT_SCHEMA_ID,
        "datacontenttype": "application/json",
        "streamid": stream_id,
        "data": data,
    }
