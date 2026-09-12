"""Bind a closed Mac/MPS plan to native-process argv. Isolation is not OCI."""

from __future__ import annotations

from llm_research_os.canonical import content_digest
from llm_research_os.training.errors import TrainingBackendError
from llm_research_os.training.gpu_bind import ResumeMode, apply_resume_overlay, command_digest
from llm_research_os.training.ms_swift import (
    PINNED_BACKEND_ID,
    PINNED_BACKEND_VERSION,
    SWIFT_ENTRYPOINT,
    SWIFT_SUBCOMMAND,
    TrainingBackendReceipt,
)
from llm_research_os.training.requests import MacMpsTrainingPlan

MPS_OUTPUT_DIR: str = "output"
MPS_MODEL_DIR: str = "model"
PINNED_MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


def plan_document_digest(plan: MacMpsTrainingPlan) -> str:
    return content_digest(plan.model_dump(mode="json", by_alias=True))


def plan_ms_swift_mps(plan: MacMpsTrainingPlan) -> TrainingBackendReceipt:
    """Translate the closed MPS plan to argv. MUST NOT subprocess."""

    if plan.backend_id != PINNED_BACKEND_ID or plan.backend_version != PINNED_BACKEND_VERSION:
        raise TrainingBackendError(
            "training backend pin mismatch",
            code="backend-pin-mismatch",
        )
    argv = (
        SWIFT_ENTRYPOINT,
        SWIFT_SUBCOMMAND,
        "--model",
        MPS_MODEL_DIR,
        "--model_revision",
        plan.model_revision,
        "--model_type",
        plan.model_type,
        "--template",
        plan.template,
        "--use_hf",
        "true",
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
        "--seed",
        str(plan.seed),
        "--fp16",
        "false",
        "--bf16",
        "false",
        "--attn_impl",
        "eager",
        "--dataloader_num_workers",
        "0",
        "--eval_strategy",
        "no",
        "--save_total_limit",
        "2",
        "--report_to",
        "none",
        "--add_version",
        "false",
        "--check_model",
        "false",
        "--optim",
        "adamw_torch",
        "--gradient_checkpointing",
        "false",
    )
    return TrainingBackendReceipt(
        backend_id=plan.backend_id,
        backend_version=plan.backend_version,
        argv=argv,
        executed=False,
        gpu="not-run",
        backend_installed=False,
        cost_known=False,
    )


def bind_ms_swift_mps_command(
    plan: MacMpsTrainingPlan,
    *,
    resume_mode: ResumeMode = "none",
    checkpoint_path: str | None = None,
) -> tuple[tuple[str, ...], str]:
    receipt = plan_ms_swift_mps(plan)
    argv = apply_resume_overlay(
        receipt.argv,
        mode=resume_mode,
        checkpoint_path=checkpoint_path,
        output_prefix=MPS_OUTPUT_DIR,
    )
    return argv, command_digest(argv)
