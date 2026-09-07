"""Closed TrainingBackendPlan for one pinned ms-swift SFT shape. Does not execute."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from llm_research_os.events.models import EventDocumentModel
from llm_research_os.spec.io import load_document
from llm_research_os.training.errors import TrainingBackendRequestError

TRAINING_BACKEND_PLAN_SCHEMA_ID = (
    "https://researchos.dev/schemas/training-backend-plan/v0alpha1.schema.json"
)
TRAINING_BACKEND_PLAN_API_VERSION = "researchos.dev/v0alpha1"


class TrainingBackendPlan(EventDocumentModel):
    """One pinned ms-swift SFT plan. Extra fields and other backends fail closed."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["TrainingBackendPlan"]
    backend_id: Literal["ms-swift"] = Field(alias="backendId")
    backend_version: Literal["4.5.2"] = Field(alias="backendVersion")
    model: Literal["Qwen/Qwen2.5-0.5B-Instruct"]
    dataset: Literal["AI-ModelScope/alpaca-gpt4-data-en#8"]
    tuner_type: Literal["lora"] = Field(alias="tunerType")
    torch_dtype: Literal["bfloat16"] = Field(alias="torchDtype")
    max_steps: Literal[1] = Field(alias="maxSteps")
    per_device_train_batch_size: Literal[1] = Field(alias="perDeviceTrainBatchSize")
    gradient_accumulation_steps: Literal[1] = Field(alias="gradientAccumulationSteps")
    learning_rate: Literal["1e-4"] = Field(alias="learningRate")
    lora_rank: Literal[8] = Field(alias="loraRank")
    lora_alpha: Literal[16] = Field(alias="loraAlpha")
    output_dir: Literal["/work/output"] = Field(alias="outputDir")
    save_steps: Literal[1] = Field(alias="saveSteps")
    logging_steps: Literal[1] = Field(alias="loggingSteps")
    max_length: Literal[512] = Field(alias="maxLength")


def load_training_backend_plan(path: str | Path) -> TrainingBackendPlan:
    try:
        return TrainingBackendPlan.model_validate(load_document(path))
    except ValidationError as exc:
        raise TrainingBackendRequestError(exc) from exc
