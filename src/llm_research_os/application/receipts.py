"""Append-only command receipts outside the EventStore.

Receipts cite fact event ids and artifact digests. They are not a second
event log and they do not authorize launch. The EventStore schema stays v2;
this file is workspace operation state and never rewrites event digests.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_research_os.application.errors import ApplicationError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_receipts (
    command_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json))
) STRICT
"""
_INTENTS = """
CREATE TABLE IF NOT EXISTS operation_effect_intents (
    scope TEXT PRIMARY KEY,
    content_digest TEXT NOT NULL
) STRICT
"""
_REJECT_UPDATE = """
CREATE TRIGGER IF NOT EXISTS operation_receipts_reject_update
BEFORE UPDATE ON operation_receipts
BEGIN
    SELECT RAISE(ABORT, 'operation receipts are append-only');
END
"""
_REJECT_DELETE = """
CREATE TRIGGER IF NOT EXISTS operation_receipts_reject_delete
BEFORE DELETE ON operation_receipts
BEGIN
    SELECT RAISE(ABORT, 'operation receipts are append-only');
END
"""


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    command_id: str
    request_digest: str
    document: dict[str, object]


class ReceiptLog:
    """Durable receipt log for one workspace."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def lookup(self, command_id: str) -> StoredReceipt | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT command_id, request_digest, receipt_json
                FROM operation_receipts
                WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        document = json.loads(row[2])
        if type(document) is not dict:
            raise ApplicationError("receipt-corrupt", "stored receipt is not an object")
        return StoredReceipt(
            command_id=str(row[0]),
            request_digest=str(row[1]),
            document=document,
        )

    def reserve_effect(self, scope: str, digest: str) -> bool:
        """Reserve before dispatch. Crash/timeout never releases this identity."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT content_digest FROM operation_effect_intents WHERE scope = ?", (scope,)
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ApplicationError(
                        "effect-conflict", "effect identity already binds other material"
                    )
                return False
            connection.execute(
                "INSERT INTO operation_effect_intents VALUES (?, ?)", (scope, digest)
            )
            connection.commit()
            return True
        except sqlite3.Error as exc:
            raise ApplicationError(
                "receipt-unwritable", "dispatch intent could not be recorded"
            ) from exc
        finally:
            connection.close()

    def published_reports(
        self, *, report_artifact: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Bounded workspace-local discovery; receipts remain operation state."""
        connection = self._connect()
        values = (report_artifact, report_artifact)
        try:
            count = connection.execute(
                """SELECT count(*) FROM operation_receipts
                WHERE json_extract(receipt_json, '$.operation') = 'conclusion.publish'
                AND (? IS NULL OR json_extract(receipt_json, '$.result.reportArtifact') = ?)""",
                values,
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT receipt_json FROM operation_receipts
                WHERE json_extract(receipt_json, '$.operation') = 'conclusion.publish'
                AND (? IS NULL OR json_extract(receipt_json, '$.result.reportArtifact') = ?)
                ORDER BY rowid DESC LIMIT 10""",
                values,
            ).fetchall()
            return [json.loads(row[0]) for row in rows], count
        finally:
            connection.close()

    def append(self, command_id: str, request_digest: str, document: dict[str, object]) -> None:
        payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO operation_receipts (command_id, request_digest, receipt_json)
                VALUES (?, ?, ?)
                """,
                (command_id, request_digest, payload),
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ApplicationError(
                "receipt-conflict",
                "command identity was already committed",
            ) from exc
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ApplicationError(
                "receipt-unwritable",
                "operation receipt could not be recorded",
            ) from exc
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            journal = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if journal is None or str(journal[0]).lower() != "wal":
                raise ApplicationError("receipt-unwritable", "receipt log requires SQLite WAL")
            connection.execute(_SCHEMA)
            connection.execute(_INTENTS)
            connection.execute(_REJECT_UPDATE)
            connection.execute(_REJECT_DELETE)
            connection.execute("PRAGMA user_version = 1")
        except Exception:
            connection.close()
            raise
        return connection
