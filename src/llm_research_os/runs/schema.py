"""Deterministic JSON Schema generation for RunSnapshot v0alpha1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.runs.models import MAX_ATTEMPTS, RUN_SNAPSHOT_SCHEMA_ID, RunSnapshot
from llm_research_os.spec.schema import SCHEMA_DIALECT

SCHEMA_ID = RUN_SNAPSHOT_SCHEMA_ID


def build_schema() -> dict[str, Any]:
    generated = RunSnapshot.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    attempts = generated.get("properties", {}).get("attempts")
    if isinstance(attempts, dict):
        attempts["maxItems"] = MAX_ATTEMPTS
    attempt_snapshot = generated.get("$defs", {}).get("AttemptSnapshot", {})
    attempt_properties = attempt_snapshot.get("properties", {})
    if isinstance(attempt_properties, dict):
        ordinal = attempt_properties.get("ordinal")
        if isinstance(ordinal, dict):
            ordinal["maximum"] = MAX_ATTEMPTS
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
