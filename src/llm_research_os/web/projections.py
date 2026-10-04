"""Bounded, project-scoped read projections for the local API.

TM-082. Every view here is a bounded page with a frozen high-water mark, so a
browser can poll or resume without a full-store scan and without a second
project's data. Nothing in this module appends a fact, mints authority, or
exposes a host path: projections are derived from the same verified folds the
CLI already uses.
"""

from __future__ import annotations

import base64
import binascii
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN
from llm_research_os.events.models import CLOUD_EVENTS_INTEGER_MAX
from llm_research_os.storage import EventStore
from llm_research_os.storage.errors import EventStoreError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.web.errors import LocalApiError, bad_request, not_found

DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500
MAX_ARTIFACT_INLINE_BYTES = 262_144
_CURSOR_PREFIX = "seq:"


@dataclass(frozen=True)
class Page:
    """One bounded page plus the high-water mark it was frozen against."""

    items: tuple[dict[str, Any], ...]
    next_cursor: str | None
    high_water_mark: int

    def document(self, kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "items": list(self.items),
            "nextCursor": self.next_cursor,
            "highWaterMark": self.high_water_mark,
        }


def encode_cursor(sequence: int, *, high_water: int | None = None, scope: str = "") -> str:
    """Opaque cursor. The value is a last-seen sequence, not a client-chosen offset."""

    value = f"{sequence}" if high_water is None else f"{sequence}:{high_water}:{scope}"
    raw = f"{_CURSOR_PREFIX}{value}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    """Decode one opaque cursor, refusing anything that is not one we issued."""

    if cursor is None or cursor == "":
        return 0
    if len(cursor) > 2048:
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.") from exc
    if not raw.startswith(_CURSOR_PREFIX):
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    tail = raw[len(_CURSOR_PREFIX) :].split(":", 2)[0]
    if not tail.isascii() or not tail.isdigit() or len(tail) > 16:
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    value = int(tail)
    if value > CLOUD_EVENTS_INTEGER_MAX:
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    return value


def parse_limit(raw: str | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_PAGE_LIMIT
    if not raw.isdigit():
        raise bad_request("parameter-invalid", "limit must be a positive integer.")
    value = int(raw)
    if not 1 <= value <= MAX_PAGE_LIMIT:
        raise bad_request("parameter-invalid", f"limit must be in 1..{MAX_PAGE_LIMIT}.")
    return value


def require_digest(raw: str) -> str:
    if re.fullmatch(SEMANTIC_DIGEST_PATTERN, raw) is None:
        raise bad_request("parameter-invalid", "The artifact digest is not canonical.")
    return raw


class ReadProjections:
    """Read-only views over one project's EventStore and CAS."""

    def __init__(self, store: EventStore, artifacts: LocalArtifactStore, project_id: str) -> None:
        self._store = store
        self._artifacts = artifacts
        self._project_id = project_id

    @property
    def project_id(self) -> str:
        return self._project_id

    def _guarded(self, action: Any, *args: Any, **kwargs: Any) -> Any:
        """Run one store or CAS call, converting an IO fault to a safe 503."""

        try:
            return action(*args, **kwargs)
        except (
            EventStoreError,
            ArtifactNotFoundError,
            ArtifactStoreError,
            OSError,
            sqlite3.Error,
        ) as exc:
            raise LocalApiError(
                "event-store-unavailable",
                "The control store could not answer this read.",
                status=503,
            ) from exc

    def _events(self, *, after_sequence: int, limit: int) -> list[StoredEvent]:
        rows: list[StoredEvent] = self._guarded(
            self._store.read_events, after_sequence=after_sequence, limit=limit
        )
        return rows

    def _bounds(self, cursor: str | None, scope: str) -> tuple[int, int]:
        after = decode_cursor(cursor)
        live = self._guarded(self._store.last_sequence)
        if cursor:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            parts = raw[len(_CURSOR_PREFIX) :].split(":", 2)
            if len(parts) > 1:
                if (
                    len(parts) != 3
                    or parts[2] != scope
                    or not parts[1].isascii()
                    or not parts[1].isdigit()
                    or len(parts[1]) > 16
                ):
                    raise bad_request("parameter-invalid", "The cursor scope is not valid.")
                high_water = int(parts[1])
                if high_water > live or after > high_water:
                    raise bad_request("parameter-invalid", "The cursor snapshot is not available.")
                return after, high_water
        return after, live

    def event_page(
        self,
        *,
        cursor: str | None,
        limit: int | None = None,
        event_types: frozenset[str] | None = None,
    ) -> Page:
        """One bounded project-scoped event page with a frozen high-water mark."""

        scope = self._project_id + "|events|" + ",".join(sorted(event_types or ()))
        after, high_water = self._bounds(cursor, scope)
        size = limit if limit is not None else parse_limit(None)
        rows = self._guarded(
            self._store.read_events,
            after_sequence=after,
            limit=size,
            until_sequence=high_water,
            event_types=event_types,
            project_id=self._project_id,
        )
        items = [
            {
                "sequence": row.sequence,
                "eventId": str(row.event.id),
                "type": str(row.event.type),
                "occurredAt": str(row.event.time),
                "projectId": str(row.event.data.project_id),
                "runId": None if row.event.data.run_id is None else str(row.event.data.run_id),
                "attemptId": None
                if row.event.data.attempt_id is None
                else str(row.event.data.attempt_id),
            }
            for row in rows
            if row.event.data.project_id == self._project_id
        ]
        last = rows[-1].sequence if rows else after
        return Page(
            items=tuple(items),
            next_cursor=encode_cursor(last, high_water=high_water, scope=scope)
            if len(rows) == size
            else None,
            high_water_mark=high_water,
        )

    def revision_page(self, *, cursor: str | None, limit: int | None = None) -> Page:
        scope = self._project_id + "|revisions"
        after, high_water = self._bounds(cursor, scope)
        size = limit if limit is not None else parse_limit(None)
        selected = self._guarded(
            self._store.list_spec_revisions_page,
            self._project_id,
            after=after,
            until=high_water,
            limit=size,
        )
        items = [
            {
                "revision": row.revision,
                "specDigest": row.spec_digest,
                "firstSeenSequence": row.first_seen_sequence,
            }
            for row in selected
        ]
        last = selected[-1].first_seen_sequence if selected else after
        return Page(
            items=tuple(items),
            next_cursor=encode_cursor(last, high_water=high_water, scope=scope)
            if len(selected) == size
            else None,
            high_water_mark=high_water,
        )

    def run_page(self, *, cursor: str | None, limit: int | None = None) -> Page:
        """Bounded run index derived from verified Run facts, newest first.

        SQL selects only the requested heads against the frozen high-water mark,
        then verifies each selected fact. The query budget bounds index work.
        The cursor resumes strictly below the last returned sequence.
        """

        scope = self._project_id + "|runs"
        after, high_water = self._bounds(cursor, scope)
        size = limit if limit is not None else parse_limit(None)
        rows = self._guarded(
            self._store.list_run_heads_page,
            self._project_id,
            before=after,
            until=high_water,
            limit=size,
        )
        items = tuple(
            {
                "runId": str(row.event.data.run_id),
                "lastSequence": row.sequence,
                "lastEventType": str(row.event.type),
                "attemptId": None
                if row.event.data.attempt_id is None
                else str(row.event.data.attempt_id),
            }
            for row in rows
        )
        return Page(
            items=items,
            next_cursor=encode_cursor(rows[-1].sequence, high_water=high_water, scope=scope)
            if len(rows) == size
            else None,
            high_water_mark=high_water,
        )

    def resolve_artifact_project(self, digest: str, *, link_limit: int = 200) -> bool:
        """True when at least one verified event of this project references ``digest``.

        The artifact index is global, so scope is proven from linked events
        rather than assumed from the first-seen sequence.
        """

        after = 0
        while True:
            links = self._guarded(
                self._store.list_artifact_links_page,
                digest,
                after_sequence=after,
                limit=link_limit,
            )
            if not links:
                return False
            for link in links:
                events = self._events(after_sequence=link.event_sequence - 1, limit=1)
                if events and events[0].event.data.project_id == self._project_id:
                    return True
            after = links[-1].event_sequence
            if len(links) < link_limit:
                return False

    def artifact_document(self, digest: str) -> dict[str, Any]:
        """Bounded artifact view. Bytes are inlined only below the inline cap."""

        canonical = require_digest(digest)
        if not self.resolve_artifact_project(canonical):
            raise not_found("The artifact is not referenced by this project.")
        try:
            record = self._guarded(self._artifacts.verify, canonical)
        except LocalApiError as exc:
            if exc.code == "event-store-unavailable":
                raise not_found("The artifact object is not present in the CAS.") from exc
            raise
        document: dict[str, Any] = {
            "digest": canonical,
            "byteLength": record.size_bytes,
            "inline": record.size_bytes <= MAX_ARTIFACT_INLINE_BYTES,
        }
        if document["inline"] is True:
            try:
                with self._artifacts.open(canonical) as stream:
                    payload = stream.read(MAX_ARTIFACT_INLINE_BYTES + 1)
            except (ArtifactNotFoundError, ArtifactStoreError, OSError) as exc:
                raise not_found("The artifact object is not present in the CAS.") from exc
            try:
                document["text"] = payload.decode("utf-8")
            except UnicodeError:
                document["inline"] = False
        return document
