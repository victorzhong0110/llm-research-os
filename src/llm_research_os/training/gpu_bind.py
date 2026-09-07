"""Bind a pinned ms-swift plan to a GPU execution command. Does not launch."""

from __future__ import annotations

from llm_research_os.canonical import content_digest
from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import TrainingBackendPlan


def command_digest(argv: tuple[str, ...]) -> str:
    return content_digest({"argv": list(argv)})


def plan_document_digest(plan: TrainingBackendPlan) -> str:
    return content_digest(plan.model_dump(mode="json", by_alias=True))


def bind_ms_swift_gpu_command(plan: TrainingBackendPlan) -> tuple[tuple[str, ...], str]:
    """Map the pinned plan to argv and its digest. MUST NOT subprocess."""

    receipt = plan_ms_swift(plan)
    argv = receipt.argv
    return argv, command_digest(argv)
