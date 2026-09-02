"""Stable fail-closed errors for the pure Run/Attempt projection."""

from pydantic import ValidationError


class RunStateError(ValueError):
    """Fail-closed error from the Run/Attempt state projection.

    Messages identify the lifecycle type, event id and sequence. They MUST NOT
    include payload bodies or other potentially sensitive document text.
    """


class RunTransitionError(RunStateError):
    """Illegal lifecycle transition, identity drift, or ordering violation."""


class RunPayloadError(RunStateError):
    """An identified lifecycle type carried a structurally invalid payload."""


class RunControlError(RunStateError):
    """Fail-closed error from the atomic RunControl append boundary.

    Messages MUST NOT include payload bodies, untrusted payload field names,
    or other potentially sensitive document text.
    """


class RunCancellationRequestError(ValueError):
    """Invalid external RunCancellationRequest document.

    Messages and JSON Pointers MUST NOT include unknown field names, hostile
    discriminator values, or other potentially sensitive document text.
    """

    def __init__(self, error: ValidationError) -> None:
        super().__init__("run cancellation request failed validation")
        self.error = error
