"""Structured, redaction-safe errors for the local API.

Every failure a browser can observe is one of these. Messages are fixed
operator text, never an interpolated exception, host path, document body, or
credential: the local API is a read surface, and its error text is attacker
reachable through the Host/Origin boundary.
"""

from __future__ import annotations

from typing import Any, Literal

LOCAL_API_VERSION = "researchos.dev/local-api/v0alpha1"

ApiErrorCode = Literal[
    "body-too-large",
    "concurrency-exhausted",
    "command-refused",
    "content-type-unsupported",
    "csrf-invalid",
    "document-hostile",
    "document-invalid",
    "event-store-unavailable",
    "host-forbidden",
    "internal-error",
    "method-not-allowed",
    "not-found",
    "origin-forbidden",
    "parameter-invalid",
    "query-timeout",
    "session-expired",
    "session-required",
    "bootstrap-invalid",
    "bootstrap-consumed",
    "workspace-invalid",
]


class LocalApiError(Exception):
    """One safe-to-render API failure with a stable machine code."""

    def __init__(self, code: ApiErrorCode, message: str, *, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def document(self) -> dict[str, Any]:
        """The rendered error body. Contains no request echo and no host detail."""

        return {
            "apiVersion": LOCAL_API_VERSION,
            "kind": "LocalApiError",
            "code": self.code,
            "message": self.message,
        }


def bad_request(code: ApiErrorCode, message: str) -> LocalApiError:
    return LocalApiError(code, message, status=400)


def forbidden(code: ApiErrorCode, message: str) -> LocalApiError:
    return LocalApiError(code, message, status=403)


def not_found(message: str) -> LocalApiError:
    return LocalApiError("not-found", message, status=404)
