"""Atomic RunControl boundary over EventStore and RunStateProjection.

EventStore remains the only fact source. RunSnapshot is a rebuildable
projection: an in-memory fold, optionally cached in SQLite and discarded when
the cache disagrees with the verified event prefix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from llm_research_os.canonical import legacy_canonical_json, legacy_content_digest
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import LIFECYCLE_TYPES, RunSnapshot, run_snapshot_document
from llm_research_os.runs.reducer import RunStateProjection
from llm_research_os.storage.models import RunProjectionRecord, StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class RunControlHead:
    """Frozen global event head plus the rebuilt snapshot for one Run."""

    last_sequence: int
    snapshot: RunSnapshot | None


@dataclass(frozen=True, slots=True)
class RunControlResult:
    """One CAS-committed event and the snapshot produced from that fact."""

    stored: StoredEvent
    snapshot: RunSnapshot


class RunControl:
    """Validate a lifecycle draft against a frozen replay, then CAS-append it.

    ``last_sequence`` is the global EventStore head used as the CAS token. It is
    not a per-Run event count and is not ``streamversion``. Conflicts are not
    retried; the caller must invoke ``append`` again so replay and preflight run
    against the new head. Cached Run rows are discarded when they fail
    canonical JSON, digest, or snapshot validation.
    """

    def __init__(
        self,
        store: EventStore,
        *,
        project_id: str,
        run_id: str,
        page_size: int = 100,
    ) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._projection = RunStateProjection(project_id=project_id, run_id=run_id)
        self._project_id = self._projection.project_id
        self._run_id = self._projection.run_id

    def rebuild(self) -> RunControlHead:
        """Replay the frozen global log and fold only this Run's events."""

        high_water = self._store.freeze_high_water()
        snapshot, after_sequence = self._cached_snapshot(high_water)
        for stored in replay_events(
            self._store,
            after_sequence=after_sequence,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            snapshot = self._projection.apply(snapshot, stored.event)
        self._persist_projection(high_water, snapshot)
        return RunControlHead(last_sequence=high_water, snapshot=snapshot)

    def append(self, document: dict[str, Any]) -> RunControlResult:
        """Preflight one lifecycle draft, then append it at the frozen head."""

        head = self.rebuild()
        frozen_head = head.last_sequence
        snapshot = head.snapshot
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise RunControlError(str(exc)) from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise RunControlError(
                f"RunControl does not accept store-assigned fields; caller supplied: {supplied}"
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise RunControlError("global event sequence is exhausted")
        preflight_document = dict(draft)
        preflight_document.update(
            {
                "sequence": str(frozen_head + 1),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        preflight_event = _validate_preflight_event(preflight_document)
        _require_matching_aggregate(preflight_event, self._project_id, self._run_id)
        if preflight_event.type not in LIFECYCLE_TYPES:
            raise RunControlError("event type is not a Run/Attempt lifecycle type")
        preflight_snapshot = self._projection.apply(snapshot, preflight_event)
        if preflight_snapshot is None:
            raise RunControlError("lifecycle preflight produced no snapshot")
        stored = self._store.append(draft, expected_last_sequence=frozen_head)
        committed_snapshot = self._projection.apply(snapshot, stored.event)
        if committed_snapshot is None:
            raise RunControlError("committed lifecycle event produced no snapshot")
        self._persist_projection(stored.sequence, committed_snapshot)
        return RunControlResult(stored=stored, snapshot=committed_snapshot)

    def _cached_snapshot(self, high_water: int) -> tuple[RunSnapshot | None, int]:
        if high_water == 0:
            return None, 0
        cached = self._store.get_run_projection(self._project_id, self._run_id)
        if cached is None or cached.last_sequence > high_water or cached.last_sequence < 1:
            return None, 0
        try:
            snapshot = _require_cached_snapshot(cached)
        except (ValueError, ValidationError):
            return None, 0
        return snapshot, cached.last_sequence

    def _persist_projection(self, last_sequence: int, snapshot: RunSnapshot | None) -> None:
        if not self._store.writable:
            return
        if last_sequence == 0:
            self._store.delete_run_projection(self._project_id, self._run_id)
            return
        if snapshot is None:
            record = RunProjectionRecord(
                project_id=self._project_id,
                run_id=self._run_id,
                last_sequence=last_sequence,
                snapshot_json=None,
                snapshot_digest=None,
            )
        else:
            payload = run_snapshot_document(snapshot)
            record = RunProjectionRecord(
                project_id=self._project_id,
                run_id=self._run_id,
                last_sequence=last_sequence,
                snapshot_json=legacy_canonical_json(payload),
                snapshot_digest=legacy_content_digest(payload),
            )
        self._store.upsert_run_projection(record)


def _require_page_size(page_size: int) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")
    return page_size


def _require_matching_aggregate(event: ResearchEvent, project_id: str, run_id: str) -> None:
    if event.data.project_id != project_id or event.data.run_id != run_id:
        raise RunControlError("event projectId/runId does not match this RunControl")


def _validate_preflight_event(document: dict[str, Any]) -> ResearchEvent:
    try:
        validated = validate_event_document(document)
    except ValidationError:
        payload_error = RunControlError("event draft failed ResearchEvent validation")
    else:
        return validated
    raise payload_error


def _require_cached_snapshot(cached: RunProjectionRecord) -> RunSnapshot | None:
    """Decode a cached snapshot or raise ``ValueError`` if the row is not canonical."""

    if cached.snapshot_json is None:
        if cached.snapshot_digest is not None:
            raise ValueError("run projection digest is present without snapshot JSON")
        return None
    if cached.snapshot_digest is None:
        raise ValueError("run projection JSON is present without a digest")
    decoded: object = json.loads(cached.snapshot_json)
    if type(decoded) is not dict:
        raise ValueError("run projection JSON root is not an object")
    document = decoded
    if legacy_canonical_json(document) != cached.snapshot_json:
        raise ValueError("run projection JSON is not canonical")
    if legacy_content_digest(document) != cached.snapshot_digest:
        raise ValueError("run projection digest mismatch")
    return RunSnapshot.model_validate(document)
