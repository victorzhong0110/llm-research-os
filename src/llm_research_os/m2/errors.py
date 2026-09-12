"""Fail-closed errors for the M2 CPU Worker integration path."""

from llm_research_os.workers.errors import WorkerError


class M2CheckpointError(WorkerError):
    """The M2 corpus or replayed Worker chain does not satisfy the integration contract."""

    def __init__(self, message: str, code: str = "m2-checkpoint") -> None:
        super().__init__(message, code=code)
