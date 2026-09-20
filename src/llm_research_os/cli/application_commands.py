"""CLI handlers for the ``researchos app`` subcommand tree.

Each handler opens a workspace via :mod:`llm_research_os.application` and
emits a single JSON document on stdout. Exit codes follow the existing
project convention:

- ``0`` — command succeeded; the JSON document describes the operation
  outcome and its receipt.
- ``1`` — the command was attempted but the operation refused
  (``status: refused``).
- ``2`` — input / workspace / storage error; the JSON document carries the
  reason code.

CLI and Python entrypoints share the same ``Service`` façade; the receipt
digest and the canonical JSON ``status`` field are guaranteed identical
for identical inputs. This is the documented semantic equivalence that
R02 acceptance requires.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from llm_research_os.application import (
    ReceiptReplayConflictError,
    Service,
    WorkspaceError,
    WorkspaceStateError,
    init_workspace,
    load_workspace,
)
from llm_research_os.application.errors import WorkspaceRootOverlapError
from llm_research_os.application.identity import InvalidCommandIdError
from llm_research_os.cli.output import safe_text
from llm_research_os.storage import EventStoreError

_INVALID_INPUT_ERRORS = (
    EventStoreError,
    InvalidCommandIdError,
    OSError,
    ReceiptReplayConflictError,
    ValueError,
    WorkspaceError,
    WorkspaceRootOverlapError,
    WorkspaceStateError,
)


def _emit(result: dict[str, object]) -> int:
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _normalize(root: str | Path) -> Path:
    raw = Path(root) if isinstance(root, str) else root
    return raw.expanduser().resolve()


def run_app(args: argparse.Namespace) -> int:
    handler = _APP_DISPATCH.get(args.app_command)
    if handler is None:
        raise AssertionError(f"unhandled app command: {args.app_command}")
    return handler(args)


def _report_error(command: str, exc: Exception) -> int:
    """Print a ProblemReport for ``exc`` and return exit code 2."""

    print(
        json.dumps(
            {
                "command": command,
                "status": "error",
                "message": safe_text(exc),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


def _app_workspace_init(args: argparse.Namespace) -> int:
    try:
        workspace = init_workspace(
            root=_normalize(args.workspace_root),
            project_id=args.project_id,
            control_db=_normalize(args.control_db) if args.control_db else None,
            cas_root=_normalize(args.cas_root) if args.cas_root else None,
            worker_root=_normalize(args.worker_root) if args.worker_root else None,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.workspace.init", exc)
    return _emit(
        {
            "command": "app.workspace.init",
            "status": "ok",
            "projectId": workspace.project_id,
            "layout": workspace.layout.as_document(),
        }
    )


def _app_workspace_show(args: argparse.Namespace) -> int:
    try:
        workspace = load_workspace(_normalize(args.workspace_root))
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.workspace.show", exc)
    return _emit(
        {
            "command": "app.workspace.show",
            "status": "ok",
            "projectId": workspace.project_id,
            "layout": workspace.layout.as_document(),
        }
    )


def _build_service(workspace_root: str | Path, project_id: str | None = None) -> Service:
    """Open the workspace and return a ready :class:`Service`.

    A separate ``project_id`` argument is rejected because the workspace
    owns project identity; CLI callers cannot override it.
    """

    if project_id is not None:
        raise InvalidCommandIdError(
            "project_id is bound to the workspace; do not pass --project-id"
        )
    workspace = load_workspace(_normalize(workspace_root))
    return Service(workspace)


def _app_spec_validate(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
        result = service.execute_validate(
            spec_path=_normalize(args.spec),
            command_id=args.command_id,
            submission_id=args.submission_id,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.spec.validate", exc)
    status_code = 0 if result.document.get("status") in ("ok", "replayed") else 1
    _emit(result.to_document())
    return status_code


def _app_spec_diff(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
        result = service.execute_diff(
            old_path=_normalize(args.old),
            new_path=_normalize(args.new),
            command_id=args.command_id,
            submission_id=args.submission_id,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.spec.diff", exc)
    status_code = 0 if result.document.get("status") in ("ok", "replayed") else 1
    _emit(result.to_document())
    return status_code


def _app_plan_dry_run(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
        result = service.execute_dry_run(
            spec_path=_normalize(args.spec),
            workflow=args.workflow,
            registry=_normalize(args.registry) if args.registry else None,
            command_id=args.command_id,
            submission_id=args.submission_id,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.plan.dry_run", exc)
    status_code = 0 if result.document.get("status") in ("ok", "replayed") else 1
    _emit(result.to_document())
    return status_code


def _app_ledger_read(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
        result = service.execute_ledger_read(
            command_id=args.command_id,
            submission_id=args.submission_id,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.ledger.read", exc)
    status_code = 0 if result.document.get("status") in ("ok", "replayed") else 1
    _emit(result.to_document())
    return status_code


def _app_run_show(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
        result = service.execute_run_query(
            run_id=args.run_id,
            command_id=args.command_id,
            submission_id=args.submission_id,
        )
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.run.show", exc)
    status_code = 0 if result.document.get("status") in ("ok", "replayed") else 1
    _emit(result.to_document())
    return status_code


def _app_receipt_get(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.receipt.get", exc)
    receipt = service.receipt_log().find(args.command_id, args.submission_id)
    if receipt is None:
        return _emit(
            {
                "command": "app.receipt.get",
                "status": "missing",
                "commandId": args.command_id,
                "submissionId": args.submission_id,
            }
        )
    return _emit(
        {
            "command": "app.receipt.get",
            "status": "ok",
            "receipt": receipt.to_document(),
        }
    )


def _app_receipt_list(args: argparse.Namespace) -> int:
    try:
        service = _build_service(args.workspace_root)
    except _INVALID_INPUT_ERRORS as exc:
        return _report_error("app.receipt.list", exc)
    entries = [receipt.to_document() for receipt in service.list_receipts()]
    return _emit({"command": "app.receipt.list", "status": "ok", "receipts": entries})


_APP_DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "workspace-init": _app_workspace_init,
    "workspace-show": _app_workspace_show,
    "spec-validate": _app_spec_validate,
    "spec-diff": _app_spec_diff,
    "plan-dry-run": _app_plan_dry_run,
    "ledger-read": _app_ledger_read,
    "run-show": _app_run_show,
    "receipt-get": _app_receipt_get,
    "receipt-list": _app_receipt_list,
}


__all__ = [
    "_APP_DISPATCH",
    "_app_ledger_read",
    "_app_plan_dry_run",
    "_app_receipt_get",
    "_app_receipt_list",
    "_app_run_show",
    "_app_spec_diff",
    "_app_spec_validate",
    "_app_workspace_init",
    "_app_workspace_show",
    "_build_service",
    "_report_error",
    "run_app",
]
