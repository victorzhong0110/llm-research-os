"""Fail-closed budget errors. Messages must not echo secrets or prompt text."""

from pydantic import ValidationError


class BudgetError(ValueError):
    """Fail-closed error from the budget boundary."""

    def __init__(self, message: str, code: str = "budget") -> None:
        super().__init__(message)
        self.code = code


class BudgetExceededError(BudgetError):
    """A reservation would exceed the declared cap. The exceeded fact is already committed."""

    def __init__(self, message: str = "budget cap exceeded", code: str = "budget-exceeded") -> None:
        super().__init__(message, code=code)


class BudgetCallError(BudgetError):
    """Fail-closed error from recording ``budget.*`` facts."""


class BudgetPayloadError(BudgetError):
    """An identified ``budget.*`` event carried a structurally invalid payload."""


class BudgetRequestError(ValueError):
    """Invalid external budget fields on a generate request."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("budget request failed validation")
        self.error = error
        self.code = "budget-request"
