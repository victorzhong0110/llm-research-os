"""Deterministic JSON Schema generation for model-provider contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_research_os.providers.models import MODEL_FIXTURE_SCHEMA_ID, ModelFixtureDocument
from llm_research_os.providers.requests import (
    MODEL_GENERATE_REQUEST_SCHEMA_ID,
    ModelGenerateRequestDocument,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT


def _build(
    model: type[Any],
    schema_id: str,
    patch: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    generated = model.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    schema = {"$schema": SCHEMA_DIALECT, "$id": schema_id, **generated}
    if patch is not None:
        patch(schema)
    return schema


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write(schema: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_canonical(schema), encoding="utf-8")


def _matches(schema: dict[str, Any], path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == _canonical(schema)
    except OSError:
        return False


def _patch_generate_request(schema: dict[str, Any]) -> None:
    events = schema.get("properties", {}).get("events")
    if type(events) is not dict:
        raise ValueError("model generate request schema is missing events")
    events["minProperties"] = 2
    events["maxProperties"] = 2
    events["required"] = ["ai.call.started", "ai.call.completed"]


def build_model_generate_request_schema() -> dict[str, Any]:
    return _build(
        ModelGenerateRequestDocument,
        MODEL_GENERATE_REQUEST_SCHEMA_ID,
        _patch_generate_request,
    )


def build_model_fixture_schema() -> dict[str, Any]:
    return _build(ModelFixtureDocument, MODEL_FIXTURE_SCHEMA_ID)


def canonical_model_generate_request_schema() -> str:
    return _canonical(build_model_generate_request_schema())


def write_model_generate_request_schema(path: str | Path) -> None:
    _write(build_model_generate_request_schema(), path)


def model_generate_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_model_generate_request_schema(), path)


def canonical_model_fixture_schema() -> str:
    return _canonical(build_model_fixture_schema())


def write_model_fixture_schema(path: str | Path) -> None:
    _write(build_model_fixture_schema(), path)


def model_fixture_schema_matches(path: str | Path) -> bool:
    return _matches(build_model_fixture_schema(), path)
