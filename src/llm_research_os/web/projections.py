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
import hashlib
import os
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

    value = (
        f"{sequence}"
        if high_water is None
        else f"{sequence}:{high_water}:{hashlib.sha256(scope.encode()).hexdigest()}"
    )
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
    if not raw.isascii() or not raw.isdigit() or len(raw) > 16:
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
                    or parts[2] not in {scope, hashlib.sha256(scope.encode()).hexdigest()}
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
        run_id: str | None = None,
    ) -> Page:
        """One bounded project-scoped event page with a frozen high-water mark."""

        scope = (
            self._project_id
            + "|events|"
            + ",".join(sorted(event_types or ()))
            + "|"
            + (run_id or "")
        )
        after, high_water = self._bounds(cursor, scope)
        size = limit if limit is not None else parse_limit(None)
        rows = self._guarded(
            self._store.read_events,
            after_sequence=after,
            limit=size,
            until_sequence=high_water,
            event_types=event_types,
            run_id=run_id,
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
                "observation": self._observation(str(row.event.data.run_id), high_water),
                "origin": self._run_origin(str(row.event.data.run_id), high_water),
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

    def _run_origin(self, run_id: str, high_water: int) -> str:
        rows = self._guarded(
            self._store.read_events,
            project_id=self._project_id,
            run_id=run_id,
            event_types=frozenset({"run.queued"}),
            until_sequence=high_water,
            limit=1,
        )
        return self._origin(dict(rows[0].event.data.payload) if rows else None)

    def _observation(self, run_id: str, high_water: int) -> str:
        """Fold one Run and map its status to the closed observation set.

        ``cancelled`` and ``lost`` are kept apart on purpose: a recorded
        cancellation request is not an observed process stop, and a lost result
        is neither success nor failure.
        """

        from llm_research_os.runs.errors import RunStateError
        from llm_research_os.runs.models import RunStatus
        from llm_research_os.runs.reducer import RunStateProjection

        try:
            projection = RunStateProjection(self._project_id, run_id)
            snapshot = None
            after = 0
            while True:
                rows = self._guarded(
                    self._store.read_events,
                    after_sequence=after,
                    limit=500,
                    until_sequence=high_water,
                    project_id=self._project_id,
                    run_id=run_id,
                )
                for row in rows:
                    snapshot = projection.apply(snapshot, row.event)
                if len(rows) < 500:
                    break
                after = rows[-1].sequence
        except RunStateError:
            # A lifecycle the fold refuses proves no state. Claiming `absent` is
            # honest; inventing a status from raw event names would not be.
            return "absent"
        if snapshot is None:
            return "absent"
        if snapshot.cancellation_requested and snapshot.status not in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return "cancel-requested"
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
        if not events or events[0].event.data.project_id != self._project_id:
            return "absent"
        payload = events[0].event.data.payload
        authority = payload.get("authority")
        execution = payload.get("execution")
        if authority == "audit-only" or execution == "not-executed":
            return "synthetic"
        return "absent"

    def event_document(self, identity: str) -> dict[str, Any]:
        from llm_research_os.web.inspection import references, safe_document

        if not identity or len(identity) > 255:
            raise bad_request("parameter-invalid", "The event identity is invalid.")
        if identity.isascii() and identity.isdigit():
            sequence = int(identity)
            if not 1 <= sequence <= CLOUD_EVENTS_INTEGER_MAX:
                raise bad_request("parameter-invalid", "The event sequence is invalid.")
            rows = self._guarded(
                self._store.read_events,
                after_sequence=sequence - 1,
                until_sequence=sequence,
                project_id=self._project_id,
                limit=1,
            )
        else:
            rows = self._guarded(
                self._store.read_events,
                project_id=self._project_id,
                event_id=identity,
                limit=1,
            )
        if not rows:
            raise not_found("No such project event.")
        row = rows[0]
        document = row.event.model_dump(mode="json", by_alias=True)
        return {
            "identity": str(row.event.id),
            "document": safe_document(document),
            "links": references(safe_document(document)),
            "immutable": True,
        }

    def revision_document(self, digest: str) -> dict[str, Any]:
        canonical = require_digest(digest)
        if not self.resolve_artifact_project(canonical):
            raise not_found("No such project revision reference.")
        rows = self._guarded(
            self._store.read_artifact_reference_events, self._project_id, canonical
        )
        facts = [
            {"kind": "event", "target": str(row.sequence), "label": "recorded reference"}
            for row in rows
        ]
        return {
            "identity": canonical,
            "document": {"specDigest": canonical},
            "links": facts,
            "immutable": True,
        }

    def artifact_inspection(self, digest: str, via: tuple[str, ...] = ()) -> dict[str, Any]:
        from llm_research_os.web.inspection import inspected_text

        artifact = self.artifact_document(digest, via=via)
        details: dict[str, Any] = (
            inspected_text(artifact["text"])
            if "text" in artifact
            else {
                "content": "Object exceeds inline limit or is binary",
                "links": [],
                "graph": {"source": "unsupported", "graphs": []},
            }
        )
        for link in details["links"]:
            if link["kind"] == "artifact":
                link["via"] = [*via, digest]
        return {
            "identity": digest,
            "document": {**{k: v for k, v in artifact.items() if k != "text"}, **details},
            "links": details["links"],
            "immutable": True,
        }

    def resolve_artifact_project(self, digest: str, *, link_limit: int = 200) -> bool:
        """True when at least one verified event of this project references ``digest``.

        The artifact index is global, so scope is proven from linked events
        rather than assumed from the first-seen sequence.
        """

        return bool(
            self._guarded(
                self._store.read_artifact_reference_events,
                self._project_id,
                digest,
                limit=1,
            )
        )

    def artifact_document(self, digest: str, *, via: tuple[str, ...] = ()) -> dict[str, Any]:
        """Bounded artifact view. Bytes are inlined only below the inline cap."""

        canonical = require_digest(digest)
        if via:
            from llm_research_os.web.inspection import inspected_text

            if len(via) > 8 or len(set(via)) != len(via) or canonical in via:
                raise bad_request("parameter-invalid", "The artifact lineage path is not bounded.")
            if not self.resolve_artifact_project(require_digest(via[0])):
                raise not_found("The lineage root is not referenced by this project.")
            for index, ancestor in enumerate(via):
                document = self._read_artifact_document(require_digest(ancestor))
                if not document.get("inline") or "text" not in document:
                    raise not_found("The lineage object cannot be inspected within the byte limit.")
                refs = inspected_text(document["text"])["links"]
                child = via[index + 1] if index + 1 < len(via) else canonical
                if not any(link["kind"] == "artifact" and link["target"] == child for link in refs):
                    raise not_found("The artifact is not a recorded lineage reference.")
        elif not self.resolve_artifact_project(canonical):
            raise not_found("The artifact is not referenced by this project.")
        return self._read_artifact_document(canonical)

    def _read_artifact_document(self, canonical: str) -> dict[str, Any]:
        """Read and hash only inline-sized objects through the CAS dirfd boundary."""
        try:
            with self._artifacts.open(canonical) as stream:
                size = os.fstat(stream.fileno()).st_size
                document: dict[str, Any] = {
                    "digest": canonical,
                    "byteLength": size,
                    "inline": False,
                    "verification": "not-inlined",
                }
                if size > MAX_ARTIFACT_INLINE_BYTES:
                    return document
                payload = stream.read(MAX_ARTIFACT_INLINE_BYTES + 1)
        except (ArtifactStoreError, OSError) as exc:
            raise not_found("The artifact object is not present in the CAS.") from exc
        if len(payload) > MAX_ARTIFACT_INLINE_BYTES:
            return document
        if "sha256:" + hashlib.sha256(payload).hexdigest() != canonical:
            raise not_found("The artifact content does not match its digest.")
        document.update(byteLength=len(payload), verification="verified")
        try:
            document["text"] = payload.decode("utf-8")
            document["inline"] = True
        except UnicodeError:
            pass
        return document
