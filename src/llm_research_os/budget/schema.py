"""Deterministic JSON Schema generation for budget-limit request contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.budget.requests import (
    BUDGET_LIMIT_REQUEST_SCHEMA_ID,
    BudgetLimitRequestDocument,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT


def build_budget_limit_request_schema() -> dict[str, Any]:
    generated = BudgetLimitRequestDocument.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": BUDGET_LIMIT_REQUEST_SCHEMA_ID, **generated}


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_budget_limit_request_schema() -> str:
    return _canonical(build_budget_limit_request_schema())


def write_budget_limit_request_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_budget_limit_request_schema(), encoding="utf-8")


def budget_limit_request_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_budget_limit_request_schema()
    except OSError:
        return False
