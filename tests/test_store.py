from __future__ import annotations

from pathlib import Path

from research_os.models.research_event import ResearchEvent
from research_os.store import EventStore


def _event(project: str, run: str, type_suffix: str) -> ResearchEvent:
    return ResearchEvent(
        source="test",
        type=f"dev.researchos.{type_suffix}",
        projectId=project,
        runId=run,
    )


def test_append_and_read_ordered(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    store.append(_event("p1", "r1", "run.started"))
    store.append(_event("p1", "r1", "train.step"))
    store.append(_event("p1", "r1", "run.completed"))

    events = list(store.read(run_id="r1"))
    assert [e.type for e in events] == [
        "dev.researchos.run.started",
        "dev.researchos.train.step",
        "dev.researchos.run.completed",
    ]
    assert store.count() == 3


def test_read_filters_by_scope(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    store.append(_event("p1", "r1", "run.started"))
    store.append(_event("p2", "r2", "run.started"))

    assert len(list(store.read(project_id="p1"))) == 1
    assert len(list(store.read(run_id="r2"))) == 1
    assert len(list(store.read())) == 2


def test_run_status_projection(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    assert store.run_status("missing") == "unknown"

    store.append(_event("p1", "r1", "run.started"))
    assert store.run_status("r1") == "running"

    store.append(_event("p1", "r1", "run.completed"))
    assert store.run_status("r1") == "completed"
