from __future__ import annotations

import json
import shutil
from pathlib import Path

from llm_research_os.cli import main
from llm_research_os.m1.prove import prove_checkpoint
from llm_research_os.runs.models import TYPE_RUN_QUEUED
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m1-checkpoint"


def test_accept_cli_records_the_research_chain_and_report(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    assert (
        main(
            [
                "m1",
                "prove",
                str(CORPUS),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["kind"] == "M1CheckpointReceipt"
    assert payload["decision"] == "accept"
    assert payload["queued"] is True
    assert payload["runId"] == "run.simulated"
    assert payload["decisionCount"] == 1
    assert payload["answeredQuestionCount"] == 1
    assert payload["rationaleCharacters"] > 0
    assert payload["overriddenDissentCount"] == 1
    assert payload["eventTypes"][:7] == [
        "ai.call.started",
        "ai.call.completed",
        "proposal.submitted",
        "dissent.recorded",
        "question.asked",
        "question.answered",
        "decision.recorded",
    ]
    assert "plan.authorization.evaluated" in payload["eventTypes"]
    assert TYPE_RUN_QUEUED in payload["eventTypes"]
    text_db = tmp_path / "text.db"
    assert main(["m1", "prove", str(CORPUS), str(text_db)]) == 0
    text = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "dissent.eval-leakage" in text
    assert "rationale characters" in text
    with EventStore(database, require_existing=True) as store:
        types = [item.event.type for item in store.read_events(limit=40)]
        assert types == payload["eventTypes"]


def test_reject_cli_does_not_queue_a_run(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    assert (
        main(
            [
                "m1",
                "prove",
                str(CORPUS),
                str(database),
                "--decision",
                "reject",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["decision"] == "reject"
    assert payload["queued"] is False
    assert payload["runId"] is None
    assert payload["overriddenDissentCount"] == 0
    assert TYPE_RUN_QUEUED not in payload["eventTypes"]
    assert "plan.authorization.evaluated" not in payload["eventTypes"]
    assert "dissent.recorded" in payload["eventTypes"]


def test_prove_replays_the_same_ledger_after_reopen(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    result = prove_checkpoint(CORPUS, database, decision="accept")
    assert result.report_markdown is not None
    assert "dissent.eval-leakage" in result.report_markdown
    assert "decision.accept-revise-eval" in result.report_markdown
    with EventStore(database, require_existing=True) as store:
        assert [item.event.type for item in store.read_events(limit=40)] == list(result.event_types)
        assert [item.event.id for item in store.read_events(limit=40)] == list(result.event_ids)


def test_stale_proposal_digest_fails_before_any_event(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    fixture_path = corpus / "fixture.json"
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    document["output"]["proposedSpecDigest"] = "jcs-sha256:" + ("0" * 64)
    fixture_path.write_text(json.dumps(document), encoding="utf-8")
    database = tmp_path / "research.db"
    assert main(["m1", "prove", str(corpus), str(database)]) == 2
    assert not database.exists()


def test_non_empty_store_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    assert main(["m1", "prove", str(CORPUS), str(database), "--format", "json"]) == 0
    assert main(["m1", "prove", str(CORPUS), str(database)]) == 2
