"""Generated JSON Schema contracts for native output transfer v0alpha1."""

from __future__ import annotations

from pathlib import Path

from llm_research_os.execution.native_reviewed_schema import _canonical, _matches, _write
from llm_research_os.spec.schema import SCHEMA_DIALECT
from llm_research_os.workers.native_output_documents import (
    NativeOutputReceipt,
    NativeReviewedTaskOutput,
)


def canonical_native_task_output_schema() -> str:
    return _canonical(
        {
            "$schema": SCHEMA_DIALECT,
            "$id": "https://researchos.dev/schemas/native-reviewed-task-output/v0alpha1.schema.json",
            **NativeReviewedTaskOutput.model_json_schema(by_alias=True, mode="validation"),
        }
    )


def native_task_output_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_task_output_schema(), path)


def write_native_task_output_schema(path: str | Path) -> None:
    _write(canonical_native_task_output_schema(), path)


def canonical_native_output_receipt_schema() -> str:
    return _canonical(
        {
            "$schema": SCHEMA_DIALECT,
            "$id": "https://researchos.dev/schemas/native-output-receipt/v0alpha1.schema.json",
            **NativeOutputReceipt.model_json_schema(by_alias=True, mode="validation"),
        }
    )


def native_output_receipt_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_output_receipt_schema(), path)


def write_native_output_receipt_schema(path: str | Path) -> None:
    _write(canonical_native_output_receipt_schema(), path)
