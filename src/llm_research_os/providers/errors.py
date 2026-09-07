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


_PRE_DISPATCH_TRANSPORT_CODES = frozenset(
    {
        "dns-rebinding",
        "endpoint-blocked",
        "endpoint-dns",
        "endpoint-host",
        "endpoint-scheme",
        "endpoint-url",
        "endpoint-userinfo",
        "local-secret-forbidden",
        "proxy-forbidden",
        "remote-secret-required",
        "secret-unavailable",
    }
)


class ModelTransportError(ModelProviderError):
    """The HTTP adapter could not complete a request without leaking vendor objects.

    ``dispatched`` is false only when the adapter can prove the request never left
    this process. Timeout, oversized, and malformed responses default to true.
    """

    def __init__(
        self,
        message: str,
        code: str = "model-provider",
        *,
        dispatched: bool | None = None,
    ) -> None:
        super().__init__(message, code)
        if dispatched is None:
            self.dispatched = code not in _PRE_DISPATCH_TRANSPORT_CODES
        else:
            self.dispatched = dispatched
