"""ms-swift 4.5.2 argv mapping. Never launches a process or imports torch."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from llm_research_os.training.errors import TrainingBackendError
from llm_research_os.training.requests import TrainingBackendPlan

SWIFT_ENTRYPOINT = "swift"
SWIFT_SUBCOMMAND = "sft"
PINNED_BACKEND_ID = "ms-swift"
PINNED_BACKEND_VERSION = "4.5.2"


@dataclass(frozen=True, slots=True)
class TrainingBackendReceipt:
    backend_id: str
    backend_version: str
    argv: tuple[str, ...]
    executed: bool
    gpu: str
    backend_installed: bool
    cost_known: bool

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "TrainingBackendPlanReceipt",
            "backendId": self.backend_id,
            "backendVersion": self.backend_version,
            "argv": list(self.argv),
            "executed": self.executed,
            "gpu": self.gpu,
            "backendInstalled": self.backend_installed,
            "costKnown": self.cost_known,
        }


def plan_ms_swift(plan: TrainingBackendPlan) -> TrainingBackendReceipt:
    """Translate the pinned plan to argv. MUST NOT subprocess or claim GPU success."""

    if plan.backend_id != PINNED_BACKEND_ID or plan.backend_version != PINNED_BACKEND_VERSION:
        raise TrainingBackendError(
            "training backend pin mismatch",
            code="backend-pin-mismatch",
        )
    argv = (
        SWIFT_ENTRYPOINT,
        SWIFT_SUBCOMMAND,
        "--model",
        plan.model,
        "--tuner_type",
        plan.tuner_type,
        "--dataset",
        plan.dataset,
        "--torch_dtype",
        plan.torch_dtype,
        "--max_steps",
        str(plan.max_steps),
        "--per_device_train_batch_size",
        str(plan.per_device_train_batch_size),
        "--gradient_accumulation_steps",
        str(plan.gradient_accumulation_steps),
        "--learning_rate",
        plan.learning_rate,
        "--lora_rank",
        str(plan.lora_rank),
        "--lora_alpha",
        str(plan.lora_alpha),
        "--output_dir",
        plan.output_dir,
        "--save_steps",
        str(plan.save_steps),
        "--logging_steps",
        str(plan.logging_steps),
        "--max_length",
        str(plan.max_length),
    )
    return TrainingBackendReceipt(
        backend_id=plan.backend_id,
        backend_version=plan.backend_version,
        argv=argv,
        executed=False,
        gpu="not-run",
        backend_installed=_swift_module_present(),
        cost_known=False,
    )


def _swift_module_present() -> bool:
    """True only when the ms-swift import name is findable. Does not import torch."""

    return importlib.util.find_spec("swift") is not None
