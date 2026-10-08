"""Deterministic JSON Schema generation for the recovery contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_research_os.recovery.models import (
    BACKUP_MANIFEST_SCHEMA_ID,
    BACKUP_MANIFEST_V2_SCHEMA_ID,
    BACKUP_REPORT_SCHEMA_ID,
    DIAGNOSTIC_REPORT_SCHEMA_ID,
    RESTORE_REPORT_SCHEMA_ID,
    BackupManifest,
    BackupManifestV2,
    BackupReport,
    DiagnosticReport,
    RestoreReport,
)
from llm_research_os.recovery.operations import OPERATIONS_SCHEMA_ID, OperationState
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


def _matches(canonical: str, path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == canonical
    except OSError:
        return False


def _emit(model: type[Any], schema_id: str) -> tuple[str, Any]:
    schema = _build(model, schema_id)
    return _canonical(schema), schema


def canonical_backup_manifest_schema() -> str:
    return _emit(BackupManifest, BACKUP_MANIFEST_SCHEMA_ID)[0]


def write_backup_manifest_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_backup_manifest_schema(), encoding="utf-8")


def backup_manifest_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_backup_manifest_schema(), path)


def canonical_backup_report_schema() -> str:
    return _emit(BackupReport, BACKUP_REPORT_SCHEMA_ID)[0]


def write_backup_report_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_backup_report_schema(), encoding="utf-8")


def backup_report_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_backup_report_schema(), path)


def canonical_restore_report_schema() -> str:
    return _emit(RestoreReport, RESTORE_REPORT_SCHEMA_ID)[0]


def write_restore_report_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_restore_report_schema(), encoding="utf-8")


def restore_report_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_restore_report_schema(), path)


def canonical_workspace_diagnostic_schema() -> str:
    return _emit(DiagnosticReport, DIAGNOSTIC_REPORT_SCHEMA_ID)[0]


def write_workspace_diagnostic_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_workspace_diagnostic_schema(), encoding="utf-8")


def workspace_diagnostic_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_workspace_diagnostic_schema(), path)


def canonical_backup_manifest_v2_schema() -> str:
    return _emit(BackupManifestV2, BACKUP_MANIFEST_V2_SCHEMA_ID)[0]


def write_backup_manifest_v2_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_backup_manifest_v2_schema(), encoding="utf-8")


def backup_manifest_v2_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_backup_manifest_v2_schema(), path)


def canonical_operations_backup_schema() -> str:
    return _emit(OperationState, OPERATIONS_SCHEMA_ID)[0]


def write_operations_backup_schema(path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical_operations_backup_schema(), encoding="utf-8")


def operations_backup_schema_matches(path: str | Path) -> bool:
    return _matches(canonical_operations_backup_schema(), path)
