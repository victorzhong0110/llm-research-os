"""Paged replay over EventStore.read_events with frozen high-water marks."""

from __future__ import annotations

from collections.abc import Iterator

from llm_research_os.events.models import CLOUD_EVENTS_INTEGER_MAX
from llm_research_os.storage.errors import EventIntegrityError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore


def replay_events(
    store: EventStore,
    *,
    after_sequence: int = 0,
    page_size: int = 100,
    freeze_high_water: bool = True,
) -> Iterator[StoredEvent]:
    """Yield verified events in global sequence order using bounded pages.

    When ``freeze_high_water`` is true, the current maximum sequence is snapshotted
    before the first yield. Events appended after that snapshot are omitted.
    The iterator never materializes the full store in memory.
    """

    _require_replay_bounds(after_sequence, page_size)
    until_sequence = _snapshot_high_water(store, page_size=page_size) if freeze_high_water else None
    yield from _iter_stored_events(
        store,
        after_sequence=after_sequence,
        page_size=page_size,
        until_sequence=until_sequence,
    )


def _snapshot_high_water(store: EventStore, *, page_size: int) -> int:
    after_sequence = 0
    high_water = 0
    while True:
        page = store.read_events(after_sequence=after_sequence, limit=page_size)
        if not page:
            return high_water
        _require_increasing_page(page, after_sequence=after_sequence)
        high_water = page[-1].sequence
        after_sequence = high_water


def _iter_stored_events(
    store: EventStore,
    *,
    after_sequence: int,
    page_size: int,
    until_sequence: int | None,
) -> Iterator[StoredEvent]:
    expected = after_sequence + 1
    seen_ids: set[str] = set()
    current = after_sequence
    while True:
        if until_sequence is not None and current >= until_sequence:
            return
        page = store.read_events(after_sequence=current, limit=page_size)
        if not page:
            if until_sequence is not None and expected <= until_sequence:
                raise EventIntegrityError(
                    "global event sequence is not contiguous: "
                    f"expected {expected}, found none at or below {until_sequence}"
                )
            return
        for stored in page:
            sequence = stored.sequence
            if until_sequence is not None and sequence > until_sequence:
                if expected <= until_sequence:
                    raise EventIntegrityError(
                        "global event sequence is not contiguous: "
                        f"expected {expected}, found {sequence}"
                    )
                return
            if sequence < expected:
                raise EventIntegrityError(
                    f"global event sequence is out of order: expected {expected}, found {sequence}"
                )
            if sequence > expected:
                raise EventIntegrityError(
                    "global event sequence is not contiguous: "
                    f"expected {expected}, found {sequence}"
                )
            event_id = stored.event.id
            if event_id in seen_ids:
                raise EventIntegrityError(f"duplicate event id during replay: {event_id}")
            seen_ids.add(event_id)
            yield stored
            expected = sequence + 1
            current = sequence


def _require_replay_bounds(after_sequence: int, page_size: int) -> None:
    if isinstance(after_sequence, bool) or not isinstance(after_sequence, int):
        raise ValueError("after_sequence must be an integer")
    if after_sequence < 0 or after_sequence > CLOUD_EVENTS_INTEGER_MAX:
        raise ValueError("after_sequence is outside the supported sequence range")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")


def _require_increasing_page(page: list[StoredEvent], *, after_sequence: int) -> None:
    expected = after_sequence + 1
    for stored in page:
        if stored.sequence < expected:
            raise EventIntegrityError(
                "global event sequence is out of order: "
                f"expected at least {expected}, found {stored.sequence}"
            )
        expected = stored.sequence + 1
