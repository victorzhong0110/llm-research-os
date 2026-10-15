"""Deterministic published map composition contract."""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from llm_research_os.dashboard.models import DashboardDocument, DashboardWrite
from llm_research_os.spec.schema import SCHEMA_DIALECT


def build_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": "https://researchos.dev/schemas/dashboard-document/v0alpha1.schema.json",
        **TypeAdapter(DashboardDocument | DashboardWrite).json_schema(by_alias=True),
    }


def canonical_schema() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"


def write_schema(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_schema(), encoding="utf-8")


def schema_matches(path: str | Path) -> bool:
    try:
        return Path(path).read_text(encoding="utf-8") == canonical_schema()
    except (OSError, UnicodeError):
        return False
