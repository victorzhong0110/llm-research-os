from __future__ import annotations

from pathlib import Path

from research_os.models.research_spec import ResearchSpec, SpecMetadata
from research_os.runtime import Outcome, SimulatedRuntime
from research_os.store import EventStore


def _spec() -> ResearchSpec:
    return ResearchSpec(metadata=SpecMetadata(id="demo-proj", revision=1, title="Demo"))


def test_completed_run_emits_terminal_completed(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = SimulatedRuntime(store).run(_spec(), steps=3, outcome=Outcome.COMPLETE)

    types = [e.type for e in store.read(run_id=run_id)]
    assert types[0] == "dev.researchos.run.queued"
    assert types.count("dev.researchos.train.step") == 3
    assert types[-1] == "dev.researchos.run.completed"
    assert store.run_status(run_id) == "completed"


def test_failed_run(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = SimulatedRuntime(store).run(_spec(), steps=2, outcome=Outcome.FAIL)
    assert store.run_status(run_id) == "failed"


def test_cancelled_run(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = SimulatedRuntime(store).run(_spec(), steps=2, outcome=Outcome.CANCEL)
    assert store.run_status(run_id) == "cancelled"


def test_events_are_cloudevents_compatible(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = SimulatedRuntime(store).run(_spec(), steps=1)
    event = next(iter(store.read(run_id=run_id)))
    ce = event.to_cloudevent()
    assert ce["specversion"] == "1.0"
    assert ce["subject"] == f"demo-proj/{run_id}"
    assert ce["type"].startswith("dev.researchos.")
