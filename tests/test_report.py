from __future__ import annotations

from pathlib import Path

import pytest

from llm_research_os.cli import main
from llm_research_os.events.models import validate_event_document
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.synthetic import (
    TYPE_EVALUATION_METRIC,
    TYPE_TRAINING_STEP,
    append_synthetic_metrics,
    metric_event_draft,
    parse_evaluation_metric_payload,
    parse_training_step_payload,
    synthetic_evaluation_payload,
    synthetic_training_payload,
)
from llm_research_os.report.fold import build_run_report
from llm_research_os.report.render import _fragment, _html_link, _md_link
from llm_research_os.research.requests import load_proposal_submit_request
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
REQUEST = ROOT / "examples" / "simulation-requests" / "valid" / "success-with-metrics.json"
PROPOSAL = ROOT / "examples" / "research-decisions" / "valid" / "proposal-submit.json"
DISSENT = ROOT / "examples" / "research-decisions" / "valid" / "dissent-record.json"
DECISION = ROOT / "examples" / "research-decisions" / "valid" / "decision-record.json"
RUN = "run.simulated"
ATTEMPT = "attempt.1"


def _simulate(database: Path) -> None:
    assert (
        main(
            [
                "runs",
                "simulate",
                str(SPEC),
                str(REQUEST),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )


def test_report_markdown_cites_event_ids(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _simulate(database)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["report", RUN, "--database", str(database), "--format", "markdown"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    for heading in ("## Research", "## Training", "## Cost", "## Lineage"):
        assert heading in output
    assert "[`evt.training.step`](#evt.training.step)" in output
    assert "[`evt.evaluation.metric`](#evt.evaluation.metric)" in output
    assert "[`evt.6.run.completed`](#evt.6.run.completed)" in output
    training = synthetic_training_payload(RUN, ATTEMPT)
    evaluation = synthetic_evaluation_payload(RUN, ATTEMPT)
    assert training["loss"] in output
    assert evaluation["value"] in output
    assert "No `budget.*` facts for this project." in output
    assert "React Flow" not in output


def test_report_html_is_static_and_anchored(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _simulate(database)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["report", RUN, "--database", str(database), "--format", "html"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert output.startswith("<!DOCTYPE html>")
    assert 'href="#evt.training.step"' in output
    assert 'id="evt.training.step"' in output
    assert "<script>" not in output
    assert "react-flow" not in output.lower()
    assert "example-minimal" in output


def test_report_missing_run_exits_one(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.verify_integrity()
    assert main(["report", "run.missing", "--database", str(database)]) == 1
    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "run-not-found" in error


def test_report_project_mismatch_exits_two(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _simulate(database)
    assert (
        main(
            [
                "report",
                RUN,
                "--database",
                str(database),
                "--project",
                "project.other",
            ]
        )
        == 2
    )
    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "run-project-mismatch" in error


def test_report_cites_research_ledger_event_ids(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _simulate(database)
    assert main(["proposals", "submit", str(PROPOSAL), str(database), "--format", "json"]) == 0
    assert main(["dissents", "record", str(DISSENT), str(database), "--format", "json"]) == 0
    assert main(["decisions", "record", str(DECISION), str(database), "--format", "json"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["report", RUN, "--database", str(database), "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "[`evt.proposal.1`](#evt.proposal.1)" in markdown
    assert "[`evt.dissent.1`](#evt.dissent.1)" in markdown
    assert "[`evt.decision.1`](#evt.decision.1)" in markdown
    assert main(["report", RUN, "--database", str(database), "--format", "html"]) == 0
    html = capsys.readouterr().out  # type: ignore[attr-defined]
    assert 'href="#evt.proposal.1"' in html
    assert "proposal.revise-eval" in html
    assert "<script>" not in html


def test_report_rejects_invalid_run_identifier(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.verify_integrity()
    assert main(["report", "..", "--database", str(database)]) == 2
    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "invalid-identifier" in error


def test_synthetic_payload_parsers_reject_type_mismatch() -> None:
    draft = metric_event_draft(
        TYPE_EVALUATION_METRIC,
        {TYPE_EVALUATION_METRIC: ("evt.evaluation.metric", "2026-08-30T12:00:00Z")},
        source="https://researchos.dev/projects/example-minimal",
        subject="run.simulated",
        stream_id="stream.simulated",
        actor_id="researcher.alice",
        project_id="example-minimal",
        run_id=RUN,
        revision=1,
        attempt_id=ATTEMPT,
    )
    probe = dict(draft)
    probe.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
    event = validate_event_document(probe)
    parse_evaluation_metric_payload(event)
    with pytest.raises(SimulationError, match=r"not training\.step"):
        parse_training_step_payload(event)
    with pytest.raises(SimulationError, match="not supported"):
        metric_event_draft(
            "metric.unknown",
            {"metric.unknown": ("evt.unknown", "2026-08-30T12:00:00Z")},
            source="https://researchos.dev/projects/example-minimal",
            subject="run.simulated",
            stream_id="stream.simulated",
            actor_id="researcher.alice",
            project_id="example-minimal",
            run_id=RUN,
            revision=1,
            attempt_id=ATTEMPT,
        )


def test_synthetic_metric_resume_requires_canonical_match(tmp_path: Path) -> None:
    events = {TYPE_TRAINING_STEP: ("evt.training.step", "2026-08-30T12:00:00Z")}
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        first = append_synthetic_metrics(
            store,
            events,
            source="https://researchos.dev/projects/example-minimal",
            subject="run.simulated",
            stream_id="stream.simulated",
            actor_id="researcher.alice",
            project_id="example-minimal",
            run_id="run.a",
            revision=1,
            attempt_id=ATTEMPT,
        )
        assert len(first) == 1
        assert (
            append_synthetic_metrics(
                store,
                events,
                source="https://researchos.dev/projects/example-minimal",
                subject="run.simulated",
                stream_id="stream.simulated",
                actor_id="researcher.alice",
                project_id="example-minimal",
                run_id="run.a",
                revision=1,
                attempt_id=ATTEMPT,
            )
            == []
        )
        with pytest.raises(SimulationError, match="already exists"):
            append_synthetic_metrics(
                store,
                events,
                source="https://researchos.dev/projects/example-minimal",
                subject="run.simulated",
                stream_id="stream.simulated",
                actor_id="researcher.alice",
                project_id="example-minimal",
                run_id="run.b",
                revision=1,
                attempt_id=ATTEMPT,
            )


def test_report_omits_facts_appended_after_the_frozen_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "research.db"
    _simulate(database)
    request = load_proposal_submit_request(PROPOSAL)
    with EventStore(database, require_existing=True) as store:
        original = EventStore.freeze_high_water
        appended = {"done": False}

        def freeze(self: EventStore) -> int:
            head = original(self)
            if not appended["done"]:
                appended["done"] = True
                self.append(request.event_draft(), expected_last_sequence=head)
                return head
            return original(self)

        monkeypatch.setattr(EventStore, "freeze_high_water", freeze)
        report = build_run_report(store, RUN)
        assert report.ledger.proposals == ()
        assert store.last_sequence() == report.last_sequence + 1


def test_markdown_and_html_anchors_percent_encode_punctuation() -> None:
    event_id = 'evt.foo) bar"baz*`#λ'
    fragment = _fragment(event_id)
    assert ")" not in fragment
    assert " " not in fragment
    assert '"' not in fragment
    assert "`" not in fragment
    assert "#" not in fragment
    assert "λ" not in fragment
    markdown = _md_link(event_id)
    assert markdown.endswith(f"](#{fragment})")
    html = _html_link(event_id)
    assert f'href="#{fragment}"' in html
    assert "evt.foo)" in html
    assert "λ" in html
