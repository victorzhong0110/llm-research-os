"""Deterministic JSON Schema generation for application command and receipt contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.application.models import (
    APPLICATION_COMMAND_SCHEMA_ID,
    APPLICATION_RECEIPT_SCHEMA_ID,
    ApplicationCommand,
    ApplicationReceipt,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT


def _build(model: type[Any], schema_id: str) -> dict[str, Any]:
    generated = model.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": schema_id, **generated}


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_application_command_schema() -> dict[str, Any]:
    return _build(ApplicationCommand, APPLICATION_COMMAND_SCHEMA_ID)


def canonical_application_command_schema() -> str:
    return _canonical(build_application_command_schema())


def write_application_command_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_application_command_schema(), encoding="utf-8")


def application_command_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_application_command_schema()
    except OSError:
        return False


def build_application_receipt_schema() -> dict[str, Any]:
    return _build(ApplicationReceipt, APPLICATION_RECEIPT_SCHEMA_ID)


def canonical_application_receipt_schema() -> str:
    return _canonical(build_application_receipt_schema())


def write_application_receipt_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_application_receipt_schema(), encoding="utf-8")


def application_receipt_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_application_receipt_schema(), path)


def _matches(canonical: str, path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical
    except OSError:
        return False
