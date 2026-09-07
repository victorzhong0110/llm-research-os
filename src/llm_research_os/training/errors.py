"""Fail-closed training-backend plan errors. This path does not launch GPU work."""

from pydantic import ValidationError


class TrainingBackendError(ValueError):
    def __init__(self, message: str, code: str = "training-backend") -> None:
        super().__init__(message)
        self.code = code


class TrainingBackendRequestError(ValueError):
    def __init__(self, error: ValidationError) -> None:
        super().__init__("training backend plan failed validation")
        self.error = error
        self.code = "training-backend-request"
