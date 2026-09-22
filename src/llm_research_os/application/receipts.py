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

from llm_research_os.application.errors import ApplicationError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_receipts (
    command_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json))
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
            connection.execute(_REJECT_UPDATE)
            connection.execute(_REJECT_DELETE)
            connection.execute("PRAGMA user_version = 1")
        except Exception:
            connection.close()
            raise
        return connection
