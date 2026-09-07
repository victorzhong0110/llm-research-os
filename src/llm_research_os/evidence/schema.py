"""Deterministic JSON Schema generation for evidence contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_research_os.evidence.models import EVIDENCE_CITATION_SCHEMA_ID, EvidenceCitation
from llm_research_os.evidence.requests import (
    EVIDENCE_IMPORT_REQUEST_SCHEMA_ID,
    EvidenceImportRequestDocument,
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


def build_evidence_import_request_schema() -> dict[str, Any]:
    return _build(EvidenceImportRequestDocument, EVIDENCE_IMPORT_REQUEST_SCHEMA_ID)


def build_evidence_citation_schema() -> dict[str, Any]:
    return _build(EvidenceCitation, EVIDENCE_CITATION_SCHEMA_ID)


def canonical_evidence_import_request_schema() -> str:
    return _canonical(build_evidence_import_request_schema())


def write_evidence_import_request_schema(path: str | Path) -> None:
    _write(build_evidence_import_request_schema(), path)


def evidence_import_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_evidence_import_request_schema(), path)


def canonical_evidence_citation_schema() -> str:
    return _canonical(build_evidence_citation_schema())


def write_evidence_citation_schema(path: str | Path) -> None:
    _write(build_evidence_citation_schema(), path)


def evidence_citation_schema_matches(path: str | Path) -> bool:
    return _matches(build_evidence_citation_schema(), path)
