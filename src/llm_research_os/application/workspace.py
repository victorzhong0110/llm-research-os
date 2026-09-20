"""Workspace binding for the R02 application layer.

A workspace ties project identity to one EventStore database, one CAS root,
and exactly one receipt log. It rejects accidental sharing between control
and Worker roots and refuses to write to a directory whose existing
``.researchos/operations.jsonl`` belongs to a different project.

R02 does not embed file change markers; the local EventStore is still the
authoritative fact source. Save/load of immutable ``ResearchSpec``
revisions is delegated to existing artifact and evidence flows, while the
workspace records the artifact digest in its receipt log.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from llm_research_os.application.errors import (
    WorkspaceError,
    WorkspaceRootOverlapError,
    WorkspaceStateError,
)
from llm_research_os.application.receipts import (
    RECEIPT_LOG_NAME,
    RECEIPT_LOG_SUBDIR,
    ReceiptLog,
)

WORKSPACE_CONFIG_NAME = "workspace.json"
WORKSPACE_CONFIG_VERSION = "application.workspace/v0alpha1"


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """Resolved filesystem layout for one workspace."""

    project_id: str
    root: Path
    control_db: Path
    cas_root: Path
    receipt_log: Path
    config_path: Path
    worker_root: Path | None = None
    supplemental_roots: tuple[Path, ...] = field(default_factory=tuple)

    def as_document(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schemaVersion": WORKSPACE_CONFIG_VERSION,
            "projectId": self.project_id,
            "root": str(self.root),
            "controlDb": str(self.control_db),
            "casRoot": str(self.cas_root),
            "receiptLog": str(self.receipt_log),
            "workerRoot": str(self.worker_root) if self.worker_root else None,
            "supplementalRoots": [str(p) for p in self.supplemental_roots],
        }
        return body


def _normalize(root: Path) -> Path:
    return root.expanduser().resolve()


def _check_overlaps(layout: WorkspaceLayout) -> None:
    """Reject sibling roots that share or nest control-plane paths.

    The layout's own control-plane paths may all live under ``layout.root``;
    that is the standard layout. The only overlap this function rejects is:

    - the worker root (if provided) containing a control-plane path, or
    - a control-plane path being identical to the worker root, or
    - a supplementary root duplicating a control-plane path.
    """

    control_paths: tuple[Path, ...] = (
        layout.control_db,
        layout.cas_root,
        layout.receipt_log,
        layout.config_path,
    )
    external_roots: list[tuple[Path, str]] = []
    if layout.worker_root is not None:
        external_roots.append((layout.worker_root, "workerRoot"))
    for path in layout.supplemental_roots:
        external_roots.append((path, "supplementalRoot"))

    for external_root, label in external_roots:
        for control_path in control_paths:
            if control_path == external_root:
                raise WorkspaceRootOverlapError(
                    f"control-plane path {control_path!r} duplicates {label}={external_root!r}"
                )
            try:
                control_path.relative_to(external_root)
            except ValueError:
                continue
            raise WorkspaceRootOverlapError(
                f"control-plane path {control_path!r} is inside {label}={external_root!r}"
            )

    for i, (path_a, label_a) in enumerate(external_roots):
        for path_b, label_b in external_roots[i + 1 :]:
            if path_a == path_b:
                raise WorkspaceRootOverlapError(
                    f"workspace sibling {label_a}={path_a!r} duplicates {label_b}={path_b!r}"
                )
            try:
                path_a.relative_to(path_b)
            except ValueError:
                pass
            else:
                raise WorkspaceRootOverlapError(
                    f"sibling {label_a}={path_a!r} is inside {label_b}={path_b!r}"
                )
            try:
                path_b.relative_to(path_a)
            except ValueError:
                continue
            raise WorkspaceRootOverlapError(
                f"sibling {label_b}={path_b!r} is inside {label_a}={path_a!r}"
            )


def _check_within_control(layout: WorkspaceLayout) -> None:
    """Reject control artifacts leaking into a separate Worker root."""

    if layout.worker_root is None:
        return
    worker_norm = layout.worker_root
    for label, path in (
        ("controlDb", layout.control_db),
        ("casRoot", layout.cas_root),
        ("receiptLog", layout.receipt_log),
        ("config", layout.config_path),
    ):
        try:
            path.relative_to(worker_norm)
        except ValueError:
            continue
        raise WorkspaceRootOverlapError(
            f"control-plane {label}={path!r} is inside worker root={worker_norm!r}"
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    """A bound view of one project's control-plane paths and receipt log."""

    layout: WorkspaceLayout
    receipt_log: ReceiptLog

    @property
    def project_id(self) -> str:
        return self.layout.project_id

    @property
    def root(self) -> Path:
        return self.layout.root

    @property
    def control_db(self) -> Path:
        return self.layout.control_db

    @property
    def cas_root(self) -> Path:
        return self.layout.cas_root

    @property
    def receipt_log_path(self) -> Path:
        return self.layout.receipt_log

    def close(self) -> None:
        return None


def init_workspace(
    *,
    root: Path,
    project_id: str,
    control_db: Path | None = None,
    cas_root: Path | None = None,
    worker_root: Path | None = None,
    supplemental_roots: Iterable[Path] = (),
    receipt_log: Path | None = None,
) -> Workspace:
    """Create a fresh workspace layout.

    The control database file is created in a path of the caller's choice if
    it does not exist. CAS, the receipt log directory, and the workspace
    config are created on disk. The returned ``Workspace`` is immediately
    usable.
    """

    if not project_id or "/" in project_id or "\\" in project_id:
        raise WorkspaceError(f"invalid project_id: {project_id!r}")

    resolved_root = _normalize(root)
    resolved_control = _normalize(control_db or resolved_root / "events.db")
    resolved_cas = _normalize(cas_root or resolved_root / "cas")
    resolved_receipt = _normalize(
        receipt_log or resolved_root / RECEIPT_LOG_SUBDIR / RECEIPT_LOG_NAME
    )
    resolved_worker = _normalize(worker_root) if worker_root is not None else None
    resolved_supplemental = tuple(_normalize(p) for p in supplemental_roots)

    layout = WorkspaceLayout(
        project_id=project_id,
        root=resolved_root,
        control_db=resolved_control,
        cas_root=resolved_cas,
        receipt_log=resolved_receipt,
        config_path=resolved_root / WORKSPACE_CONFIG_NAME,
        worker_root=resolved_worker,
        supplemental_roots=resolved_supplemental,
    )
    _check_overlaps(layout)
    _check_within_control(layout)

    resolved_root.mkdir(parents=True, exist_ok=True)
    resolved_cas.mkdir(parents=True, exist_ok=True)
    resolved_receipt.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(resolved_root, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    _write_workspace_config(layout)
    return Workspace(layout=layout, receipt_log=ReceiptLog(resolved_receipt))


def load_workspace(root: Path) -> Workspace:
    """Load an existing workspace from its config file."""

    resolved_root = _normalize(root)
    config_path = resolved_root / WORKSPACE_CONFIG_NAME
    if not config_path.exists():
        raise WorkspaceStateError(f"workspace config not found at {config_path}; did you run init?")
    document = json.loads(config_path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != WORKSPACE_CONFIG_VERSION:
        raise WorkspaceStateError(
            f"workspace config {config_path} reports schema "
            f"{document.get('schemaVersion')!r}; expected {WORKSPACE_CONFIG_VERSION!r}"
        )
    expected_project = str(document.get("projectId") or "")
    if not expected_project:
        raise WorkspaceStateError(f"workspace config {config_path} missing projectId")
    resolved_control = _normalize(Path(str(document["controlDb"])))
    resolved_cas = _normalize(Path(str(document["casRoot"])))
    resolved_receipt = _normalize(Path(str(document["receiptLog"])))
    resolved_worker = (
        _normalize(Path(str(document["workerRoot"]))) if document.get("workerRoot") else None
    )
    resolved_supplemental = tuple(
        _normalize(Path(str(p))) for p in (document.get("supplementalRoots") or ())
    )
    layout = WorkspaceLayout(
        project_id=expected_project,
        root=resolved_root,
        control_db=resolved_control,
        cas_root=resolved_cas,
        receipt_log=resolved_receipt,
        config_path=config_path,
        worker_root=resolved_worker,
        supplemental_roots=resolved_supplemental,
    )
    _check_overlaps(layout)
    _check_within_control(layout)
    if not resolved_receipt.exists():
        resolved_receipt.parent.mkdir(parents=True, exist_ok=True)
        resolved_receipt.write_text("", encoding="utf-8")
        os.chmod(resolved_receipt, stat.S_IRUSR | stat.S_IWUSR)
    receipt_log = ReceiptLog(resolved_receipt)
    workspace = Workspace(layout=layout, receipt_log=receipt_log)
    _verify_project_id_matches(workspace, expected_project)
    return workspace


def describe_workspace(workspace: Workspace) -> Mapping[str, object]:
    return MappingProxyType(workspace.layout.as_document())


def _write_workspace_config(layout: WorkspaceLayout) -> None:
    payload = json.dumps(layout.as_document(), ensure_ascii=False, sort_keys=True)
    layout.config_path.write_text(payload, encoding="utf-8")
    os.chmod(layout.config_path, stat.S_IRUSR | stat.S_IWUSR)


def _verify_project_id_matches(workspace: Workspace, expected: str) -> None:
    if workspace.project_id != expected:
        raise WorkspaceStateError(
            f"workspace project_id {workspace.project_id!r} does not match config "
            f"projectId {expected!r}"
        )


__all__ = [
    "WORKSPACE_CONFIG_NAME",
    "WORKSPACE_CONFIG_VERSION",
    "Workspace",
    "WorkspaceLayout",
    "describe_workspace",
    "init_workspace",
    "load_workspace",
]
