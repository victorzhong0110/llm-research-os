"""Deterministic JSON Schema generation for block command reports v0alpha1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.reports import BLOCK_COMMAND_REPORT_ADAPTER
from llm_research_os.spec.schema import SCHEMA_DIALECT

SCHEMA_ID = "https://researchos.dev/schemas/block-command-report/v0alpha1.schema.json"


def build_schema() -> dict[str, Any]:
    generated = BLOCK_COMMAND_REPORT_ADAPTER.json_schema(
        by_alias=True,
        mode="serialization",
        ref_template="#/$defs/{model}",
    )
    manifest_schema = BlockManifest.model_json_schema(
        by_alias=True,
        mode="serialization",
        ref_template="#/$defs/{model}",
    )
    manifest_definitions = manifest_schema.pop("$defs", {})
    generated["$defs"].update(manifest_definitions)
    generated["$defs"]["BlockManifest"] = manifest_schema
    registry_entry = generated["$defs"]["BlockRegistryEntry"]
    registry_entry["properties"]["manifest"] = {
        "anyOf": [
            {"$ref": "#/$defs/BlockManifest"},
            {"type": "null"},
        ]
    }
    registry_report = generated["$defs"]["BlockRegistryReport"]
    registry_report["allOf"] = [
        {
            "if": {
                "properties": {"operation": {"const": "list"}},
                "required": ["operation"],
            },
            "then": {
                "properties": {
                    "blocks": {
                        "items": {"not": {"required": ["manifest"]}},
                    }
                }
            },
        },
        {
            "if": {
                "properties": {"operation": {"const": "show"}},
                "required": ["operation"],
            },
            "then": {
                "properties": {
                    "blocks": {
                        "minItems": 1,
                        "maxItems": 1,
                        "items": {
                            "required": ["manifest"],
                            "properties": {"manifest": {"not": {"type": "null"}}},
                        },
                    }
                }
            },
        },
    ]
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
