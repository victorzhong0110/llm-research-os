"""Pure Run/Attempt v0alpha1 state projection and append boundary."""

from llm_research_os.runs.cancellation import (
    AttemptCancellationTarget,
    RunCancellationRequestDocument,
    RunCancellationTarget,
    load_run_cancellation_request,
    request_cancellation,
    validate_run_cancellation_request_document,
)
from llm_research_os.runs.control import RunControl, RunControlHead, RunControlResult
from llm_research_os.runs.errors import (
    RunCancellationRequestError,
    RunControlError,
    RunPayloadError,
    RunStateError,
    RunTransitionError,
)
from llm_research_os.runs.models import (
    AttemptSnapshot,
    AttemptStatus,
    RetryHint,
    RunSnapshot,
    RunStatus,
    run_snapshot_document,
    validate_run_snapshot_document,
)
from llm_research_os.runs.reducer import RunStateProjection

__all__ = [
    "AttemptCancellationTarget",
    "AttemptSnapshot",
    "AttemptStatus",
    "RetryHint",
    "RunCancellationRequestDocument",
    "RunCancellationRequestError",
    "RunCancellationTarget",
    "RunControl",
    "RunControlError",
    "RunControlHead",
    "RunControlResult",
    "RunPayloadError",
    "RunSnapshot",
    "RunStateError",
    "RunStateProjection",
    "RunStatus",
    "RunTransitionError",
    "load_run_cancellation_request",
    "request_cancellation",
    "run_snapshot_document",
    "validate_run_cancellation_request_document",
    "validate_run_snapshot_document",
]
