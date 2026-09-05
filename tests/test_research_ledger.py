from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.cli import main
from llm_research_os.events.models import validate_event_document
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.errors import ResearchLedgerError
from llm_research_os.research.ledger import ResearchLedgerProjection, build_research_ledger
from llm_research_os.research.models import MAX_DECISION_LIST, ProposalRevisionState
from llm_research_os.research.requests import (
    load_decision_record_request,
    load_dissent_record_request,
    load_proposal_submit_request,
    load_question_answer_request,
    load_question_ask_request,
    validate_decision_record_request,
)
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "research-decisions"
PROPOSAL = EXAMPLES / "valid" / "proposal-submit.json"
DISSENT = EXAMPLES / "valid" / "dissent-record.json"
DECISION = EXAMPLES / "valid" / "decision-record.json"
QUESTION_ASK = EXAMPLES / "valid" / "question-ask.json"
QUESTION_ANSWER = EXAMPLES / "valid" / "question-answer.json"
RATIONALE = "The dissent stands; we still accept."
OBJECTION = "The proposed split still shares documents with training."
QUESTION = "Was any evaluation document used in training?"
ANSWER_OPTION = "No overlap."
PROJECT = "example-minimal"


def _init_store(path: Path) -> None:
    with EventStore(path) as store:
        assert store.last_sequence() == 0


def _record(database: Path, command: list[str]) -> int:
    return main([*command, str(database), "--format", "json"])


def test_cli_corpus_builds_ledger_with_hand_computed_counters(
    tmp_path: Path, capsys: object
) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    assert _record(database, ["dissents", "record", str(DISSENT)]) == 0
    assert _record(database, ["decisions", "record", str(DECISION)]) == 0
    receipts = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Tighten the evaluation split." not in receipts
    assert OBJECTION not in receipts
    assert RATIONALE not in receipts
    assert (
        main(["research", "ledger", str(database), "--project", PROJECT, "--format", "json"]) == 0
    )
    ledger = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert ledger["kind"] == "ResearchLedger"
    assert ledger["decisionCount"] == 1
    assert ledger["overriddenDissentCount"] == 1
    assert ledger["rationaleCharacters"] == 36
    assert ledger["rationaleCharacters"] == len(RATIONALE)
    assert ledger["answeredQuestionCount"] == 0
    assert ledger["openQuestionCount"] == 0
    assert ledger["questions"] == []
    assert ledger["proposals"][0]["revisionState"] == ProposalRevisionState.ACCEPTED.value
    dissent = ledger["dissents"][0]
    assert dissent["dissentId"] == "dissent.eval-leakage"
    assert dissent["objections"] == [
        {"kind": "data-leakage", "statement": OBJECTION},
    ]
    assert dissent["overriddenByDecisionIds"] == ["decision.accept-revise-eval"]
    assert ledger["decisions"][0]["overriddenDissentIds"] == ["dissent.eval-leakage"]
    assert ledger["decisions"][0]["rationale"] == RATIONALE


def test_replay_equality_across_two_store_opens(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    assert _record(database, ["dissents", "record", str(DISSENT)]) == 0
    assert _record(database, ["decisions", "record", str(DECISION)]) == 0
    with EventStore(database, create=False) as first:
        events = tuple(item.event for item in first.read_events(after_sequence=0, limit=100))
        high_water = first.last_sequence()
        left = build_research_ledger(events, project_id=PROJECT, last_sequence=high_water)
    with EventStore(database, create=False) as second:
        events = tuple(item.event for item in second.read_events(after_sequence=0, limit=100))
        right = build_research_ledger(
            events, project_id=PROJECT, last_sequence=second.last_sequence()
        )
    assert left == right
    assert left.dissents[0].objections[0].statement == OBJECTION


def test_unknown_dissent_target_is_a_domain_refusal(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    hostile = "sk-secret-should-not-echo"
    document = load_document(DISSENT)
    document["targetId"] = "proposal.missing"
    document["objections"][0]["statement"] = hostile
    path = tmp_path / "bad-dissent.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _record(database, ["dissents", "record", str(path)]) == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert hostile not in output.err
    assert "unknown-dissent-target" in output.err


def test_invalid_request_does_not_echo_text(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    hostile = "sk-secret-should-not-echo"
    document = load_document(DECISION)
    document["rationale"] = ""
    document["extraSecret"] = hostile
    path = tmp_path / "bad-decision.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _record(database, ["decisions", "record", str(path)]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert hostile not in output.err
    assert output.out == ""


def test_ai_actor_decision_request_is_rejected() -> None:
    with pytest.raises(Exception, match="research request failed validation"):
        load_decision_record_request(EXAMPLES / "invalid" / "decision-ai-actor.json")


def test_foreign_project_events_do_not_enter_the_ledger(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    foreign = load_proposal_submit_request(PROPOSAL).event_draft()
    foreign["id"] = "evt.foreign.proposal"
    foreign["data"]["projectId"] = "project.other"
    foreign["data"]["payload"]["proposalId"] = "proposal.other"
    with EventStore(database, require_existing=True) as store:
        store.append(foreign)
        events = tuple(item.event for item in store.read_events(after_sequence=0, limit=100))
        ledger = build_research_ledger(
            events, project_id=PROJECT, last_sequence=store.last_sequence()
        )
    assert len(ledger.proposals) == 1
    assert ledger.proposals[0].proposal_id == "proposal.revise-eval"


def test_missing_database_is_an_input_error(tmp_path: Path, capsys: object) -> None:
    missing = tmp_path / "missing.db"
    assert main(["proposals", "submit", str(PROPOSAL), str(missing), "--format", "json"]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert output.err


def test_ledger_error_on_duplicate_proposal() -> None:
    proposal = load_proposal_submit_request(PROPOSAL)
    event = _preflight(proposal.event_draft(), sequence=1)
    projection = ResearchLedgerProjection(PROJECT)
    fold = projection.apply(None, event)
    with pytest.raises(ResearchLedgerError, match="proposalId is not unique"):
        projection.apply(fold, _preflight(proposal.event_draft(), sequence=2, event_id="evt.dup"))


def _override_draft(index: int) -> dict[str, Any]:
    document = load_document(DECISION)
    document["decisionId"] = f"decision.override.{index}"
    document["subject"] = f"decision.override.{index}"
    document["event"] = {
        "id": f"evt.decision.override.{index}",
        "time": "2026-09-04T12:03:00Z",
    }
    document["targetKind"] = "dissent"
    document["targetId"] = "dissent.eval-leakage"
    document["outcome"] = "continue"
    document["overriddenDissentIds"] = ["dissent.eval-leakage"]
    return validate_decision_record_request(document).event_draft()


def test_thirty_third_override_is_rejected_before_commit(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = ResearchControl(store, project_id=PROJECT)
        control.append(load_proposal_submit_request(PROPOSAL).event_draft())
        control.append(load_dissent_record_request(DISSENT).event_draft())
        for index in range(MAX_DECISION_LIST):
            control.append(_override_draft(index))
        head = store.last_sequence()
        with pytest.raises(ResearchLedgerError, match="overriddenByDecisionIds exceeds"):
            control.append(_override_draft(MAX_DECISION_LIST))
        assert store.last_sequence() == head
        assert store.get_event(f"evt.decision.override.{MAX_DECISION_LIST}") is None


def test_question_channel_corpus_and_counters(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    assert _record(database, ["questions", "ask", str(QUESTION_ASK)]) == 0
    assert _record(database, ["questions", "answer", str(QUESTION_ANSWER)]) == 0
    receipts = capsys.readouterr().out  # type: ignore[attr-defined]
    assert QUESTION not in receipts
    assert ANSWER_OPTION not in receipts
    assert (
        main(["research", "ledger", str(database), "--project", PROJECT, "--format", "json"]) == 0
    )
    ledger = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert ledger["openQuestionCount"] == 0
    assert ledger["answeredQuestionCount"] == 1
    assert ledger["questions"][0]["status"] == "answered"
    assert ledger["questions"][0]["question"] == QUESTION
    assert ledger["questions"][0]["answer"] == {"option": ANSWER_OPTION}


def test_answer_without_ask_is_a_domain_refusal(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["questions", "answer", str(QUESTION_ANSWER)]) == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert ANSWER_OPTION not in output.err
    assert "unknown-question" in output.err


def test_second_answer_is_a_domain_refusal(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    assert _record(database, ["questions", "ask", str(QUESTION_ASK)]) == 0
    assert _record(database, ["questions", "answer", str(QUESTION_ANSWER)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    document = load_document(QUESTION_ANSWER)
    document["event"] = {"id": "evt.question.answer.2", "time": "2026-09-04T12:06:00Z"}
    path = tmp_path / "second-answer.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _record(database, ["questions", "answer", str(path)]) == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert ANSWER_OPTION not in output.err
    assert "duplicate-answer" in output.err


def test_option_outside_the_closed_list_is_a_domain_refusal(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert _record(database, ["proposals", "submit", str(PROPOSAL)]) == 0
    assert _record(database, ["questions", "ask", str(QUESTION_ASK)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    hostile = "sk-secret-should-not-echo"
    document = load_document(QUESTION_ANSWER)
    document["answer"] = {"option": hostile}
    path = tmp_path / "bad-option.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _record(database, ["questions", "answer", str(path)]) == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert hostile not in output.err
    assert QUESTION not in output.err
    assert "invalid-answer-option" in output.err


def test_human_ask_and_ai_answer_fail_request_validation() -> None:
    with pytest.raises(Exception, match="research request failed validation"):
        load_question_ask_request(EXAMPLES / "invalid" / "question-human-actor.json")
    with pytest.raises(Exception, match="research request failed validation"):
        load_question_answer_request(EXAMPLES / "invalid" / "answer-ai-actor.json")


def test_unknown_rights_cannot_authorize_training() -> None:
    with pytest.raises(Exception, match="research request failed validation"):
        load_question_answer_request(EXAMPLES / "invalid" / "answer-unknown-training.json")


def test_unknown_rights_training_does_not_echo_answer(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    hostile = "sk-secret-should-not-echo"
    assert (
        main(
            [
                "questions",
                "answer",
                str(EXAMPLES / "invalid" / "answer-unknown-training.json"),
                str(database),
                "--format",
                "json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert hostile not in output.err
    assert output.out == ""


def test_unanswered_question_decision_requires_defer(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = ResearchControl(store, project_id=PROJECT)
        control.append(load_proposal_submit_request(PROPOSAL).event_draft())
        control.append(load_question_ask_request(QUESTION_ASK).event_draft())
        accept = load_document(DECISION)
        accept["decisionId"] = "decision.close-question"
        accept["targetKind"] = "question"
        accept["targetId"] = "question.eval-split"
        accept["overriddenDissentIds"] = []
        accept["event"] = {"id": "evt.decision.question", "time": "2026-09-04T12:06:00Z"}
        with pytest.raises(ResearchLedgerError, match="requires an answer or outcome=defer"):
            control.append(validate_decision_record_request(accept).event_draft())
        accept["outcome"] = "defer"
        result = control.append(validate_decision_record_request(accept).event_draft())
        assert result.snapshot.questions[0].status.value == "open"


def _preflight(draft: dict[str, Any], *, sequence: int, event_id: str | None = None):
    document = dict(draft)
    if event_id is not None:
        document["id"] = event_id
    document.update(
        {
            "sequence": str(sequence),
            "sequencetype": "Integer",
            "streamversion": sequence - 1,
        }
    )
    return validate_event_document(document)
