"""Deterministic JSON Schema generation for the R16 trial contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.recovery.trial import TRIAL_RECORD_SCHEMA_ID, TrialKit, TrialRecord
from llm_research_os.spec.schema import SCHEMA_DIALECT

TRIAL_KIT_SCHEMA_ID = "https://researchos.dev/schemas/trial-kit/v0alpha1.schema.json"


def _build(model: type[Any], schema_id: str) -> dict[str, Any]:
    generated = model.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": schema_id, **generated}


def _canonical(model: type[Any], schema_id: str) -> str:
    schema = _build(model, schema_id)
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _matches(canonical: str, path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical
    except OSError:
        return False


def canonical_trial_record_schema() -> str:
    return _canonical(TrialRecord, TRIAL_RECORD_SCHEMA_ID)


def write_trial_record_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_trial_record_schema(), encoding="utf-8")


def trial_record_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_trial_record_schema(), path)


def canonical_trial_kit_schema() -> str:
    return _canonical(TrialKit, TRIAL_KIT_SCHEMA_ID)


def write_trial_kit_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_trial_kit_schema(), encoding="utf-8")


def trial_kit_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_trial_kit_schema(), path)
