"""Transactional, revision-bound view storage; never writes execution facts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from llm_research_os.application.workspace import Workspace
from llm_research_os.dashboard.models import DashboardDocument, DashboardWrite, check_agent_edit

MAX_BYTES = 1048576


class DashboardError(ValueError):
    """A refused view write or unreadable view history."""


class DashboardStore:
    def __init__(self, workspace: Workspace) -> None:
        self.project_id = workspace.project_id
        self.path = workspace.root / "dashboard.sqlite"
        resolved = self.path.resolve()
        if self.path.is_symlink() or resolved in (workspace.control_db, workspace.receipt_db):
            raise DashboardError("unsafe view store")
        if resolved.is_relative_to(workspace.worker_root) or resolved.is_relative_to(
            workspace.cas_root
        ):
            raise DashboardError("view store overlaps execution storage")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.path.is_symlink():
            raise DashboardError("unsafe view store")
        try:
            db = sqlite3.connect(self.path, timeout=5)
            try:
                with db:
                    yield db
            finally:
                db.close()
        except sqlite3.Error as exc:
            raise DashboardError("view store unavailable") from exc

    def _decode(self, body: str) -> DashboardDocument:
        if len(body.encode()) > MAX_BYTES:
            raise DashboardError("view document exceeds limit")
        document = DashboardDocument.model_validate_json(body)
        if document.project_id != self.project_id:
            raise DashboardError("foreign view document")
        return document

    def read(self, revision: int | None = None) -> DashboardDocument:
        if revision is not None and revision < 0:
            raise DashboardError("invalid revision")
        if revision == 0 or not self.path.exists():
            if revision not in (0, None):
                raise DashboardError("revision unavailable")
            return DashboardDocument(projectId=self.project_id)
        with self._connect() as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='revisions'").fetchone():
                if revision is not None:
                    raise DashboardError("revision unavailable")
                return DashboardDocument(projectId=self.project_id)
            if revision is None:
                row = db.execute(
                    "SELECT body FROM revisions WHERE project=? ORDER BY revision DESC LIMIT 1",
                    (self.project_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT body FROM revisions WHERE project=? AND revision=?",
                    (self.project_id, revision),
                ).fetchone()
            if row is None:
                if revision is not None:
                    raise DashboardError("revision unavailable")
                return DashboardDocument(projectId=self.project_id)
            return self._decode(row[0])

    def write(self, request: DashboardWrite) -> DashboardDocument:
        if request.project_id != self.project_id:
            raise DashboardError("foreign project")
        encoded = request.model_dump_json(by_alias=True)
        if len(encoded.encode()) > MAX_BYTES - 1024:
            raise DashboardError("view document exceeds limit")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS revisions (project TEXT, revision INTEGER, "
                "request TEXT, digest TEXT, body TEXT, PRIMARY KEY(project, revision), "
                "UNIQUE(project, request))"
            )
            replay = db.execute(
                "SELECT digest,body FROM revisions WHERE project=? AND request=?",
                (self.project_id, request.request_id),
            ).fetchone()
            if replay:
                if replay[0] != digest:
                    raise DashboardError("request identity reused")
                return self._decode(replay[1])
            row = db.execute(
                "SELECT body FROM revisions WHERE project=? ORDER BY revision DESC LIMIT 1",
                (self.project_id,),
            ).fetchone()
            current = self._decode(row[0]) if row else DashboardDocument(projectId=self.project_id)
            if request.expected_revision != current.revision:
                raise DashboardError("revision conflict")
            if request.author_kind == "agent":
                check_agent_edit(current.state, request.state)
            document = DashboardDocument(
                projectId=self.project_id,
                revision=current.revision + 1,
                state=request.state,
                author=request.author,
                authorKind=request.author_kind,
                updatedAt=datetime.now(UTC).isoformat(),
            )
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?)",
                (
                    self.project_id,
                    document.revision,
                    request.request_id,
                    digest,
                    document.model_dump_json(by_alias=True),
                ),
            )
            db.execute(
                "DELETE FROM revisions WHERE project=? AND revision<=?",
                (
                    self.project_id,
                    document.revision - 30,
                ),
            )
            return document


def read_write_request(path: Path) -> DashboardWrite:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DashboardError("view document exceeds limit")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise DashboardError("duplicate JSON key")
            result[key] = value
        return result

    json.loads(raw, object_pairs_hook=unique)
    return DashboardWrite.model_validate_json(raw)
