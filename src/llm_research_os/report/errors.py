"""Fail-closed errors for static Run reports. Reports are projections, not facts."""


class ReportError(ValueError):
    """Fail-closed error while rebuilding or rendering a Run report."""

    def __init__(self, message: str, code: str = "report") -> None:
        super().__init__(message)
        self.code = code
