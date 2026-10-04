"""Published, deterministic schema for local API response documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from llm_research_os.spec.schema import SCHEMA_DIALECT
from llm_research_os.web.contracts import (
    ArtifactDocument,
    CapabilitiesDocument,
    CommandReceipt,
    DocumentPreviewDocument,
    ErrorDocument,
    EventPageDocument,
    HealthDocument,
    InspectionDocument,
    RevisionPageDocument,
    RunPageDocument,
    SessionDocument,
    WorkspaceDocument,
)

ResponseDocument = (
    ArtifactDocument
    | CapabilitiesDocument
    | CommandReceipt
    | DocumentPreviewDocument
    | ErrorDocument
    | EventPageDocument
    | HealthDocument
    | InspectionDocument
    | RevisionPageDocument
    | RunPageDocument
    | SessionDocument
    | WorkspaceDocument
)


def build_schema() -> dict[str, Any]:
    schema = TypeAdapter(ResponseDocument).json_schema(by_alias=True)
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": "https://researchos.dev/schemas/local-api-response/v0alpha1.schema.json",
        **schema,
    }


def canonical_schema() -> str:
    return json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_schema(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_schema(), encoding="utf-8")


def schema_matches(path: str | Path) -> bool:
    try:
        return Path(path).read_text(encoding="utf-8") == canonical_schema()
    except (OSError, UnicodeError):
        return False
