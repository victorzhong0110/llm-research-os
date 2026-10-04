"""Fail-closed errors for installation, backup, restore, and doctor paths."""


class RecoveryError(ValueError):
    """An installation or recovery step was refused.

    ``code`` is a stable machine identifier. ``message`` must not include a
    host path, a document body, a credential, or an object digest that the
    operator did not already print.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class BackupIntegrityError(RecoveryError):
    """A backup or restore source did not match its own manifest.

    Raised instead of a partially applied restore: a backup that cannot be
    verified is never copied into a workspace, so a damaged image can never
    become the new head of a project.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
