from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.events.models import ResearchEvent
from llm_research_os.projections import fold_events, replay_events
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventIntegrityError, EventStore
from llm_research_os.storage.schema import MIGRATION_STATEMENTS

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


class EventTypeCounter:
    def initial_state(self) -> dict[str, int]:
        return {}

    def apply(self, state: dict[str, int], event: ResearchEvent) -> dict[str, int]:
        next_state = dict(state)
        next_state[event.type] = next_state.get(event.type, 0) + 1
        return next_state


def _event_draft(index: int = 1, *, event_type: str = "run.started") -> dict[str, Any]:
    document = load_document(EXAMPLES / "valid" / "minimal.json")
    document.pop("sequence")
    document.pop("sequencetype")
    document.pop("streamversion")
    document["id"] = f"evt.store.{index}"
    document["type"] = event_type
    document["streamid"] = "project.example"
    document["time"] = f"2026-08-28T06:00:{index % 60:02d}Z"
    data = document["data"]
    assert isinstance(data, dict)
    data["projectId"] = "project.example"
    return document


def test_replay_pages_without_duplicates_and_freezes_high_water(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        for index in range(1, 4):
            store.append(_event_draft(index))
        replayed = replay_events(store, page_size=1)
        first = next(replayed)
        store.append(_event_draft(4, event_type="run.heartbeat"))
        rest = list(replayed)

    assert first.sequence == 1
    assert [item.sequence for item in rest] == [2, 3]
    assert [item.event.id for item in (first, *rest)] == [
        "evt.store.1",
        "evt.store.2",
        "evt.store.3",
    ]


def test_full_rebuild_matches_segmented_continue(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    projection = EventTypeCounter()
    with EventStore(database) as store:
        store.append(_event_draft(1, event_type="run.started"))
        store.append(_event_draft(2, event_type="run.heartbeat"))
        store.append(_event_draft(3, event_type="run.started"))
        store.append(_event_draft(4, event_type="run.completed"))
        events = [item.event for item in replay_events(store, page_size=2)]
        full = fold_events(events, projection)
        checkpoint = fold_events(events[:2], projection)
        continued = fold_events(events[2:], projection, resume=checkpoint)
        resumed = fold_events(
            (item.event for item in replay_events(store, after_sequence=2, page_size=1)),
            projection,
            resume=checkpoint,
        )

    assert full == {"run.started": 2, "run.heartbeat": 1, "run.completed": 1}
    assert continued == full
    assert resumed == full


def test_replay_rejects_sequence_gaps(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.append(_event_draft(1))
        store.append(_event_draft(2))

    def trigger(name: str) -> str:
        marker = f"CREATE TRIGGER {name}"
        return next(statement for statement in MIGRATION_STATEMENTS if marker in statement)

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.execute(trigger("events_reject_delete"))

    with EventStore(database) as store, pytest.raises(EventIntegrityError, match="not contiguous"):
        list(replay_events(store, page_size=1))
