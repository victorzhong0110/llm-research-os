"""Application-layer error types.

These exceptions are raised at the application service boundary, distinct from
domain-level errors raised by ``research/``, ``runs/``, ``execution/`` or
``storage/``. Callers may catch ``ApplicationError`` to handle any R02
operation failure without coupling to the underlying control module.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for R02 application services."""


class WorkspaceError(ApplicationError):
    """Base class for workspace bind/init/open failures."""


class WorkspaceRootOverlapError(WorkspaceError):
    """Two workspace paths resolve to the same on-disk root.

    Reject accidental sharing of control-plane and Worker roots; reuse of an
    already-bound path; or any reuse of CAS / config / receipt-log paths
    between distinct workspaces.
    """


class WorkspaceStateError(WorkspaceError):
    """Workspace layout exists but is inconsistent (missing config, wrong project)."""


class ReceiptLogError(ApplicationError):
    """Raised when an operation receipt cannot be appended or replayed."""


class ReceiptReplayConflictError(ReceiptLogError):
    """Raised when a replay attempt does not match the prior receipt.

    Re-exposing this at the package root lets CLI and Python callers catch
    the error by importing only from :mod:`llm_research_os.application`.
    """


class InvalidCommandIdError(ApplicationError):
    """Caller supplied a malformed ``command_id``."""


__all__ = [
    "ApplicationError",
    "InvalidCommandIdError",
    "ReceiptLogError",
    "ReceiptReplayConflictError",
    "WorkspaceError",
    "WorkspaceRootOverlapError",
    "WorkspaceStateError",
]
