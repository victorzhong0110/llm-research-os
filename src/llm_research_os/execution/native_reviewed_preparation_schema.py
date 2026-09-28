"""JSON Schema generation for reviewed-native preparation documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.execution.native_reviewed_material import (
    NativeReviewedCodeReview,
    NativeReviewedDependencyInventory,
    NativeReviewedDependencyLock,
    NativeReviewedInterpreterIdentity,
    NativeReviewedPythonBundle,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NATIVE_REVIEWED_PREPARATION_DIAGNOSIS_SCHEMA_ID,
    NATIVE_REVIEWED_PREPARATION_RECEIPT_SCHEMA_ID,
    NativeReviewedPreparationDiagnosis,
    NativeReviewedPreparationReceipt,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT

NATIVE_REVIEWED_BUNDLE_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-python-bundle/v0alpha1.schema.json"
)
NATIVE_REVIEWED_CODE_REVIEW_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-code-review/v0alpha1.schema.json"
)
NATIVE_REVIEWED_INTERPRETER_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-interpreter-identity/v0alpha1.schema.json"
)
NATIVE_REVIEWED_DEPENDENCY_LOCK_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-dependency-lock/v0alpha1.schema.json"
)
NATIVE_REVIEWED_DEPENDENCY_INVENTORY_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-dependency-inventory/v0alpha1.schema.json"
)


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


def _bind(model: type[Any], schema_id: str) -> tuple[Any, Any, Any, Any]:
    def build() -> dict[str, Any]:
        return _build(model, schema_id)

    def canonical() -> str:
        return _canonical(build())

    def write(path: str | Path) -> None:
        _write(canonical(), path)

    def matches(path: str | Path) -> bool:
        return _matches(canonical(), path)

    return build, canonical, write, matches


(
    build_native_reviewed_preparation_receipt_schema,
    canonical_native_reviewed_preparation_receipt_schema,
    write_native_reviewed_preparation_receipt_schema,
    native_reviewed_preparation_receipt_schema_matches,
) = _bind(NativeReviewedPreparationReceipt, NATIVE_REVIEWED_PREPARATION_RECEIPT_SCHEMA_ID)
(
    build_native_reviewed_preparation_diagnosis_schema,
    canonical_native_reviewed_preparation_diagnosis_schema,
    write_native_reviewed_preparation_diagnosis_schema,
    native_reviewed_preparation_diagnosis_schema_matches,
) = _bind(NativeReviewedPreparationDiagnosis, NATIVE_REVIEWED_PREPARATION_DIAGNOSIS_SCHEMA_ID)
(
    build_native_reviewed_python_bundle_schema,
    canonical_native_reviewed_python_bundle_schema,
    write_native_reviewed_python_bundle_schema,
    native_reviewed_python_bundle_schema_matches,
) = _bind(NativeReviewedPythonBundle, NATIVE_REVIEWED_BUNDLE_SCHEMA_ID)
(
    build_native_reviewed_code_review_schema,
    canonical_native_reviewed_code_review_schema,
    write_native_reviewed_code_review_schema,
    native_reviewed_code_review_schema_matches,
) = _bind(NativeReviewedCodeReview, NATIVE_REVIEWED_CODE_REVIEW_SCHEMA_ID)
(
    build_native_reviewed_interpreter_identity_schema,
    canonical_native_reviewed_interpreter_identity_schema,
    write_native_reviewed_interpreter_identity_schema,
    native_reviewed_interpreter_identity_schema_matches,
) = _bind(NativeReviewedInterpreterIdentity, NATIVE_REVIEWED_INTERPRETER_SCHEMA_ID)
(
    build_native_reviewed_dependency_lock_schema,
    canonical_native_reviewed_dependency_lock_schema,
    write_native_reviewed_dependency_lock_schema,
    native_reviewed_dependency_lock_schema_matches,
) = _bind(NativeReviewedDependencyLock, NATIVE_REVIEWED_DEPENDENCY_LOCK_SCHEMA_ID)
(
    build_native_reviewed_dependency_inventory_schema,
    canonical_native_reviewed_dependency_inventory_schema,
    write_native_reviewed_dependency_inventory_schema,
    native_reviewed_dependency_inventory_schema_matches,
) = _bind(NativeReviewedDependencyInventory, NATIVE_REVIEWED_DEPENDENCY_INVENTORY_SCHEMA_ID)
