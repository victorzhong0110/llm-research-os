"""Top-level service façade for the R02 application layer.

The service ties together a :class:`Workspace`, the receipt log, the
EventStore, and the operation façade. It is the single entry point used by
both the CLI handlers and the Python entrypoints so that semantic digests and
exit codes are guaranteed identical for the same command.

Receipt semantics:

- The service resolves ``command_id`` against the receipt log. A replay
  with the same ``command_id``/``submission_id`` and identical content
  returns the existing receipt.
- A replay with the same ``command_id`` but different content fails
  closed (``ReceiptReplayConflictError``).
- Successful read operations are not recorded as event-bearing receipts;
  they are recorded as ``read`` outcomes for replay debugging only.

The service does not bypass EventStore. Substantive fact emissions stay in
the existing M1/M2 issue-handler commands (e.g. ``researchos authorizations
record``); the service exposes reads and pure planning outputs for R02 and
relies on those existing commands for state changes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from llm_research_os.application.identity import OperationIdentity, bind_operation_identity
from llm_research_os.application.operations import (
    ApplicationOperations,
    OperationStatus,
    ReadOutcome,
    ValidationOutcome,
)
from llm_research_os.application.receipts import (
    OperationReceipt,
    ReceiptLog,
    ReceiptReplayConflictError,
)
from llm_research_os.application.workspace import (
    Workspace,
    describe_workspace,
    init_workspace,
    load_workspace,
)
from llm_research_os.storage import EventStore, EventStoreError


def compute_content_digest(payload: bytes | str) -> str:
    """Return the hex SHA-256 of the UTF-8 bytes of ``payload``.

    The application service uses canonical SHA-256 as the replay-guard
    digest because the persisted receipt log must survive independent
    verification. JSON canonicalization (RFC 8785) is applied by the
    caller's contract layer before this digest is recorded.
    """

    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _canonical_json_digest(payload: Mapping[str, Any] | list[Any] | str | int | bool | None) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return compute_content_digest(text)


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Caller-supplied layout hints for :func:`open_workspace`."""

    root: Path
    project_id: str
    control_db: Path | None = None
    cas_root: Path | None = None
    worker_root: Path | None = None
    supplemental_roots: tuple[Path, ...] = ()
    create: bool = True


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Resolved paths after :func:`open_workspace` returns."""

    root: Path
    control_db: Path
    cas_root: Path
    receipt_log: Path
    config_path: Path
    worker_root: Path | None = None


def open_workspace(config: WorkspaceConfig) -> Workspace:
    """Open or create the workspace described by ``config``."""

    if config.create:
        return init_workspace(
            root=config.root,
            project_id=config.project_id,
            control_db=config.control_db,
            cas_root=config.cas_root,
            worker_root=config.worker_root,
            supplemental_roots=config.supplemental_roots,
        )
    return load_workspace(config.root)


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Return value of every :meth:`Service.execute_*` operation.

    ``receipt`` is the durable :class:`OperationReceipt` recorded in the
    workspace receipt log. ``outcome`` is the operation-specific
    result object. ``document`` is the canonical JSON-friendly form for
    CLI output.
    """

    receipt: OperationReceipt | None
    outcome: Any
    document: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        body = {
            "status": self.document.get("status"),
            "outcome": self.document.get("outcome"),
            "receipt": self.receipt.to_document() if self.receipt else None,
        }
        return body


class Service:
    """R02 application service.

    Construct one per command invocation; do not share across processes.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._operations = ApplicationOperations(project_id=workspace.project_id)

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    def describe(self) -> Mapping[str, object]:
        return describe_workspace(self._workspace)

    def receipt_log(self) -> ReceiptLog:
        return self._workspace.receipt_log

    def list_receipts(self) -> tuple[OperationReceipt, ...]:
        return tuple(self._workspace.receipt_log.list())

    def _open_event_store(self) -> EventStore | None:
        """Open the workspace's EventStore if it already has a database.

        ``init_workspace`` does not create the SQLite database; only the
        manifest paths. Operations that need the event store return a
        ``store-missing`` outcome when the database file does not exist
        yet, so first-run setups don't crash.
        """

        if not self._workspace.control_db.exists():
            return None
        try:
            return EventStore(self._workspace.control_db, require_existing=True)
        except EventStoreError as exc:
            raise EventStoreError(
                f"could not open event store at {self._workspace.control_db}: {exc}"
            ) from exc

    def _record_receipt(
        self,
        *,
        operation_name: str,
        identity: OperationIdentity,
        content_digest: str,
        expected_head: int | None,
        outcome_label: str,
        detail: Mapping[str, Any],
        event_id: str | None = None,
        event_sequence: int | None = None,
    ) -> OperationReceipt | None:
        if outcome_label == "refused":
            return None
        receipt = OperationReceipt(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            command=operation_name,
            content_digest=content_digest,
            expected_head=expected_head,
            outcome=outcome_label,
            event_id=event_id,
            event_sequence=event_sequence,
            detail=MappingProxyType(dict(detail)),
        )
        try:
            self._workspace.receipt_log.append(receipt)
        except ReceiptReplayConflictError:
            existing = self._workspace.receipt_log.find(identity.command_id, identity.submission_id)
            if existing is None:
                raise
            return existing
        return receipt

    def execute_validate(
        self,
        *,
        spec_path: Path,
        command_id: str | None,
        submission_id: int = 1,
    ) -> OperationResult:
        identity = bind_operation_identity(command_id, submission_id=submission_id)
        outcome: ValidationOutcome = self._operations.validate(spec_path)
        digest = _canonical_json_digest(
            {
                "operation": "app.validate",
                "specPath": str(spec_path),
                "outcome": outcome.status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome,
                document={
                    "status": "replayed",
                    "outcome": outcome.status.to_document(),
                    "validate": outcome.document,
                },
            )
        receipt = self._record_receipt(
            operation_name="app.validate",
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="validated" if outcome.status.ok else "refused",
            detail=outcome.status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome,
            document={
                "status": "ok" if outcome.status.ok else "refused",
                "outcome": outcome.status.to_document(),
                "validate": outcome.document,
            },
        )

    def execute_diff(
        self,
        *,
        old_path: Path,
        new_path: Path,
        command_id: str | None,
        submission_id: int = 1,
    ) -> OperationResult:
        identity = bind_operation_identity(command_id, submission_id=submission_id)
        outcome = self._operations.diff(old_path, new_path)
        digest = _canonical_json_digest(
            {
                "operation": "app.diff",
                "oldPath": str(old_path),
                "newPath": str(new_path),
                "outcome": outcome.status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome,
                document={
                    "status": "replayed",
                    "outcome": outcome.status.to_document(),
                    "diff": outcome.document,
                },
            )
        receipt = self._record_receipt(
            operation_name="app.diff",
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="validated" if outcome.status.ok else "refused",
            detail=outcome.status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome,
            document={
                "status": "ok" if outcome.status.ok else "refused",
                "outcome": outcome.status.to_document(),
                "diff": outcome.document,
            },
        )

    def execute_dry_run(
        self,
        *,
        spec_path: Path,
        workflow: str | None,
        registry: Path | None,
        command_id: str | None,
        submission_id: int = 1,
    ) -> OperationResult:
        identity = bind_operation_identity(command_id, submission_id=submission_id)
        outcome = self._operations.dry_run(spec_path, workflow, registry)
        digest = _canonical_json_digest(
            {
                "operation": "app.dry_run",
                "specPath": str(spec_path),
                "workflow": workflow,
                "registry": str(registry) if registry is not None else None,
                "outcome": outcome.status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome,
                document={
                    "status": "replayed",
                    "outcome": outcome.status.to_document(),
                    "dryRun": outcome.report_document,
                },
            )
        receipt = self._record_receipt(
            operation_name="app.dry_run",
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="validated" if outcome.status.ok else "refused",
            detail=outcome.status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome,
            document={
                "status": "ok" if outcome.status.ok else "refused",
                "outcome": outcome.status.to_document(),
                "dryRun": outcome.report_document,
            },
        )

    def execute_ledger_read(
        self,
        *,
        command_id: str | None,
        submission_id: int = 1,
    ) -> OperationResult:
        identity = bind_operation_identity(command_id, submission_id=submission_id)
        store = self._open_event_store()
        if store is None:
            return self._record_store_missing(
                identity,
                operation_name="app.ledger_read",
                OperationStatus_kwargs={
                    "name": "ledger-read",
                    "ok": False,
                    "reason_code": "store-missing",
                    "detail": MappingProxyType(
                        {
                            "controlDb": str(self._workspace.control_db),
                            "hint": (
                                "create the EventStore by running an existing "
                                "researchos m1 prove / m2 prove command first"
                            ),
                        }
                    ),
                },
                empty_key="ledger",
            )
        try:
            outcome = self._operations.ledger_read(store)
        finally:
            store.close()
        digest = _canonical_json_digest(
            {
                "operation": "app.ledger_read",
                "projectId": self._workspace.project_id,
                "outcome": outcome.status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome,
                document={
                    "status": "replayed",
                    "outcome": outcome.status.to_document(),
                    "ledger": list(outcome.documents),
                },
            )
        receipt = self._record_receipt(
            operation_name="app.ledger_read",
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="read" if outcome.status.ok else "refused",
            detail=outcome.status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome,
            document={
                "status": "ok" if outcome.status.ok else "refused",
                "outcome": outcome.status.to_document(),
                "ledger": list(outcome.documents),
            },
        )

    def execute_run_query(
        self,
        *,
        run_id: str,
        command_id: str | None,
        submission_id: int = 1,
    ) -> OperationResult:
        identity = bind_operation_identity(command_id, submission_id=submission_id)
        store = self._open_event_store()
        if store is None:
            return self._record_store_missing(
                identity,
                operation_name="app.run_query",
                OperationStatus_kwargs={
                    "name": "run-query",
                    "ok": False,
                    "reason_code": "store-missing",
                    "detail": MappingProxyType(
                        {
                            "runId": run_id,
                            "controlDb": str(self._workspace.control_db),
                            "hint": (
                                "create the EventStore by running an existing "
                                "researchos m1 prove / m2 prove command first"
                            ),
                        }
                    ),
                },
                empty_key="run",
            )
        try:
            outcome: ReadOutcome = self._operations.run_query(store, run_id)
        finally:
            store.close()
        digest = _canonical_json_digest(
            {
                "operation": "app.run_query",
                "runId": run_id,
                "projectId": self._workspace.project_id,
                "outcome": outcome.status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome,
                document={
                    "status": "replayed",
                    "outcome": outcome.status.to_document(),
                    "run": list(outcome.documents),
                },
            )
        receipt = self._record_receipt(
            operation_name="app.run_query",
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="read" if outcome.status.ok else "refused",
            detail=outcome.status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome,
            document={
                "status": "ok" if outcome.status.ok else "refused",
                "outcome": outcome.status.to_document(),
                "run": list(outcome.documents),
            },
        )

    def _record_store_missing(
        self,
        identity: OperationIdentity,
        *,
        operation_name: str,
        OperationStatus_kwargs: Mapping[str, Any],
        empty_key: str,
    ) -> OperationResult:
        outcome_status = OperationStatus(**OperationStatus_kwargs)
        digest = _canonical_json_digest(
            {
                "operation": operation_name,
                "outcome": outcome_status.to_document(),
            }
        )
        prior = self._workspace.receipt_log.replay_guard(
            command_id=identity.command_id,
            submission_id=identity.submission_id,
            content_digest=digest,
            expected_head=None,
        )
        if prior is not None:
            return OperationResult(
                receipt=prior,
                outcome=outcome_status,
                document={
                    "status": "replayed",
                    "outcome": outcome_status.to_document(),
                    empty_key: [],
                },
            )
        receipt = self._record_receipt(
            operation_name=operation_name,
            identity=identity,
            content_digest=digest,
            expected_head=None,
            outcome_label="refused",
            detail=outcome_status.to_document(),
        )
        return OperationResult(
            receipt=receipt,
            outcome=outcome_status,
            document={
                "status": "refused",
                "outcome": outcome_status.to_document(),
                empty_key: [],
            },
        )


__all__ = [
    "OperationResult",
    "Service",
    "WorkspaceConfig",
    "WorkspacePaths",
    "compute_content_digest",
    "open_workspace",
]
