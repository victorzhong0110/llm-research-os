from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_research_os.cli import main
from llm_research_os.m2.bench import run_perf_baseline
from llm_research_os.m2.usage import run_usage_evidence
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]


def test_usage_evidence_uses_control_path_not_eventstore_fill(tmp_path: Path) -> None:
    output = tmp_path / "usage"
    evidence = run_usage_evidence(output)
    payload = evidence.as_json()
    assert payload["kind"] == "M2UsageEvidence"
    assert payload["usedEventStoreAppendFill"] is False
    assert payload["gpu"] == "not-run"
    assert payload["crossMachine"] == "pending-live"
    control = evidence.control_path
    assert control["usedEventStoreAppendFill"] is False
    assert control["concurrentWorkers"] == 4
    assert int(control["eventCount"]) >= 20
    counts = control["eventTypeCounts"]
    assert isinstance(counts, dict)
    assert counts.get("proposal.submitted", 0) == 4
    assert counts.get("budget.limit.recorded", 0) == 1
    assert counts.get("work.claimed", 0) >= 4
    assert counts.get("work.completed", 0) >= 4
    assert "run.heartbeat" not in counts
    assert counts.get("run.cancel.requested", 0) == 1
    assert control["cancelRequestedOnResume"] is True
    assert control["foreignClaimCode"] == "grant-worker-mismatch"
    assert int(control["sqliteBytes"]) > 0
    isolated = evidence.isolated_worker
    assert isolated["status"] == "observed"
    assert isolated["privateCas"] is True
    assert isolated["localhostIsNotCrossMachine"] is True
    report = evidence.report
    for label in (
        "Spec digest",
        "Registry digest",
        "Plan digest",
        "Worker runtime",
        "Image digest",
        "Config digest",
        "Output artifact",
    ):
        assert label in report["cites"]
    markdown = (output / "isolated" / "report.md").read_text(encoding="utf-8")
    assert "Image digest" in markdown
    assert "Output artifact" in markdown
    oci = evidence.oci
    assert oci["status"] in {"observed", "skipped-no-runtime"}
    if oci["status"] == "skipped-no-runtime":
        assert oci["required"] is False
    with EventStore(output / "control" / "research.db", require_existing=True) as store:
        types = [item.event.type for item in store.read_events(limit=500)]
    assert "work.claimed" in types
    assert "proposal.submitted" in types
    assert "budget.limit.recorded" in types


def test_m2_usage_cli_writes_receipt(tmp_path: Path, capsys: object) -> None:
    output = tmp_path / "cli-usage"
    assert main(["m2", "usage", str(output), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["kind"] == "M2UsageEvidence"
    assert payload["usedEventStoreAppendFill"] is False
    saved = json.loads((output / "USAGE.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "M2UsageEvidence"


def test_m2_usage_refuses_non_empty_output(tmp_path: Path, capsys: object) -> None:
    output = tmp_path / "used"
    output.mkdir()
    (output / "stale.txt").write_text("nope", encoding="utf-8")
    assert main(["m2", "usage", str(output)]) == 2
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "not empty" in err


def test_eventstore_append_fill_is_a_different_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="10000 or 100000"):
        run_perf_baseline(tmp_path / "other.db", 4)
