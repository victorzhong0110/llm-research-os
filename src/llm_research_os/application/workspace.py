"""Workspace binding for project identity, EventStore, CAS, and Worker roots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.events.models import EventIdentifier
from llm_research_os.research.models import ResearchDocumentModel

_MANIFEST_NAME = "workspace.json"
_RECEIPT_NAME = "operation-receipts.sqlite"


class _ProjectId(ResearchDocumentModel):
    project_id: EventIdentifier = Field(alias="projectId")


@dataclass(frozen=True, slots=True)
class Workspace:
    """Paths bound to one project. Relative manifest paths stay workspace-relative."""

    root: Path
    project_id: str
    control_db: Path
    cas_root: Path
    worker_root: Path
    manifest_control_db: str
    manifest_cas_root: str
    manifest_worker_root: str
    receipt_db: Path

    def describe(self) -> dict[str, str]:
        return {
            "projectId": self.project_id,
            "controlDb": self.manifest_control_db,
            "casRoot": self.manifest_cas_root,
            "workerRoot": self.manifest_worker_root,
        }


def init_workspace(
    root: Path,
    *,
    project_id: str,
    control_db: Path,
    cas_root: Path,
    worker_root: Path,
) -> Workspace:
    """Create a workspace manifest. Relative inputs are resolved under ``root``."""

    try:
        _ProjectId.model_validate({"projectId": project_id})
    except ValidationError as exc:
        raise ApplicationError("project-invalid", "project id is not a valid identifier") from exc
    workspace_root = root.resolve()
    if workspace_root.exists() and not workspace_root.is_dir():
        raise ApplicationError("workspace-invalid", "workspace root is not a directory")
    if (workspace_root / _MANIFEST_NAME).exists():
        raise ApplicationError("workspace-exists", "workspace manifest already exists")
    control = _resolve_under(workspace_root, control_db)
    cas = _resolve_under(workspace_root, cas_root)
    worker = _resolve_under(workspace_root, worker_root)
    receipt = workspace_root / _RECEIPT_NAME
    _reject_shared_roots(control, cas, worker, receipt)
    workspace_root.mkdir(parents=True, exist_ok=True)
    cas.mkdir(parents=True, exist_ok=True)
    worker.mkdir(parents=True, exist_ok=True)
    control.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "projectId": project_id,
        "controlDb": _display(workspace_root, control),
        "casRoot": _display(workspace_root, cas),
        "workerRoot": _display(workspace_root, worker),
    }
    (workspace_root / _MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_workspace(workspace_root)


def load_workspace(root: Path) -> Workspace:
    """Open a workspace and refuse overlapping control and Worker roots."""

    workspace_root = root.resolve()
    manifest_path = workspace_root / _MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApplicationError("workspace-invalid", "workspace manifest could not be read") from exc
    if type(payload) is not dict:
        raise ApplicationError("workspace-invalid", "workspace manifest is not an object")
    project_id = payload.get("projectId")
    control_name = payload.get("controlDb")
    cas_name = payload.get("casRoot")
    worker_name = payload.get("workerRoot")
    if (
        type(project_id) is not str
        or type(control_name) is not str
        or type(cas_name) is not str
        or type(worker_name) is not str
    ):
        raise ApplicationError("workspace-invalid", "workspace manifest fields are invalid")
    try:
        _ProjectId.model_validate({"projectId": project_id})
    except ValidationError as exc:
        raise ApplicationError("project-invalid", "project id is not a valid identifier") from exc
    control = _resolve_under(workspace_root, Path(control_name))
    cas = _resolve_under(workspace_root, Path(cas_name))
    worker = _resolve_under(workspace_root, Path(worker_name))
    receipt = workspace_root / _RECEIPT_NAME
    _reject_shared_roots(control, cas, worker, receipt)
    return Workspace(
        root=workspace_root,
        project_id=project_id,
        control_db=control,
        cas_root=cas,
        worker_root=worker,
        manifest_control_db=control_name,
        manifest_cas_root=cas_name,
        manifest_worker_root=worker_name,
        receipt_db=receipt,
    )


def _resolve_under(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def _display(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _reject_shared_roots(
    control_db: Path, cas_root: Path, worker_root: Path, receipt_db: Path
) -> None:
    control_dir = control_db.parent
    if _overlaps(control_dir, worker_root) or _overlaps(control_db, worker_root):
        raise ApplicationError(
            "shared-root",
            "control database and Worker root must not overlap",
        )
    if _overlaps(cas_root, worker_root):
        raise ApplicationError(
            "shared-root",
            "CAS root and Worker root must not overlap",
        )
    if receipt_db == control_db or _overlaps(receipt_db, worker_root):
        raise ApplicationError(
            "shared-root",
            "operation receipts must not share the control database or Worker root",
        )
