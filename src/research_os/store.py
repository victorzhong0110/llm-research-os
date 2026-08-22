"""Append-only SQLite fact source (decisions ``6-DBC`` and ``P8``).

Events are the source of truth; anything else (run status, dashboards) is a
projection rebuilt from this stream. The store enforces append-only semantics:
events are inserted and read, never updated or deleted. Corrections are new
events.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

from research_os.models.research_event import ResearchEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL UNIQUE,
    project_id      TEXT NOT NULL,
    run_id          TEXT,
    type            TEXT NOT NULL,
    time            TEXT NOT NULL,
    payload_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
"""


class EventStore:
    """A minimal append-only event store backed by SQLite."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def append(self, event: ResearchEvent) -> int:
        """Append one immutable event, returning its monotonic sequence number."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO events "
                "(event_id, project_id, run_id, type, time, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.projectId,
                    event.runId,
                    event.type,
                    event.time,
                    json.dumps(event.model_dump(mode="json")),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def read(
        self, *, project_id: str | None = None, run_id: str | None = None
    ) -> Iterator[ResearchEvent]:
        """Yield events in insertion order, optionally filtered by scope."""
        query = "SELECT payload_json FROM events"
        clauses: list[str] = []
        params: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY seq ASC"

        with closing(self._connect()) as conn:
            for row in conn.execute(query, params):
                yield ResearchEvent.model_validate_json(row["payload_json"])

    def count(self) -> int:
        """Return the total number of stored events."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
            return int(row["n"])

    def run_status(self, run_id: str) -> str:
        """Project the terminal status of a run from its event stream.

        Returns ``unknown`` when no terminal event has been observed, honoring
        principle P5 (never guess success).
        """
        terminal = {
            "dev.researchos.run.completed": "completed",
            "dev.researchos.run.failed": "failed",
            "dev.researchos.run.cancelled": "cancelled",
        }
        status = "unknown"
        for event in self.read(run_id=run_id):
            if event.type in terminal:
                return terminal[event.type]
            status = "running"
        return status
