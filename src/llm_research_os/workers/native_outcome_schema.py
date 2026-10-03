"""Generated schema contracts for remote native outcome records."""

from __future__ import annotations

from pathlib import Path

from llm_research_os.execution.native_reviewed_schema import _build, _canonical, _matches, _write
from llm_research_os.workers.native_outcome_documents import (
    NativeOutcomeReceipt,
    NativeOutcomeRequest,
)


def canonical_native_outcome_request_schema() -> str:
    return _canonical(
        _build(
            NativeOutcomeRequest,
            "https://researchos.dev/schemas/native-outcome-request/v0alpha1.schema.json",
        )
    )


def native_outcome_request_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_outcome_request_schema(), path)


def write_native_outcome_request_schema(path: str | Path) -> None:
    _write(canonical_native_outcome_request_schema(), path)


def canonical_native_outcome_receipt_schema() -> str:
    return _canonical(
        _build(
            NativeOutcomeReceipt,
            "https://researchos.dev/schemas/native-outcome-receipt/v0alpha1.schema.json",
        )
    )


def native_outcome_receipt_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_outcome_receipt_schema(), path)


def write_native_outcome_receipt_schema(path: str | Path) -> None:
    _write(canonical_native_outcome_receipt_schema(), path)
