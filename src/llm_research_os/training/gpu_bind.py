"""Bind a pinned ms-swift plan to a GPU execution command. Does not launch."""

from __future__ import annotations

from typing import Literal

from llm_research_os.canonical import content_digest
from llm_research_os.training.errors import TrainingBackendError
from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import TrainingBackendPlan

ResumeMode = Literal["none", "adapter-only", "full-checkpoint"]
FULL_CHECKPOINT_LOADS = (
    "weights",
    "optimizer",
    "scheduler",
    "rng",
    "global_step",
)
ADAPTER_ONLY_LOADS = ("adapter_weights",)
_OUTPUT_MOUNT = "/work/output"
_FORBIDDEN_OVERLAY_FLAGS = frozenset(
    {
        "--gpus",
        "--privileged",
        "--resume_only_model",
        "--network",
        "--mount",
    }
)


def command_digest(argv: tuple[str, ...]) -> str:
    return content_digest({"argv": list(argv)})


def plan_document_digest(plan: TrainingBackendPlan) -> str:
    return content_digest(plan.model_dump(mode="json", by_alias=True))


def resume_loads(mode: ResumeMode) -> tuple[str, ...]:
    if mode == "full-checkpoint":
        return FULL_CHECKPOINT_LOADS
    if mode == "adapter-only":
        return ADAPTER_ONLY_LOADS
    return ()


def apply_resume_overlay(
    argv: tuple[str, ...],
    *,
    mode: ResumeMode = "none",
    checkpoint_path: str | None = None,
    output_prefix: str = _OUTPUT_MOUNT,
) -> tuple[str, ...]:
    """Append resume flags. This is a new execution object, not a silent rerun."""

    if any(flag in argv for flag in _FORBIDDEN_OVERLAY_FLAGS):
        raise TrainingBackendError(
            "training argv requested a forbidden host mapping",
            code="gpu-mount-forbidden",
        )
    if "--resume_from_checkpoint" in argv or "--adapters" in argv:
        raise TrainingBackendError(
            "training argv already contains a resume flag",
            code="resume-overlay-conflict",
        )
    if mode == "none":
        if checkpoint_path is not None:
            raise TrainingBackendError(
                "checkpoint path is forbidden when resume is none",
                code="resume-overlay-conflict",
            )
        return argv
    prefix = f"{output_prefix}/"
    if checkpoint_path is None or not checkpoint_path.startswith(prefix):
        raise TrainingBackendError(
            "resume checkpoint is not under the authorized output mount",
            code="gpu-mount-forbidden",
        )
    flag = "--resume_from_checkpoint" if mode == "full-checkpoint" else "--adapters"
    return (*argv, flag, checkpoint_path)


def bind_ms_swift_gpu_command(
    plan: TrainingBackendPlan,
    *,
    resume_mode: ResumeMode = "none",
    checkpoint_path: str | None = None,
) -> tuple[tuple[str, ...], str]:
    """Map the pinned plan to argv and its digest. MUST NOT subprocess."""

    receipt = plan_ms_swift(plan)
    argv = apply_resume_overlay(
        receipt.argv,
        mode=resume_mode,
        checkpoint_path=checkpoint_path,
    )
    return argv, command_digest(argv)
