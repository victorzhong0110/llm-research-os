"""Reproducible EventStore append/replay/claim/report baseline. Not a GPU claim."""

from __future__ import annotations

import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.report.fold import build_run_report
from llm_research_os.report.render import render_markdown
from llm_research_os.spec.io import load_document
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore
from llm_research_os.workers.control import WorkerControl

BENCH_EVENT_COUNTS = (10_000, 100_000)
_SOURCE = "https://researchos.dev/projects/example-minimal"
_PROJECT = "example-minimal"
_RUN = "run.worker.cpu"
_TEMPLATE = Path(__file__).resolve().parents[3] / "examples" / "events" / "valid" / "minimal.json"
_ZERO = "jcs-sha256:" + ("0" * 64)
_ONE = "jcs-sha256:" + ("1" * 64)
_TWO = "jcs-sha256:" + ("2" * 64)
_THREE = "jcs-sha256:" + ("3" * 64)


@dataclass(frozen=True, slots=True)
class M2BenchResult:
    event_count: int
    append_seconds: float
    replay_seconds: float
    worker_rebuild_seconds: float
    report_seconds: float
    peak_rss_bytes: int
    report_characters: int
    lineage_events: int

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "M2PerfBaseline",
            "eventCount": self.event_count,
            "appendSeconds": _seconds(self.append_seconds),
            "replaySeconds": _seconds(self.replay_seconds),
            "workerRebuildSeconds": _seconds(self.worker_rebuild_seconds),
            "reportSeconds": _seconds(self.report_seconds),
            "peakRssBytes": self.peak_rss_bytes,
            "reportCharacters": self.report_characters,
            "lineageEvents": self.lineage_events,
        }


def run_perf_baseline(database: Path, event_count: int) -> M2BenchResult:
    """Fill ``event_count`` facts with EventStore.append, then measure replay/claim/report.

    Heartbeats stay off this log. Worker rebuild is the claim-path fold cost.
    Receipts are measurements, not SLA numbers.
    """

    if event_count not in BENCH_EVENT_COUNTS:
        raise ValueError("event_count must be 10000 or 100000")
    if database.exists():
        raise ValueError("perf baseline database must not already exist")
    template = _base_template()
    rss_before = _max_rss_bytes()
    started = time.perf_counter()
    with EventStore(database) as store:
        for index in range(1, event_count):
            store.append(_heartbeat_from(template, index))
        store.append(_queued_from(template, event_count))
        append_seconds = time.perf_counter() - started
        replay_started = time.perf_counter()
        replayed = sum(
            1 for _ in replay_events(store, page_size=MAX_READ_PAGE_SIZE, freeze_high_water=False)
        )
        replay_seconds = time.perf_counter() - replay_started
        rebuild_started = time.perf_counter()
        WorkerControl(store, project_id=_PROJECT, page_size=MAX_READ_PAGE_SIZE).rebuild()
        rebuild_seconds = time.perf_counter() - rebuild_started
        report_started = time.perf_counter()
        report = build_run_report(store, _RUN, project_id=_PROJECT)
        markdown = render_markdown(report)
        report_seconds = time.perf_counter() - report_started
    if replayed != event_count:
        raise ValueError("perf baseline replay count does not match appends")
    return M2BenchResult(
        event_count=event_count,
        append_seconds=append_seconds,
        replay_seconds=replay_seconds,
        worker_rebuild_seconds=rebuild_seconds,
        report_seconds=report_seconds,
        peak_rss_bytes=max(rss_before, _max_rss_bytes()),
        report_characters=len(markdown),
        lineage_events=len(report.lineage),
    )


def _base_template() -> dict[str, Any]:
    document = snapshot_json_document(load_document(_TEMPLATE))
    document.pop("sequence", None)
    document.pop("sequencetype", None)
    document.pop("streamversion", None)
    document["source"] = _SOURCE
    document["streamid"] = _PROJECT
    document["time"] = "2026-09-07T12:00:00Z"
    data = document["data"]
    if type(data) is not dict:
        raise ValueError("perf baseline template data must be an object")
    data["projectId"] = _PROJECT
    data.pop("runId", None)
    data.pop("attemptId", None)
    return document


def _heartbeat_from(template: dict[str, Any], index: int) -> dict[str, Any]:
    document = snapshot_json_document(template)
    document["id"] = f"evt.perf.heartbeat.{index}"
    document["type"] = "run.heartbeat"
    return document


def _queued_from(template: dict[str, Any], index: int) -> dict[str, Any]:
    document = snapshot_json_document(template)
    document["id"] = f"evt.perf.queued.{index}"
    document["type"] = "run.queued"
    data = document["data"]
    if type(data) is not dict:
        raise ValueError("perf baseline template data must be an object")
    data["runId"] = _RUN
    data["payload"] = {
        "workflowId": "wf.cpu",
        "specDigest": _ZERO,
        "registryDigest": _ONE,
        "planDigest": _TWO,
        "decisionDigest": _THREE,
        "maxAttempts": 1,
    }
    return document


def _max_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(usage)
    return int(usage) * 1024


def _seconds(value: float) -> float:
    return round(value, 3)
