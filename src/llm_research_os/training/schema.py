"""Deterministic JSON Schema for TrainingBackendPlan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.spec.schema import SCHEMA_DIALECT
from llm_research_os.training.checkpoint import (
    GPU_DATA_CHECKPOINT_SCHEMA_ID,
    GpuDataCheckpointBinding,
)
from llm_research_os.training.requests import (
    MAC_MPS_TRAINING_PLAN_SCHEMA_ID,
    TRAINING_BACKEND_PLAN_SCHEMA_ID,
    MacMpsTrainingPlan,
    TrainingBackendPlan,
)


def build_training_backend_plan_schema() -> dict[str, Any]:
    generated = TrainingBackendPlan.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": TRAINING_BACKEND_PLAN_SCHEMA_ID, **generated}


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_training_backend_plan_schema() -> str:
    return _canonical(build_training_backend_plan_schema())


def write_training_backend_plan_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_training_backend_plan_schema(), encoding="utf-8")


def training_backend_plan_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_training_backend_plan_schema()
    except OSError:
        return False


def build_gpu_data_checkpoint_schema() -> dict[str, Any]:
    generated = GpuDataCheckpointBinding.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": GPU_DATA_CHECKPOINT_SCHEMA_ID, **generated}


def canonical_gpu_data_checkpoint_schema() -> str:
    return _canonical(build_gpu_data_checkpoint_schema())


def write_gpu_data_checkpoint_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_gpu_data_checkpoint_schema(), encoding="utf-8")


def gpu_data_checkpoint_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_gpu_data_checkpoint_schema()
    except OSError:
        return False


def build_mac_mps_training_plan_schema() -> dict[str, Any]:
    generated = MacMpsTrainingPlan.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": MAC_MPS_TRAINING_PLAN_SCHEMA_ID, **generated}


def canonical_mac_mps_training_plan_schema() -> str:
    return _canonical(build_mac_mps_training_plan_schema())


def write_mac_mps_training_plan_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_mac_mps_training_plan_schema(), encoding="utf-8")


def mac_mps_training_plan_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_mac_mps_training_plan_schema()
    except OSError:
        return False
