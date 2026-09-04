"""Fail-closed errors for ModelProvider. Messages must not echo prompt or output text."""

from pydantic import ValidationError


class ModelProviderError(ValueError):
    """Fail-closed error from the model-call boundary.

    Messages MUST NOT include prompt text, output text, or fixture bodies
    (TM-007, TM-022).
    """

    def __init__(self, message: str, code: str = "model-provider") -> None:
        super().__init__(message)
        self.code = code


class ModelCapabilityError(ModelProviderError):
    """A requested capability is absent from the allowed set."""


class ModelFixtureError(ModelProviderError):
    """A fixture document is missing, mismatched, or structurally invalid."""


class ModelCallError(ModelProviderError):
    """Fail-closed error from recording ``ai.call.*`` facts."""


class ModelPayloadError(ModelProviderError):
    """An identified ``ai.call.*`` event carried a structurally invalid payload."""


class ModelRequestError(ValueError):
    """Invalid external model generate request or fixture document."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("model request failed validation")
        self.error = error
        self.code = "model-request"


class ModelTransportError(ModelProviderError):
    """The HTTP adapter could not complete a request without leaking vendor objects."""
