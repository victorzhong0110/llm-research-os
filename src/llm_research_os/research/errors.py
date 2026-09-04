"""Fail-closed errors for research decision objects. Messages must not echo text fields."""

from pydantic import ValidationError


class ResearchDecisionError(ValueError):
    """Fail-closed error from proposal, dissent, decision, or ledger code.

    Messages MUST NOT include rationale, objection statements, predictions, or
    other payload text (TM-022).
    """

    def __init__(self, message: str, code: str = "research-decision") -> None:
        super().__init__(message)
        self.code = code


class ResearchPayloadError(ResearchDecisionError):
    """An identified research event type carried a structurally invalid payload."""


class ResearchLedgerError(ResearchDecisionError):
    """Illegal cross-event invariant on the research ledger fold."""


class ResearchControlError(ResearchDecisionError):
    """Fail-closed error from the project-scoped research append boundary."""


class ResearchRequestError(ValueError):
    """Invalid external proposal, dissent, or decision request document."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("research request failed validation")
        self.error = error
        self.code = "research-request"
