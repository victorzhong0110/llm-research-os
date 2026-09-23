"""JSON Schema generation for reviewed native execution v0alpha1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.execution.native_reviewed_documents import (
    NATIVE_REVIEWED_REPORT_SCHEMA_ID,
    NATIVE_REVIEWED_REQUEST_SCHEMA_ID,
    NativeReviewedExecutionReport,
    NativeReviewedExecutionRequest,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT


def _omit_null_defaults(node: Any) -> None:
    """Optional JSON fields are omitted. Explicit null is not a second form."""

    if isinstance(node, dict):
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and any(
            isinstance(item, dict) and item.get("type") == "null" for item in any_of
        ):
            kept = [
                item
                for item in any_of
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]
            if len(kept) == 1 and isinstance(kept[0], dict):
                replacement = dict(kept[0])
                for key, value in node.items():
                    if key not in {"anyOf", "default"} and key not in replacement:
                        replacement[key] = value
                node.clear()
                node.update(replacement)
        for value in node.values():
            _omit_null_defaults(value)
    elif isinstance(node, list):
        for item in node:
            _omit_null_defaults(item)


def _build(model: type[Any], schema_id: str) -> dict[str, Any]:
    generated = model.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    _omit_null_defaults(generated)
    return {"$schema": SCHEMA_DIALECT, "$id": schema_id, **generated}


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write(canonical: str, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical, encoding="utf-8")


def _matches(canonical: str, path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical
    except OSError:
        return False


def build_native_reviewed_execution_request_schema() -> dict[str, Any]:
    return _build(NativeReviewedExecutionRequest, NATIVE_REVIEWED_REQUEST_SCHEMA_ID)


def canonical_native_reviewed_execution_request_schema() -> str:
    return _canonical(build_native_reviewed_execution_request_schema())


def write_native_reviewed_execution_request_schema(path: str | Path) -> None:
    _write(canonical_native_reviewed_execution_request_schema(), path)


def native_reviewed_execution_request_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_reviewed_execution_request_schema(), path)


def build_native_reviewed_execution_report_schema() -> dict[str, Any]:
    return _build(NativeReviewedExecutionReport, NATIVE_REVIEWED_REPORT_SCHEMA_ID)


def canonical_native_reviewed_execution_report_schema() -> str:
    return _canonical(build_native_reviewed_execution_report_schema())


def write_native_reviewed_execution_report_schema(path: str | Path) -> None:
    _write(canonical_native_reviewed_execution_report_schema(), path)


def native_reviewed_execution_report_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_native_reviewed_execution_report_schema(), path)
