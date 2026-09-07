"""Fail-closed errors for the M1 checkpoint integration path."""

from llm_research_os.research.errors import ResearchDecisionError


class M1CheckpointError(ResearchDecisionError):
    """The checkpoint corpus or replayed chain does not satisfy the integration contract.

    Messages MUST NOT include rationale, objections, predictions, prompt, or output
    text (TM-022).
    """
