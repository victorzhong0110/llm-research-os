"""Pure, rebuildable research ledger fold over one projectId."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import TypeAdapter, ValidationError

from llm_research_os.events.models import EventIdentifier, ResearchEvent
from llm_research_os.research.errors import ResearchLedgerError, ResearchPayloadError
from llm_research_os.research.models import (
    DECISION_EVENT_TYPES,
    MAX_DECISION_LIST,
    RESEARCH_LEDGER_API_VERSION,
    TYPE_DECISION_RECORDED,
    TYPE_DISSENT_RECORDED,
    TYPE_PROPOSAL_SUBMITTED,
    TYPE_QUESTION_ANSWERED,
    TYPE_QUESTION_ASKED,
    DecisionLedgerEntry,
    DecisionOutcome,
    DecisionRecordedPayload,
    DecisionTargetKind,
    DissentLedgerEntry,
    DissentRecordedPayload,
    DissentTargetKind,
    ProposalLedgerEntry,
    ProposalRevisionState,
    ProposalSubmittedPayload,
    QuestionAnsweredPayload,
    QuestionAskedPayload,
    QuestionLedgerEntry,
    QuestionStatus,
    ResearchDocumentModel,
    ResearchLedger,
    empty_research_ledger,
    parse_decision_payload,
    require_actor_kind,
)
from llm_research_os.runs.models import TYPE_RUN_QUEUED

_IDENTIFIER = TypeAdapter(EventIdentifier)


@dataclass(frozen=True, slots=True)
class LedgerFold:
    """In-memory fold state. Not an external document; snapshot() is."""

    proposals: tuple[ProposalLedgerEntry, ...] = ()
    dissents: tuple[DissentLedgerEntry, ...] = ()
    decisions: tuple[DecisionLedgerEntry, ...] = ()
    questions: tuple[QuestionLedgerEntry, ...] = ()
    run_ids: frozenset[str] = frozenset()


class ResearchLedgerProjection:
    """Fold ResearchEvents for one ``projectId``.

    ``apply`` is a pure function of the previous fold and one already-validated
    event. It performs no I/O and never emits events.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = _require_identifier("project_id", project_id)

    def initial_state(self) -> LedgerFold:
        return LedgerFold()

    def apply(self, state: LedgerFold | None, event: ResearchEvent) -> LedgerFold:
        fold = state if state is not None else LedgerFold()
        if event.data.project_id != self.project_id:
            return fold
        if event.type == TYPE_RUN_QUEUED and event.data.run_id is not None:
            fold = replace(fold, run_ids=fold.run_ids | {event.data.run_id})
        if event.type not in DECISION_EVENT_TYPES:
            return fold
        require_actor_kind(event)
        payload = parse_decision_payload(event)
        evidence_refs = _payload_evidence_refs(payload)
        if tuple(event.data.evidence_refs) != evidence_refs:
            raise ResearchLedgerError(
                "payload evidenceRefs must match data.evidenceRefs",
                code="evidence-refs-mismatch",
            )
        if event.type == TYPE_PROPOSAL_SUBMITTED:
            if type(payload) is not ProposalSubmittedPayload:
                raise ResearchPayloadError(
                    _type_mismatch(event),
                    code="invalid-payload",
                )
            return _apply_proposal(fold, event, payload)
        if event.type == TYPE_DISSENT_RECORDED:
            if type(payload) is not DissentRecordedPayload:
                raise ResearchPayloadError(
                    _type_mismatch(event),
                    code="invalid-payload",
                )
            return _apply_dissent(fold, event, payload)
        if event.type == TYPE_QUESTION_ASKED:
            if type(payload) is not QuestionAskedPayload:
                raise ResearchPayloadError(_type_mismatch(event), code="invalid-payload")
            return _apply_question_asked(fold, event, payload)
        if event.type == TYPE_QUESTION_ANSWERED:
            if type(payload) is not QuestionAnsweredPayload:
                raise ResearchPayloadError(_type_mismatch(event), code="invalid-payload")
            return _apply_question_answered(fold, event, payload)
        if event.type != TYPE_DECISION_RECORDED or type(payload) is not DecisionRecordedPayload:
            raise ResearchPayloadError(_type_mismatch(event), code="invalid-payload")
        return _apply_decision(fold, event, payload)

    def snapshot(self, state: LedgerFold | None, last_sequence: int) -> ResearchLedger:
        fold = state if state is not None else LedgerFold()
        decisions = fold.decisions
        questions = fold.questions
        overridden = {
            dissent_id for item in decisions for dissent_id in item.overridden_dissent_ids
        }
        rationale_characters = sum(len(item.rationale) for item in decisions)
        answered = sum(1 for item in questions if item.status is QuestionStatus.ANSWERED)
        return ResearchLedger.model_validate(
            {
                "apiVersion": RESEARCH_LEDGER_API_VERSION,
                "kind": "ResearchLedger",
                "projectId": self.project_id,
                "lastSequence": last_sequence,
                "proposals": [
                    item.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for item in fold.proposals
                ],
                "dissents": [
                    item.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for item in fold.dissents
                ],
                "decisions": [
                    item.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for item in decisions
                ],
                "questions": [
                    item.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for item in questions
                ],
                "decisionCount": len(decisions),
                "answeredQuestionCount": answered,
                "openQuestionCount": len(questions) - answered,
                "rationaleCharacters": rationale_characters,
                "overriddenDissentCount": len(overridden),
            }
        )


def build_research_ledger(
    events: tuple[ResearchEvent, ...],
    *,
    project_id: str,
    last_sequence: int,
) -> ResearchLedger:
    """Fold ``events`` for one project. ``last_sequence`` is the frozen global head."""

    projection = ResearchLedgerProjection(project_id)
    fold: LedgerFold | None = None
    for event in events:
        fold = projection.apply(fold, event)
    if fold is None:
        return empty_research_ledger(project_id, last_sequence)
    return projection.snapshot(fold, last_sequence)


def _apply_proposal(
    fold: LedgerFold,
    event: ResearchEvent,
    payload: ProposalSubmittedPayload,
) -> LedgerFold:
    if payload.base_revision != event.data.experiment_revision:
        raise ResearchLedgerError(
            "proposal baseRevision must equal data.experimentRevision",
            code="proposal-revision-mismatch",
        )
    if any(item.proposal_id == payload.proposal_id for item in fold.proposals):
        raise ResearchLedgerError(
            "proposalId is not unique in this project",
            code="duplicate-proposal",
        )
    if event.data.run_id is not None:
        raise ResearchLedgerError("proposal.submitted must not set runId", code="unexpected-run-id")
    entry = ProposalLedgerEntry.model_validate(
        {
            "proposalId": payload.proposal_id,
            "baseRevision": payload.base_revision,
            "specDiffDigest": payload.spec_diff_digest,
            "proposedSpecDigest": payload.proposed_spec_digest,
            "rationale": payload.rationale,
            "revisionState": ProposalRevisionState.PROPOSED.value,
            "eventId": event.id,
            "sequence": _event_sequence(event),
        }
    )
    return replace(fold, proposals=(*fold.proposals, entry))


def _apply_dissent(
    fold: LedgerFold,
    event: ResearchEvent,
    payload: DissentRecordedPayload,
) -> LedgerFold:
    if any(item.dissent_id == payload.dissent_id for item in fold.dissents):
        raise ResearchLedgerError(
            "dissentId is not unique in this project",
            code="duplicate-dissent",
        )
    if event.data.run_id is not None:
        raise ResearchLedgerError("dissent.recorded must not set runId", code="unexpected-run-id")
    if not _dissent_target_resolves(fold, payload):
        raise ResearchLedgerError(
            "dissent target does not resolve in this project",
            code="unknown-dissent-target",
        )
    entry = DissentLedgerEntry.model_validate(
        {
            "dissentId": payload.dissent_id,
            "targetKind": payload.target_kind.value,
            "targetId": payload.target_id,
            "objections": [
                item.model_dump(mode="json", by_alias=True) for item in payload.objections
            ],
            "overriddenByDecisionIds": [],
            "eventId": event.id,
            "sequence": _event_sequence(event),
        }
    )
    return replace(fold, dissents=(*fold.dissents, entry))


def _apply_decision(
    fold: LedgerFold,
    event: ResearchEvent,
    payload: DecisionRecordedPayload,
) -> LedgerFold:
    if any(item.decision_id == payload.decision_id for item in fold.decisions):
        raise ResearchLedgerError(
            "decisionId is not unique in this project", code="duplicate-decision"
        )
    if payload.target_kind is DecisionTargetKind.RUN:
        if event.data.run_id != payload.target_id:
            raise ResearchLedgerError(
                "run-targeted decision requires data.runId to equal targetId",
                code="run-target-mismatch",
            )
    elif event.data.run_id is not None:
        raise ResearchLedgerError(
            "non-run decision must not set runId",
            code="unexpected-run-id",
        )
    if not _decision_target_resolves(fold, payload):
        raise ResearchLedgerError(
            "decision target does not resolve in this project",
            code="unknown-decision-target",
        )
    if payload.target_kind is DecisionTargetKind.QUESTION:
        question = _question(fold, payload.target_id)
        if question is None:
            raise ResearchLedgerError(
                "decision target does not resolve in this project",
                code="unknown-decision-target",
            )
        if question.status is QuestionStatus.OPEN and payload.outcome is not DecisionOutcome.DEFER:
            raise ResearchLedgerError(
                "decision on a question requires an answer or outcome=defer",
                code="unanswered-question-decision",
            )
    sequence = _event_sequence(event)
    for dissent_id in payload.overridden_dissent_ids:
        dissent = _dissent(fold, dissent_id)
        if dissent is None:
            raise ResearchLedgerError(
                "overriddenDissentIds must cite earlier dissents in this project",
                code="unknown-overridden-dissent",
            )
        if dissent.sequence >= sequence:
            raise ResearchLedgerError(
                "overridden dissent must precede the decision",
                code="overridden-dissent-order",
            )
    entry = DecisionLedgerEntry.model_validate(
        {
            "decisionId": payload.decision_id,
            "targetKind": payload.target_kind.value,
            "targetId": payload.target_id,
            "outcome": payload.outcome.value,
            "rationale": payload.rationale,
            "overriddenDissentIds": list(payload.overridden_dissent_ids),
            "eventId": event.id,
            "sequence": sequence,
        }
    )
    return replace(
        fold,
        proposals=_apply_proposal_outcome(fold.proposals, payload),
        dissents=_mark_overridden_dissents(fold.dissents, payload),
        decisions=(*fold.decisions, entry),
    )


def _apply_question_asked(
    fold: LedgerFold,
    event: ResearchEvent,
    payload: QuestionAskedPayload,
) -> LedgerFold:
    if any(item.question_id == payload.question_id for item in fold.questions):
        raise ResearchLedgerError(
            "questionId is not unique in this project",
            code="duplicate-question",
        )
    if event.data.run_id is not None:
        raise ResearchLedgerError("question.asked must not set runId", code="unexpected-run-id")
    if payload.related_proposal_id is not None and not any(
        item.proposal_id == payload.related_proposal_id for item in fold.proposals
    ):
        raise ResearchLedgerError(
            "relatedProposalId does not resolve in this project",
            code="unknown-related-proposal",
        )
    entry = QuestionLedgerEntry.model_validate(
        {
            "questionId": payload.question_id,
            "question": payload.question,
            "uncertainty": payload.uncertainty,
            "whyNotObservable": payload.why_not_observable,
            "options": list(payload.options) if payload.options is not None else [],
            "blocking": payload.blocking,
            **(
                {"relatedProposalId": payload.related_proposal_id}
                if payload.related_proposal_id is not None
                else {}
            ),
            "status": QuestionStatus.OPEN.value,
            "eventId": event.id,
            "sequence": _event_sequence(event),
        }
    )
    return replace(fold, questions=(*fold.questions, entry))


def _apply_question_answered(
    fold: LedgerFold,
    event: ResearchEvent,
    payload: QuestionAnsweredPayload,
) -> LedgerFold:
    if event.data.run_id is not None:
        raise ResearchLedgerError(
            "question.answered must not set runId",
            code="unexpected-run-id",
        )
    asked = _question(fold, payload.question_id)
    if asked is None:
        raise ResearchLedgerError(
            "questionId has no prior question.asked in this project",
            code="unknown-question",
        )
    if asked.status is QuestionStatus.ANSWERED:
        raise ResearchLedgerError(
            "questionId already has an answer",
            code="duplicate-answer",
        )
    if payload.answer.option is not None:
        allowed = asked.options
        if payload.answer.option not in allowed:
            raise ResearchLedgerError(
                "answer option is not one of the question options",
                code="invalid-answer-option",
            )
    updated = asked.model_copy(
        update={
            "status": QuestionStatus.ANSWERED,
            "answer_event_id": event.id,
            "answer_sequence": _event_sequence(event),
            "answer": payload.answer,
            "rights": payload.rights,
        }
    )
    questions = tuple(
        updated if item.question_id == payload.question_id else item for item in fold.questions
    )
    return replace(fold, questions=questions)


def _dissent_target_resolves(fold: LedgerFold, payload: DissentRecordedPayload) -> bool:
    if payload.target_kind is DissentTargetKind.PROPOSAL:
        return any(item.proposal_id == payload.target_id for item in fold.proposals)
    if payload.target_kind is DissentTargetKind.DECISION:
        return any(item.decision_id == payload.target_id for item in fold.decisions)
    return False


def _decision_target_resolves(fold: LedgerFold, payload: DecisionRecordedPayload) -> bool:
    if payload.target_kind is DecisionTargetKind.PROPOSAL:
        return any(item.proposal_id == payload.target_id for item in fold.proposals)
    if payload.target_kind is DecisionTargetKind.DISSENT:
        return any(item.dissent_id == payload.target_id for item in fold.dissents)
    if payload.target_kind is DecisionTargetKind.RUN:
        return payload.target_id in fold.run_ids
    if payload.target_kind is DecisionTargetKind.QUESTION:
        return any(item.question_id == payload.target_id for item in fold.questions)
    return False


def _apply_proposal_outcome(
    proposals: tuple[ProposalLedgerEntry, ...],
    payload: DecisionRecordedPayload,
) -> tuple[ProposalLedgerEntry, ...]:
    if payload.target_kind is not DecisionTargetKind.PROPOSAL:
        return proposals
    if payload.outcome not in {DecisionOutcome.ACCEPT, DecisionOutcome.REJECT}:
        return proposals
    target = next((item for item in proposals if item.proposal_id == payload.target_id), None)
    if target is None:
        raise ResearchLedgerError(
            "decision target does not resolve in this project",
            code="unknown-decision-target",
        )
    if target.revision_state not in {
        ProposalRevisionState.PROPOSED,
        ProposalRevisionState.VALIDATED,
    }:
        raise ResearchLedgerError(
            "proposal is not open for this decision outcome",
            code="proposal-not-open",
        )
    updated: list[ProposalLedgerEntry] = []
    for proposal in proposals:
        if proposal.proposal_id == payload.target_id:
            if payload.outcome is DecisionOutcome.ACCEPT:
                updated.append(
                    proposal.model_copy(
                        update={
                            "revision_state": ProposalRevisionState.ACCEPTED,
                            "accepted_by_decision_id": payload.decision_id,
                        }
                    )
                )
            else:
                updated.append(
                    proposal.model_copy(update={"revision_state": ProposalRevisionState.REJECTED})
                )
            continue
        if (
            payload.outcome is DecisionOutcome.ACCEPT
            and proposal.revision_state is ProposalRevisionState.ACCEPTED
            and proposal.base_revision < target.base_revision
        ):
            updated.append(
                proposal.model_copy(
                    update={
                        "revision_state": ProposalRevisionState.SUPERSEDED,
                        "superseded_by_proposal_id": payload.target_id,
                    }
                )
            )
            continue
        updated.append(proposal)
    return tuple(updated)


def _mark_overridden_dissents(
    dissents: tuple[DissentLedgerEntry, ...],
    payload: DecisionRecordedPayload,
) -> tuple[DissentLedgerEntry, ...]:
    if not payload.overridden_dissent_ids:
        return dissents
    overridden = set(payload.overridden_dissent_ids)
    updated: list[DissentLedgerEntry] = []
    for dissent in dissents:
        if dissent.dissent_id not in overridden:
            updated.append(dissent)
            continue
        linked = (*dissent.overridden_by_decision_ids, payload.decision_id)
        if len(linked) > MAX_DECISION_LIST:
            raise ResearchLedgerError(
                "overriddenByDecisionIds exceeds the ledger list cap",
                code="override-list-exhausted",
            )
        dumped = dissent.model_dump(mode="json", by_alias=True)
        dumped["overriddenByDecisionIds"] = list(linked)
        updated.append(DissentLedgerEntry.model_validate(dumped))
    return tuple(updated)


def _dissent(fold: LedgerFold, dissent_id: str) -> DissentLedgerEntry | None:
    for item in fold.dissents:
        if item.dissent_id == dissent_id:
            return item
    return None


def _question(fold: LedgerFold, question_id: str) -> QuestionLedgerEntry | None:
    for item in fold.questions:
        if item.question_id == question_id:
            return item
    return None


def _payload_evidence_refs(payload: ResearchDocumentModel) -> tuple[str, ...]:
    refs = getattr(payload, "evidence_refs", None)
    if type(refs) is not tuple:
        raise ResearchPayloadError("payload evidenceRefs is missing", code="invalid-payload")
    return refs


def _event_sequence(event: ResearchEvent) -> int:
    return int(event.sequence)


def _type_mismatch(event: ResearchEvent) -> str:
    return f"payload type mismatch for {event.type} (event id {event.id})"


def _require_identifier(name: str, value: str) -> str:
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError:
        raise ResearchPayloadError(
            f"{name} is not a valid identifier",
            code="invalid-identifier",
        ) from None
