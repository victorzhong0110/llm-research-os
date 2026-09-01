"""JSON Schema generation for NativeProcessPreflightRequest v0alpha1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.execution.native_preflight_documents import (
    NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA_ID,
    NativeProcessPreflightRequestDocument,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT

SCHEMA_ID = NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA_ID


def build_schema() -> dict[str, Any]:
    generated = NativeProcessPreflightRequestDocument.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **generated}


def canonical_schema() -> str:
    return json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_schema(), encoding="utf-8")


def schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_schema()
    except OSError:
        return False
