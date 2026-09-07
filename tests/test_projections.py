from __future__ import annotations

import sqlite3
import types
from collections.abc import Iterator
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


class _FakeStoredEvent:
    def __init__(self, sequence: int) -> None:
        self.sequence = sequence
        self.event = type("Event", (), {"id": f"evt.{sequence}"})()


class _NeverEmptyStore:
    def __init__(self) -> None:
        self.read_calls = 0

    def verify_integrity(self) -> int:
        return 3

    def freeze_high_water(self) -> int:
        return self.verify_integrity()

    def read_events(self, *, after_sequence: int = 0, limit: int = 100) -> list[_FakeStoredEvent]:
        self.read_calls += 1
        if self.read_calls > 8:
            raise AssertionError("replay paged until empty instead of freezing high water")
        return [_FakeStoredEvent(after_sequence + offset) for offset in range(1, limit + 1)]


def test_replay_freezes_high_water_without_waiting_for_an_empty_page() -> None:
    store = _NeverEmptyStore()
    events = list(replay_events(store, page_size=2))  # type: ignore[arg-type]
    assert [item.sequence for item in events] == [1, 2, 3]
    assert store.read_calls <= 2


def test_replay_rejects_gaps_before_yielding(tmp_path: Path) -> None:
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

    yielded: list[int] = []
    with EventStore(database) as store, pytest.raises(EventIntegrityError, match="not contiguous"):
        yielded.append(next(iter(replay_events(store, page_size=1))).sequence)
    assert yielded == []


def _retained_collection_lengths(iterator: object) -> dict[str, int]:
    lengths: dict[str, int] = {}
    current: object | None = iterator
    depth = 0
    while isinstance(current, types.GeneratorType):
        frame = current.gi_frame
        assert frame is not None
        for name, value in frame.f_locals.items():
            if isinstance(value, (set, dict, list)):
                lengths[f"{depth}:{name}"] = len(value)
        nested = current.gi_yieldfrom
        current = nested if isinstance(nested, types.GeneratorType) else None
        depth += 1
    return lengths


def test_retained_collection_lengths_observes_inner_seen_ids() -> None:
    def inner() -> Iterator[int]:
        seen_ids: set[str] = set()
        page = ["item"]
        for index in range(1, 5):
            seen_ids.add(str(index))
            yield index
            assert page == ["item"]

    def outer() -> Iterator[int]:
        yield from inner()

    generated = outer()
    assert next(generated) == 1
    first = _retained_collection_lengths(generated)
    assert first["1:seen_ids"] == 1
    assert first["1:page"] == 1
    for _ in range(3):
        next(generated)
    last = _retained_collection_lengths(generated)
    assert last["1:seen_ids"] == 4
    assert last["1:page"] == 1


def test_replay_pager_state_does_not_grow_with_history(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    history = 40
    page_size = 1
    with EventStore(database) as store:
        for index in range(1, history + 1):
            store.append(_event_draft(index))
        replayed = replay_events(store, page_size=page_size)
        samples: list[dict[str, int]] = []
        seen = 0
        for _item in replayed:
            seen += 1
            if seen in {1, 10, 20, 40}:
                samples.append(_retained_collection_lengths(replayed))

    assert seen == history
    assert len(samples) == 4
    for sample in samples:
        assert any(name.startswith("1:") for name in sample), sample
        assert not any(name.split(":", 1)[1] == "seen_ids" for name in sample)
        page_lengths = [length for name, length in sample.items() if name.endswith(":page")]
        assert page_lengths
        assert all(length <= page_size for length in page_lengths)
        assert all(length <= page_size for length in sample.values())
    assert samples[0] == samples[1] == samples[2] == samples[3]


class OptionalFlagProjection:
    def initial_state(self) -> bool | None:
        return False

    def apply(self, state: bool | None, event: ResearchEvent) -> bool | None:
        if event.type == "run.started":
            return True
        if event.type == "run.completed":
            return None
        return state


class NoneProjection:
    def initial_state(self) -> None:
        return None

    def apply(self, state: None, event: ResearchEvent) -> None:
        return None


def test_fold_resumes_from_explicit_none_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    projection = OptionalFlagProjection()
    with EventStore(database) as store:
        store.append(_event_draft(1, event_type="run.started"))
        store.append(_event_draft(2, event_type="run.heartbeat"))
        store.append(_event_draft(3, event_type="run.completed"))
        store.append(_event_draft(4, event_type="run.heartbeat"))
        events = [item.event for item in replay_events(store, page_size=2)]

    assert fold_events(events, projection) is None
    checkpoint = fold_events(events[:3], projection)
    assert checkpoint is None
    assert fold_events(events[3:], projection, resume=None) is None
    assert fold_events(events[3:], projection) is False
    assert fold_events(events, NoneProjection(), resume=None) is None
