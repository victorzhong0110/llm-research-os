"""Fail-closed errors for the shared application service."""


class ApplicationError(ValueError):
    """A command was refused or its dispatched outcome requires reconciliation.

    An error does not imply rollback of an already reserved or dispatched effect.

    ``code`` is a stable machine identifier. ``message`` must not include
    document bodies, credentials, or raw host paths.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
