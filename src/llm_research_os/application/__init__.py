"""Thin shared application services for CLI, Python, and future Web callers.

The application layer binds workspace identity and gives CLI and Python callers a
common façade over the existing ``research/``, ``runs/``, ``execution/`` and
``report/`` controls. It does not own new facts; durable operation records live
in the workspace's append-only receipt log, and EventStore remains the only
authoritative source of record for stored events. Operations are versioned
explicitly through receipt identity.

R02 ships this package. R03+ may add new operations without changing the R02
public API. Do not introduce a parallel authorization store here; worker HMAC
grants and existing EventStore CAS remain the launch authority surface.
"""

from llm_research_os.application.errors import (
    ApplicationError,
    InvalidCommandIdError,
    ReceiptLogError,
    WorkspaceError,
    WorkspaceRootOverlapError,
    WorkspaceStateError,
)
from llm_research_os.application.identity import (
    OperationIdentity,
    bind_operation_identity,
    normalize_command_id,
)
from llm_research_os.application.operations import (
    ApplicationOperations,
    DiffOutcome,
    DryRunOutcome,
    OperationStatus,
    ValidationOutcome,
)
from llm_research_os.application.receipts import (
    OperationReceipt,
    ReceiptLog,
    ReceiptReplayConflictError,
    operation_receipt_document,
)
from llm_research_os.application.service import (
    OperationResult,
    Service,
    WorkspaceConfig,
    WorkspacePaths,
    open_workspace,
)
from llm_research_os.application.workspace import (
    Workspace,
    WorkspaceLayout,
    describe_workspace,
    init_workspace,
    load_workspace,
)

__all__ = [
    "ApplicationError",
    "ApplicationOperations",
    "DiffOutcome",
    "DryRunOutcome",
    "InvalidCommandIdError",
    "OperationIdentity",
    "OperationReceipt",
    "OperationResult",
    "OperationStatus",
    "ReceiptLog",
    "ReceiptLogError",
    "ReceiptReplayConflictError",
    "Service",
    "ValidationOutcome",
    "Workspace",
    "WorkspaceConfig",
    "WorkspaceError",
    "WorkspaceLayout",
    "WorkspacePaths",
    "WorkspaceRootOverlapError",
    "WorkspaceStateError",
    "bind_operation_identity",
    "describe_workspace",
    "init_workspace",
    "load_workspace",
    "normalize_command_id",
    "open_workspace",
    "operation_receipt_document",
]
