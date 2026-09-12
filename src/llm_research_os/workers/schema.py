"""Deterministic JSON Schema generation for Worker and grant request contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.spec.schema import SCHEMA_DIALECT
from llm_research_os.workers.requests import (
    AUTHORIZATION_GRANT_REQUEST_SCHEMA_ID,
    WORKER_REGISTER_REQUEST_SCHEMA_ID,
    AuthorizationGrantRequestDocument,
    WorkerRegisterRequestDocument,
)


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_worker_register_request_schema() -> dict[str, Any]:
    generated = WorkerRegisterRequestDocument.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": WORKER_REGISTER_REQUEST_SCHEMA_ID, **generated}


def canonical_worker_register_request_schema() -> str:
    return _canonical(build_worker_register_request_schema())


def write_worker_register_request_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_worker_register_request_schema(), encoding="utf-8")


def worker_register_request_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical_worker_register_request_schema()
    except OSError:
        return False


def build_authorization_grant_request_schema() -> dict[str, Any]:
    generated = AuthorizationGrantRequestDocument.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {"$schema": SCHEMA_DIALECT, "$id": AUTHORIZATION_GRANT_REQUEST_SCHEMA_ID, **generated}


def canonical_authorization_grant_request_schema() -> str:
    return _canonical(build_authorization_grant_request_schema())


def write_authorization_grant_request_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_authorization_grant_request_schema(), encoding="utf-8")


def authorization_grant_request_schema_matches(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return (
            candidate.read_text(encoding="utf-8") == canonical_authorization_grant_request_schema()
        )
    except OSError:
        return False
