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
from dataclasses import dataclass
from typing import Any

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN
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


def encode_cursor(sequence: int) -> str:
    """Opaque cursor. The value is a last-seen sequence, not a client-chosen offset."""

    raw = f"{_CURSOR_PREFIX}{sequence}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    """Decode one opaque cursor, refusing anything that is not one we issued."""

    if cursor is None or cursor == "":
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.") from exc
    if not raw.startswith(_CURSOR_PREFIX):
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    tail = raw[len(_CURSOR_PREFIX) :]
    if not tail.isdigit():
        raise bad_request("parameter-invalid", "The cursor is not a valid page token.")
    return int(tail)


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
        except (EventStoreError, ArtifactNotFoundError, ArtifactStoreError, OSError) as exc:
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

    def event_page(
        self,
        *,
        cursor: str | None,
        limit: int | None = None,
        event_types: frozenset[str] | None = None,
    ) -> Page:
        """One bounded project-scoped event page with a frozen high-water mark."""

        after = decode_cursor(cursor)
        size = limit if limit is not None else parse_limit(None)
        high_water = self._guarded(self._store.last_sequence)
        rows = self._events(after_sequence=after, limit=size)
        if event_types is not None:
            rows = [row for row in rows if str(row.event.type) in event_types]
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
            next_cursor=encode_cursor(last) if len(rows) == size else None,
            high_water_mark=high_water,
        )

    def revision_page(self, *, cursor: str | None, limit: int | None = None) -> Page:
        after = decode_cursor(cursor)
        size = limit if limit is not None else parse_limit(None)
        high_water = self._guarded(self._store.last_sequence)
        rows = self._guarded(self._store.list_spec_revisions)
        scoped = [row for row in rows if row.project_id == self._project_id]
        selected = [row for row in scoped if row.first_seen_sequence > after][:size]
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
            next_cursor=encode_cursor(last) if len(selected) == size else None,
            high_water_mark=high_water,
        )

    def run_page(self, *, cursor: str | None, limit: int | None = None) -> Page:
        """Bounded run index derived from verified Run facts, newest first.

        The observation state comes from the authoritative ``RunControl`` fold,
        not from guessing at event type names. A run with no snapshot stays
        ``absent``; the view then says so instead of implying a lifecycle.

        The fold is scanned once against the frozen high-water mark, so a page
        is bounded in the response but the derivation cost is the project run
        count. The cursor resumes strictly below the last returned sequence.
        """

        after = decode_cursor(cursor)
        size = limit if limit is not None else parse_limit(None)
        high_water = self._guarded(self._store.last_sequence)
        rows = self._events(after_sequence=0, limit=high_water or 1)
        latest: dict[str, dict[str, Any]] = {}
        queued: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.event.data.project_id != self._project_id or row.event.data.run_id is None:
                continue
            run_id = str(row.event.data.run_id)
            if str(row.event.type) == "run.queued":
                queued.setdefault(run_id, dict(row.event.data.payload))
            entry = latest.get(run_id)
            if entry is not None and row.sequence <= int(entry["lastSequence"]):
                continue
            latest[run_id] = {
                "runId": run_id,
                "lastSequence": row.sequence,
                "lastEventType": str(row.event.type),
                "attemptId": None
                if row.event.data.attempt_id is None
                else str(row.event.data.attempt_id),
            }
        for run_id, entry in latest.items():
            entry["observation"] = self._observation(run_id)
            entry["origin"] = self._origin(queued.get(run_id))
        ordered = sorted(latest.values(), key=lambda item: int(item["lastSequence"]), reverse=True)
        # The index is newest-first, so a cursor means "strictly older than this".
        remaining = [item for item in ordered if after == 0 or int(item["lastSequence"]) < after]
        selected = remaining[:size]
        return Page(
            items=tuple(
                {
                    "runId": item["runId"],
                    "lastSequence": item["lastSequence"],
                    "lastEventType": item["lastEventType"],
                    "attemptId": item["attemptId"],
                    "observation": item["observation"],
                    "origin": item["origin"],
                }
                for item in selected
            ),
            next_cursor=encode_cursor(int(selected[-1]["lastSequence"])) if selected else None,
            high_water_mark=high_water,
        )

    def _observation(self, run_id: str) -> str:
        """Fold one Run and map its status to the closed observation set.

        ``cancelled`` and ``lost`` are kept apart on purpose: a recorded
        cancellation request is not an observed process stop, and a lost result
        is neither success nor failure.
        """

        from llm_research_os.runs.control import RunControl
        from llm_research_os.runs.errors import RunStateError
        from llm_research_os.runs.models import RunStatus

        try:
            head = RunControl(self._store, project_id=self._project_id, run_id=run_id).rebuild()
        except RunStateError:
            # A lifecycle the fold refuses proves no state. Claiming `absent` is
            # honest; inventing a status from raw event names would not be.
            return "absent"
        snapshot = head.snapshot
        if snapshot is None:
            return "absent"
        mapping = {
            RunStatus.QUEUED: "queued",
            RunStatus.RUNNING: "running",
            RunStatus.RETRY_PENDING: "running",
            RunStatus.LOST: "lost",
            RunStatus.UNKNOWN: "unknown",
            RunStatus.COMPLETED: "succeeded",
            RunStatus.FAILED: "failed",
            RunStatus.CANCELLED: "observed-stop",
        }
        return mapping.get(snapshot.status, "absent")

    def _origin(self, queued: dict[str, Any] | None) -> str:
        """Label a run's data provenance from the authorization it actually cites.

        The signal is a recorded fact, not a naming convention: the run's
        ``run.queued`` fact cites an authorization event, and that event states
        its own ``authority`` and ``execution``. A run authorized only for audit
        is synthetic. Anything else is reported ``absent`` rather than
        ``real``: claiming a measurement the workbench cannot source is the
        misleading direction, and R10 requires synthetic, absent and real to stay
        distinguishable.
        """

        if queued is None:
            return "absent"
        # CloudEvents carries sequence fields as decimal strings; accept both
        # forms rather than assuming one and silently reporting "absent".
        raw = queued.get("authorizationSequence")
        if isinstance(raw, int) and not isinstance(raw, bool):
            sequence = raw
        elif isinstance(raw, str) and raw.isdigit():
            sequence = int(raw)
        else:
            return "absent"
        if sequence < 1:
            return "absent"
        events = self._events(after_sequence=sequence - 1, limit=1)
        if not events:
            return "absent"
        payload = events[0].event.data.payload
        authority = payload.get("authority")
        execution = payload.get("execution")
        if authority == "audit-only" or execution == "not-executed":
            return "synthetic"
        return "absent"

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
