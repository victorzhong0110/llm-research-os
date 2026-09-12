"""M2-0 Worker semantic plane: loopback long-poll, HMAC grants, CPU sandbox."""

from llm_research_os.workers.control import WorkerControl, WorkerFold, apply_worker_fold
from llm_research_os.workers.errors import (
    WorkerCallError,
    WorkerError,
    WorkerGrantError,
    WorkerRequestError,
    WorkerSandboxError,
)
from llm_research_os.workers.models import (
    TYPE_GRANT_CONSUMED,
    TYPE_GRANT_RECORDED,
    TYPE_GRANT_REVOKED,
    TYPE_WORK_CLAIMED,
    TYPE_WORK_COMPLETED,
    TYPE_WORK_FAILED,
    TYPE_WORK_LEASE_EXPIRED,
    TYPE_WORK_LEASED,
    TYPE_WORK_QUEUED,
    TYPE_WORKER_REGISTERED,
)
from llm_research_os.workers.plane import ClaimedWork, WorkerPlane
from llm_research_os.workers.tokens import HMAC_KEY_BYTES, issue_grant_token, require_hmac_key

__all__ = [
    "HMAC_KEY_BYTES",
    "TYPE_GRANT_CONSUMED",
    "TYPE_GRANT_RECORDED",
    "TYPE_GRANT_REVOKED",
    "TYPE_WORKER_REGISTERED",
    "TYPE_WORK_CLAIMED",
    "TYPE_WORK_COMPLETED",
    "TYPE_WORK_FAILED",
    "TYPE_WORK_LEASED",
    "TYPE_WORK_LEASE_EXPIRED",
    "TYPE_WORK_QUEUED",
    "ClaimedWork",
    "WorkerCallError",
    "WorkerControl",
    "WorkerError",
    "WorkerFold",
    "WorkerGrantError",
    "WorkerPlane",
    "WorkerRequestError",
    "WorkerSandboxError",
    "apply_worker_fold",
    "issue_grant_token",
    "require_hmac_key",
]
