"""Generated schema contracts for remote native start records."""

from __future__ import annotations

from pathlib import Path

from llm_research_os.execution.native_reviewed_schema import _build, _canonical, _matches, _write
from llm_research_os.workers.native_start_documents import NativeStartReceipt, NativeStartRequest


def canonical_native_start_request_schema() -> str:
    return _canonical(
        _build(
            NativeStartRequest,
            "https://researchos.dev/schemas/native-start-request/v0alpha1.schema.json",
        )
    )


def native_start_request_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_start_request_schema(), path)


def write_native_start_request_schema(path: str | Path) -> None:
    _write(canonical_native_start_request_schema(), path)


def canonical_native_start_receipt_schema() -> str:
    return _canonical(
        _build(
            NativeStartReceipt,
            "https://researchos.dev/schemas/native-start-receipt/v0alpha1.schema.json",
        )
    )


def native_start_receipt_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_start_receipt_schema(), path)


def write_native_start_receipt_schema(path: str | Path) -> None:
    _write(canonical_native_start_receipt_schema(), path)
