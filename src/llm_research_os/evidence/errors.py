"""Fail-closed errors for evidence import. Messages must not echo source text or paths."""

from pydantic import ValidationError


class EvidenceError(ValueError):
    """Fail-closed error from the evidence-import boundary.

    Messages MUST NOT include source paths, extracted text, or license
    rationale bodies (TM-006, TM-007, TM-022).
    """

    def __init__(self, message: str, code: str = "evidence") -> None:
        super().__init__(message)
        self.code = code


class EvidenceExtractError(EvidenceError):
    """The local file could not be read or converted to text."""


class EvidenceRightsError(EvidenceError):
    """Unknown rights cannot authorize training or redistribution."""


class EvidenceCallError(EvidenceError):
    """Fail-closed error from recording ``evidence.imported`` facts."""


class EvidencePayloadError(EvidenceError):
    """An identified ``evidence.imported`` event carried a structurally invalid payload."""


class EvidenceRequestError(ValueError):
    """Invalid external evidence import request or citation document."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("evidence request failed validation")
        self.error = error
        self.code = "evidence-request"
