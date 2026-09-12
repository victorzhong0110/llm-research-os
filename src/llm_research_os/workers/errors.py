"""Fail-closed Worker, grant, and sandbox errors. Messages must not echo secrets."""

from pydantic import ValidationError


class WorkerError(ValueError):
    """Fail-closed error from the Worker semantic plane."""

    def __init__(self, message: str, code: str = "worker") -> None:
        super().__init__(message)
        self.code = code


class WorkerCallError(WorkerError):
    """Fail-closed error from recording Worker or grant facts."""


class WorkerPayloadError(WorkerError):
    """An identified Worker or grant event carried a structurally invalid payload."""


class WorkerGrantError(WorkerError):
    """HMAC grant issue, verify, expiry, or revocation failure (TM-009)."""


class WorkerSandboxError(WorkerError):
    """Python-sandbox execution refused or produced an uncertified outcome."""


class WorkerRequestError(ValueError):
    """Invalid external Worker or grant request document."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("worker request failed validation")
        self.error = error
        self.code = "worker-request"
