"""Closed v0alpha1 payloads and the rebuildable ResearchLedger snapshot."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import JCS_SHA256_PREFIX
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ActorKind,
    CloudEventsString,
    EventDocumentModel,
    EventIdentifier,
    ResearchEvent,
)
from llm_research_os.research.errors import ResearchPayloadError

RESEARCH_LEDGER_SCHEMA_ID = "https://researchos.dev/schemas/research-ledger/v0alpha1.schema.json"
RESEARCH_LEDGER_API_VERSION = "researchos.dev/v0alpha1"
MAX_DECISION_LIST = 32
MAX_DECISION_TEXT = 4000
MAX_DECISION_ITEM_TEXT = 1000
JCS_DIGEST_LENGTH = len(JCS_SHA256_PREFIX) + 64

TYPE_PROPOSAL_SUBMITTED = "proposal.submitted"
TYPE_DISSENT_RECORDED = "dissent.recorded"
TYPE_DECISION_RECORDED = "decision.recorded"
DECISION_EVENT_TYPES = frozenset(
    {TYPE_PROPOSAL_SUBMITTED, TYPE_DISSENT_RECORDED, TYPE_DECISION_RECORDED}
)
ALLOWED_ACTOR_KINDS: dict[str, frozenset[ActorKind]] = {
    TYPE_PROPOSAL_SUBMITTED: frozenset({ActorKind.AI, ActorKind.HUMAN}),
    TYPE_DISSENT_RECORDED: frozenset({ActorKind.AI, ActorKind.HUMAN}),
    TYPE_DECISION_RECORDED: frozenset({ActorKind.HUMAN, ActorKind.POLICY}),
}


def _coerce_strenum(enum_type: type[StrEnum], value: object) -> object:
    if type(value) is str:
        try:
            return enum_type(value)
        except ValueError:
            return value
    return value


def require_json_array(value: object, field: str) -> object:
    if type(value) is list:
        return tuple(value)
    if type(value) is tuple:
        return value
    raise ValueError(f"{field} must be a JSON array")


def _require_tuple(value: object, field: str) -> object:
    return require_json_array(value, field)


JcsDigest = Annotated[
    str,
    StringConstraints(
        min_length=JCS_DIGEST_LENGTH,
        max_length=JCS_DIGEST_LENGTH,
        strip_whitespace=False,
        pattern=rf"^{JCS_SHA256_PREFIX}[0-9a-f]{{64}}$",
    ),
]
DecisionText = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MAX_DECISION_TEXT,
        strip_whitespace=False,
    ),
]
DecisionItemText = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MAX_DECISION_ITEM_TEXT,
        strip_whitespace=False,
    ),
]
RiskText = Annotated[
    str,
    StringConstraints(min_length=0, max_length=MAX_DECISION_TEXT, strip_whitespace=False),
]
LedgerSequence = Annotated[int, Field(ge=0, le=CLOUD_EVENTS_INTEGER_MAX)]
BaseRevision = Annotated[int, Field(ge=1, le=CLOUD_EVENTS_INTEGER_MAX)]


class ResearchDocumentModel(EventDocumentModel):
    """Frozen research documents: aliases only, strict, no trimming."""

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


class ObjectionKind(StrEnum):
    FALSIFIABILITY = "falsifiability"
    ALTERNATIVE_EXPLANATION = "alternative-explanation"
    DATA_LEAKAGE = "data-leakage"
    BASELINE_OR_ABLATION = "baseline-or-ablation"
    METRIC_VALIDITY = "metric-validity"
    COST_BENEFIT = "cost-benefit"
    NEGATIVE_RESULT_VALUE = "negative-result-value"
    OTHER = "other"


class DissentTargetKind(StrEnum):
    PROPOSAL = "proposal"
    DECISION = "decision"
    CONCLUSION = "conclusion"


class DecisionTargetKind(StrEnum):
    PROPOSAL = "proposal"
    RUN = "run"
    QUESTION = "question"
    DISSENT = "dissent"


class DecisionOutcome(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"
    CONTINUE = "continue"
    DEFER = "defer"


class ProposalRevisionState(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ExpectedDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"
    RANGE = "range"
    UNKNOWN = "unknown"


class ProposalPrediction(ResearchDocumentModel):
    id: EventIdentifier
    statement: DecisionItemText
    metric: EventIdentifier | None = None
    expected_direction: ExpectedDirection = Field(alias="expectedDirection")

    @field_validator("expected_direction", mode="before")
    @classmethod
    def coerce_expected_direction(cls, value: object) -> object:
        return _coerce_strenum(ExpectedDirection, value)


class RiskAssessment(ResearchDocumentModel):
    data: RiskText
    method: RiskText
    safety: RiskText
    cost: RiskText


class ProposalSubmittedPayload(ResearchDocumentModel):
    proposal_id: EventIdentifier = Field(alias="proposalId")
    base_revision: BaseRevision = Field(alias="baseRevision")
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
        return _require_tuple(value, "list")

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


class DissentObjection(ResearchDocumentModel):
    kind: ObjectionKind
    statement: DecisionItemText

    @field_validator("kind", mode="before")
    @classmethod
    def coerce_objection_kind(cls, value: object) -> object:
        return _coerce_strenum(ObjectionKind, value)


class DissentRecordedPayload(ResearchDocumentModel):
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
        return _coerce_strenum(DissentTargetKind, value)

    @field_validator("objections", "evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return _require_tuple(value, "list")

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self


class DecisionRecordedPayload(ResearchDocumentModel):
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
        return _coerce_strenum(DecisionTargetKind, value)

    @field_validator("outcome", mode="before")
    @classmethod
    def coerce_outcome(cls, value: object) -> object:
        return _coerce_strenum(DecisionOutcome, value)

    @field_validator("overridden_dissent_ids", "evidence_refs", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return _require_tuple(value, "list")

    @model_validator(mode="after")
    def identifier_lists_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        if len(self.overridden_dissent_ids) != len(set(self.overridden_dissent_ids)):
            raise ValueError("overriddenDissentIds entries must be unique")
        return self


PAYLOAD_MODELS: dict[str, type[ResearchDocumentModel]] = {
    TYPE_PROPOSAL_SUBMITTED: ProposalSubmittedPayload,
    TYPE_DISSENT_RECORDED: DissentRecordedPayload,
    TYPE_DECISION_RECORDED: DecisionRecordedPayload,
}

if set(PAYLOAD_MODELS) != DECISION_EVENT_TYPES:
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the M1-1 research event catalog")


class ProposalLedgerEntry(ResearchDocumentModel):
    proposal_id: EventIdentifier = Field(alias="proposalId")
    base_revision: BaseRevision = Field(alias="baseRevision")
    spec_diff_digest: JcsDigest = Field(alias="specDiffDigest")
    proposed_spec_digest: JcsDigest = Field(alias="proposedSpecDigest")
    rationale: DecisionText
    revision_state: ProposalRevisionState = Field(alias="revisionState")
    event_id: CloudEventsString = Field(alias="eventId")
    sequence: LedgerSequence
    accepted_by_decision_id: EventIdentifier | None = Field(
        default=None, alias="acceptedByDecisionId"
    )
    superseded_by_proposal_id: EventIdentifier | None = Field(
        default=None, alias="supersededByProposalId"
    )

    @field_validator("revision_state", mode="before")
    @classmethod
    def coerce_revision_state(cls, value: object) -> object:
        return _coerce_strenum(ProposalRevisionState, value)


class DissentLedgerEntry(ResearchDocumentModel):
    dissent_id: EventIdentifier = Field(alias="dissentId")
    target_kind: DissentTargetKind = Field(alias="targetKind")
    target_id: EventIdentifier = Field(alias="targetId")
    objections: tuple[DissentObjection, ...] = Field(min_length=1, max_length=MAX_DECISION_LIST)
    overridden_by_decision_ids: tuple[EventIdentifier, ...] = Field(
        default=(),
        alias="overriddenByDecisionIds",
        max_length=MAX_DECISION_LIST,
    )
    event_id: CloudEventsString = Field(alias="eventId")
    sequence: LedgerSequence

    @field_validator("target_kind", mode="before")
    @classmethod
    def coerce_target_kind(cls, value: object) -> object:
        return _coerce_strenum(DissentTargetKind, value)

    @field_validator("objections", "overridden_by_decision_ids", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return _require_tuple(value, "list")


class DecisionLedgerEntry(ResearchDocumentModel):
    decision_id: EventIdentifier = Field(alias="decisionId")
    target_kind: DecisionTargetKind = Field(alias="targetKind")
    target_id: EventIdentifier = Field(alias="targetId")
    outcome: DecisionOutcome
    rationale: DecisionText
    overridden_dissent_ids: tuple[EventIdentifier, ...] = Field(
        alias="overriddenDissentIds",
        max_length=MAX_DECISION_LIST,
    )
    event_id: CloudEventsString = Field(alias="eventId")
    sequence: LedgerSequence

    @field_validator("target_kind", mode="before")
    @classmethod
    def coerce_target_kind(cls, value: object) -> object:
        return _coerce_strenum(DecisionTargetKind, value)

    @field_validator("outcome", mode="before")
    @classmethod
    def coerce_outcome(cls, value: object) -> object:
        return _coerce_strenum(DecisionOutcome, value)

    @field_validator("overridden_dissent_ids", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return _require_tuple(value, "list")


class ResearchLedger(ResearchDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ResearchLedger"]
    project_id: EventIdentifier = Field(alias="projectId")
    last_sequence: LedgerSequence = Field(alias="lastSequence")
    proposals: tuple[ProposalLedgerEntry, ...] = Field(default=())
    dissents: tuple[DissentLedgerEntry, ...] = Field(default=())
    decisions: tuple[DecisionLedgerEntry, ...] = Field(default=())
    questions: tuple[()] = Field(default=())
    decision_count: int = Field(alias="decisionCount", ge=0)
    answered_question_count: int = Field(alias="answeredQuestionCount", ge=0)
    open_question_count: int = Field(alias="openQuestionCount", ge=0)
    rationale_characters: int = Field(alias="rationaleCharacters", ge=0)
    overridden_dissent_count: int = Field(alias="overriddenDissentCount", ge=0)

    @field_validator("proposals", "dissents", "decisions", "questions", mode="before")
    @classmethod
    def json_lists_are_tuples(cls, value: object) -> object:
        return _require_tuple(value, "list")

    @model_validator(mode="after")
    def questions_are_absent_until_channel_lands(self) -> Self:
        if self.questions != ():
            raise ValueError("question channel entries are not part of M1-1")
        if self.answered_question_count != 0 or self.open_question_count != 0:
            raise ValueError("question counters stay at zero until Issue #42")
        if self.decision_count != len(self.decisions):
            raise ValueError("decisionCount must equal the number of decision entries")
        return self


def empty_research_ledger(project_id: str, last_sequence: int = 0) -> ResearchLedger:
    """Return a project ledger with no proposals, dissents, or decisions."""

    return ResearchLedger.model_validate(
        {
            "apiVersion": RESEARCH_LEDGER_API_VERSION,
            "kind": "ResearchLedger",
            "projectId": project_id,
            "lastSequence": last_sequence,
            "proposals": [],
            "dissents": [],
            "decisions": [],
            "questions": [],
            "decisionCount": 0,
            "answeredQuestionCount": 0,
            "openQuestionCount": 0,
            "rationaleCharacters": 0,
            "overriddenDissentCount": 0,
        }
    )


def research_ledger_document(ledger: ResearchLedger) -> dict[str, Any]:
    """Return the deterministic alias-keyed JSON object for a ledger."""

    payload = ledger.model_dump(mode="json", by_alias=True, exclude_none=True)
    return payload


def parse_decision_payload(event: ResearchEvent) -> ResearchDocumentModel:
    """Validate a closed research-decision payload without echoing its body."""

    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        raise ResearchPayloadError(
            f"event type is not a research decision type (event id {event.id})",
            code="unknown-research-type",
        )
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = ResearchPayloadError(_payload_error_message(event), code="invalid-payload")
    else:
        return validated
    raise payload_error


def require_actor_kind(event: ResearchEvent) -> ActorKind:
    """Fail closed when a research decision event omits actor kind or uses a forbidden kind."""

    kind = event.data.actor.kind
    if kind is None:
        raise ResearchPayloadError(
            f"actor kind is required for {event.type} (event id {event.id})",
            code="actor-kind-required",
        )
    allowed = ALLOWED_ACTOR_KINDS[event.type]
    if kind not in allowed:
        raise ResearchPayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
    return kind


def _payload_error_message(event: ResearchEvent) -> str:
    return (
        f"invalid payload for research type {event.type} "
        f"(event id {event.id}, sequence {event.sequence})"
    )
