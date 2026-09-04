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
    schema = {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **generated}
    _forbid_null_optional_digest(schema, "RunDigests", "decisionDigest")
    _forbid_null_root_union(schema, "consumedAuthorization")
    return schema


def _forbid_null_optional_digest(schema: dict[str, Any], definition: str, field: str) -> None:
    """Replace Pydantic's ``anyOf: [string, null]`` with a tagged string.

    Optional digests may be omitted, but JSON ``null`` is not a legal value.
    The generator shape is fail-closed: a missing definition, field, or string
    alternative raises so a Pydantic change cannot republish a nullable contract.
    """

    _forbid_null_union(schema, definition, field)


def _forbid_null_union(schema: dict[str, Any], definition: str, field: str) -> None:
    location = f"$defs.{definition}.properties.{field}"
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError(f"schema is missing $defs while forbidding null on {location}")
    binding = definitions.get(definition)
    if type(binding) is not dict:
        raise ValueError(f"schema is missing {location} definition")
    properties = binding.get("properties")
    if type(properties) is not dict:
        raise ValueError(f"schema is missing {location} properties")
    properties[field] = _non_null_alternative(properties.get(field), location)


def _forbid_null_root_union(schema: dict[str, Any], field: str) -> None:
    location = f"properties.{field}"
    properties = schema.get("properties")
    if type(properties) is not dict:
        raise ValueError(f"schema is missing {location}")
    properties[field] = _non_null_alternative(properties.get(field), location)


def _non_null_alternative(node: object, location: str) -> dict[str, Any]:
    if type(node) is not dict:
        raise ValueError(f"schema is missing {location}")
    alternatives = node.get("anyOf")
    if type(alternatives) is not list:
        raise ValueError(f"schema {location} is not an anyOf union")
    kept = [item for item in alternatives if type(item) is dict and item.get("type") != "null"]
    if len(kept) != 1:
        raise ValueError(f"schema {location} anyOf has no unique non-null alternative")
    return kept[0]


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
