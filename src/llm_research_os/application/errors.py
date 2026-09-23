"""Fail-closed errors for the shared application service."""


class ApplicationError(ValueError):
    """A command was refused before it changed durable operation state.

    ``code`` is a stable machine identifier. ``message`` must not include
    document bodies, credentials, or raw host paths.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
