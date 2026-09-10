from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_research_os.cli import main
from llm_research_os.m2.bench import run_perf_baseline
from llm_research_os.report.fold import build_run_report
from llm_research_os.report.render import render_html, render_markdown
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.drafts import registered_draft
from llm_research_os.workers.models import WORKER_EVENT_TYPES

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "events" / "valid" / "minimal.json"
CORPUS = ROOT / "examples" / "m2-checkpoint"


def _heartbeat_draft(index: int) -> dict[str, object]:
    document = load_document(EXAMPLES)
    document.pop("sequence")
    document.pop("sequencetype")
    document.pop("streamversion")
    document["id"] = f"evt.perf.test.heartbeat.{index}"
    document["type"] = "run.heartbeat"
    document["streamid"] = "example-minimal"
    data = document["data"]
    assert type(data) is dict
    data["projectId"] = "example-minimal"
    data.pop("runId", None)
    return document


def test_worker_rebuild_folds_only_worker_types_after_heartbeats(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        for index in range(1, 51):
            store.append(_heartbeat_draft(index))
        control = WorkerControl(store, project_id="example-minimal")
        control.append(
            registered_draft(
                project_id="example-minimal",
                worker_id="worker.loopback.1",
                event_id="evt.worker.registered.perf.1",
                time="2026-09-07T12:00:00Z",
                source="https://researchos.dev/projects/example-minimal",
                actor_id="researcher.alice",
            )
        )
        seen: list[frozenset[str] | None] = []
        original = store.read_events

        def _read(
            *,
            after_sequence: int = 0,
            limit: int = 100,
            until_sequence: int | None = None,
            event_types: frozenset[str] | None = None,
        ) -> object:
            seen.append(event_types)
            return original(
                after_sequence=after_sequence,
                limit=limit,
                until_sequence=until_sequence,
                event_types=event_types,
            )

        store.read_events = _read  # type: ignore[method-assign]
        head = control.rebuild()
    assert seen
    assert all(item == WORKER_EVENT_TYPES for item in seen)
    assert head.last_sequence == 51
    assert head.fold.worker("worker.loopback.1") is not None


def test_report_lineage_stays_on_the_run_when_heartbeats_fill_the_store(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        for index in range(1, 201):
            store.append(_heartbeat_draft(index))
        queued = _heartbeat_draft(201)
        queued["id"] = "evt.perf.test.queued.201"
        queued["type"] = "run.queued"
        data = queued["data"]
        assert type(data) is dict
        data["runId"] = "run.worker.cpu"
        data["payload"] = {
            "workflowId": "wf.cpu",
            "specDigest": "jcs-sha256:" + ("0" * 64),
            "registryDigest": "jcs-sha256:" + ("1" * 64),
            "planDigest": "jcs-sha256:" + ("2" * 64),
            "decisionDigest": "jcs-sha256:" + ("3" * 64),
            "maxAttempts": 1,
        }
        store.append(queued)
        report = build_run_report(store, "run.worker.cpu", project_id="example-minimal")
    assert len(report.lineage) == 1
    markdown = render_markdown(report)
    html = render_html(report)
    assert "evt.perf.test.heartbeat" not in markdown
    assert "Spec digest" in markdown
    assert "Spec digest" in html
    assert report.lineage[0].event.type == "run.queued"


def test_m2_bench_cli_records_10k_receipt(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "bench.db"
    assert main(["m2", "bench", str(database), "--events", "10000", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["kind"] == "M2PerfBaseline"
    assert payload["eventCount"] == 10_000
    assert payload["lineageEvents"] == 1
    assert payload["appendSeconds"] < 30
    assert payload["replaySeconds"] < 30
    assert payload["workerRebuildSeconds"] < 5
    assert payload["reportSeconds"] < 30
    assert payload["reportCharacters"] < 8_000
    assert payload["peakRssBytes"] > 0


@pytest.mark.slow
def test_perf_baseline_100k_keeps_report_lineage_short(tmp_path: Path) -> None:
    result = run_perf_baseline(tmp_path / "bench-100k.db", 100_000)
    assert result.event_count == 100_000
    assert result.lineage_events == 1
    assert result.append_seconds < 180
    assert result.replay_seconds < 120
    assert result.worker_rebuild_seconds < 15
    assert result.report_seconds < 120
    assert result.report_characters < 8_000
    assert result.peak_rss_bytes > 0


def test_m2_bench_refuses_existing_database(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "bench.db"
    database.write_text("existing", encoding="utf-8")
    assert main(["m2", "bench", str(database)]) == 2
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "must not already exist" in err


def test_perf_baseline_rejects_unsupported_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="10000 or 100000"):
        run_perf_baseline(tmp_path / "bench.db", 1_000)
