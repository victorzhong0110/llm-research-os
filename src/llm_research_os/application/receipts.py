"""Durable operation receipts.

A receipt records that an application-layer command was attempted: its
identity, content digest, expected EventStore head, and the resulting event
or refusal. Receipts live in the workspace's append-only JSONL log and are
purely operational records; they are NOT stored as ``ResearchEvent`` facts
and do not become launch authority.

Replay semantics: re-submitting the same ``(command_id, submission_id)``
with the same content digest and expected head returns the existing
receipt. Any difference in content or expected head fails with
:class:`ReceiptReplayConflictError` so the caller knows the replay is not
trivially safe.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from llm_research_os.application.errors import ReceiptLogError

RECEIPT_LOG_VERSION = "application.receipts/v0alpha1"
RECEIPT_LOG_NAME = "operations.jsonl"
RECEIPT_LOG_SUBDIR = ".researchos"

_TERMINATOR = "\n"


class ReceiptReplayConflictError(ReceiptLogError):
    """Raised when a replay attempt does not match the prior receipt.

    The caller explicitly tried to reuse a ``command_id`` with different
    content, a stale expected head, or a different ``submission_id`` than
    the recorded value. This is a fail-closed boundary; the caller must
    obtain a fresh command identity.
    """


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    """One durable record of an application-layer command submission."""

    command_id: str
    submission_id: int
    command: str
    content_digest: str
    expected_head: int | None
    outcome: str  # ``appended`` | ``validated`` | ``refused`` | ``noop`` | ``read``
    event_id: str | None = None
    event_sequence: int | None = None
    recorded_at: str = field(default_factory=lambda: _utc_now_iso())
    detail: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    schema_version: str = RECEIPT_LOG_VERSION

    def to_document(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "commandId": self.command_id,
            "submissionId": self.submission_id,
            "command": self.command,
            "contentDigest": self.content_digest,
            "expectedHead": self.expected_head,
            "outcome": self.outcome,
            "eventId": self.event_id,
            "eventSequence": self.event_sequence,
            "recordedAt": self.recorded_at,
            "detail": dict(self.detail),
        }
        return body


def operation_receipt_document(receipt: OperationReceipt) -> dict[str, Any]:
    return receipt.to_document()


class ReceiptLog:
    """Append-only JSONL log of operation receipts.

    The log is a regular file, written in line-delimited UTF-8 JSON and
    flushed after every append. Replay reads the log sequentially; the
    in-memory index keeps the last seen ``(command_id, submission_id)``
    pair so the common-case replay check is O(1).

    Concurrent writers from a single workspace are not supported; the CLI
    and Python entrypoints acquire an exclusive ``flock`` on the log file
    before mutating it.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._index: dict[tuple[str, int], OperationReceipt] = {}
        if path.exists():
            self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def __iter__(self) -> Iterator[OperationReceipt]:
        yield from self._index.values()

    def find(self, command_id: str, submission_id: int) -> OperationReceipt | None:
        return self._index.get((command_id, submission_id))

    def list(self) -> list[OperationReceipt]:
        return sorted(
            self._index.values(),
            key=lambda r: (r.command_id, r.submission_id),
        )

    def replay_guard(
        self,
        *,
        command_id: str,
        submission_id: int,
        content_digest: str,
        expected_head: int | None,
    ) -> OperationReceipt | None:
        """Return prior receipt if a matching replay exists; raise on conflict.

        Returns ``None`` if no prior receipt with the same identity exists.
        Raises :class:`ReceiptReplayConflictError` if the caller reuses the
        identity but the content differs. The CLI/Python entrypoints translate
        this into a fail-closed response (exit code 2 or
        :class:`ApplicationError`).
        """

        prior = self._index.get((command_id, submission_id))
        if prior is None:
            return None
        if prior.content_digest != content_digest or prior.expected_head != expected_head:
            raise ReceiptReplayConflictError(
                f"command_id {command_id!r} submission {submission_id} was previously "
                f"recorded with a different content or expected head"
            )
        return prior

    def append(self, receipt: OperationReceipt) -> OperationReceipt:
        key = (receipt.command_id, receipt.submission_id)
        if key in self._index:
            prior = self._index[key]
            if (
                prior.content_digest != receipt.content_digest
                or prior.expected_head != receipt.expected_head
                or prior.command != receipt.command
            ):
                raise ReceiptReplayConflictError(
                    f"duplicate receipt for {receipt.command_id!r} "
                    f"submission {receipt.submission_id}"
                )
            return prior
        self._append_line(receipt)
        self._index[key] = receipt
        return receipt

    def append_all(self, receipts: Iterable[OperationReceipt]) -> None:
        for receipt in receipts:
            self.append(receipt)

    def _append_line(self, receipt: OperationReceipt) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(receipt.to_document(), ensure_ascii=False, sort_keys=True)
        payload = (line + _TERMINATOR).encode("utf-8")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        fd = os.open(self._path, flags, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        with suppress(OSError):
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)

    def _load_existing(self) -> None:
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        document = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise ReceiptLogError(
                            f"unparseable receipt line in {self._path}: {exc}"
                        ) from exc
                    receipt = _receipt_from_document(document)
                    self._index[(receipt.command_id, receipt.submission_id)] = receipt
        except FileNotFoundError:
            return


def _receipt_from_document(document: Mapping[str, Any]) -> OperationReceipt:
    try:
        command_id = str(document["commandId"])
        submission_id = int(document["submissionId"])
        command = str(document["command"])
        content_digest = str(document["contentDigest"])
        expected_head_raw = document.get("expectedHead")
        expected_head = int(expected_head_raw) if expected_head_raw is not None else None
        outcome = str(document["outcome"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReceiptLogError(f"receipt document missing required field: {exc}") from exc
    return OperationReceipt(
        command_id=command_id,
        submission_id=submission_id,
        command=command,
        content_digest=content_digest,
        expected_head=expected_head,
        outcome=outcome,
        event_id=document.get("eventId"),
        event_sequence=document.get("eventSequence"),
        recorded_at=str(document.get("recordedAt") or _utc_now_iso()),
        detail=MappingProxyType(dict(document.get("detail") or {})),
        schema_version=str(document.get("schemaVersion") or RECEIPT_LOG_VERSION),
    )


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ReceiptLogSnapshot:
    """Snapshot of a receipt log slice, used for CLI output."""

    path: Path
    entries: tuple[OperationReceipt, ...]

    @classmethod
    def from_log(cls, log: ReceiptLog) -> Self:
        return cls(path=log.path, entries=tuple(log.list()))


__all__ = [
    "RECEIPT_LOG_NAME",
    "RECEIPT_LOG_SUBDIR",
    "RECEIPT_LOG_VERSION",
    "OperationReceipt",
    "ReceiptLog",
    "ReceiptLogSnapshot",
    "ReceiptReplayConflictError",
    "operation_receipt_document",
]
