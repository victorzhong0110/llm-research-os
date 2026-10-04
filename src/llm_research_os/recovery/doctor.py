"""Redacted workspace diagnostics, migration planning, and startup preflight.

R15 makes the installed package operable without a source checkout, so an
operator needs one command that answers "can I use this workspace, and if not,
what is wrong" before a browser or a Worker is started. Every value in a
report is a count, an identifier the operator already supplied, or a boolean:
no host path, no document body, and no credential is ever rendered
(TM-007, TM-022), so a report can be pasted into an issue as-is.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import Workspace, load_workspace
from llm_research_os.artifacts.errors import ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.projections.replay import replay_events
from llm_research_os.projections.sqlite import referenced_digests
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.recovery.models import DiagnosticCheck, DiagnosticReport
from llm_research_os.secrets.redaction import redact_object
from llm_research_os.storage.errors import EventIntegrityError, EventStoreError
from llm_research_os.storage.schema import MIGRATIONS, SCHEMA_VERSION
from llm_research_os.storage.store import EventStore
from llm_research_os.web.assets import INDEX_NAME, STATIC_ROOT

MINIMUM_PYTHON = (3, 12)
MIN_FREE_BYTES = 64 << 20


def diagnose(root: Path, *, now: datetime, deep: bool = False) -> DiagnosticReport:
    """Return a redacted diagnostic report for one workspace root.

    A workspace that cannot be opened still produces a report; the failure is a
    check, not an exception, so an operator can read what is wrong.
    """

    checks: list[DiagnosticCheck] = []
    project_id: str | None = None
    try:
        workspace = load_workspace(root)
    except (ApplicationError, OSError, ValueError, ValidationError):
        checks.append(_check("workspace.manifest", "failed", {"reason": "unreadable"}))
        return _report(None, checks, now=now)
    project_id = workspace.project_id
    checks.append(_check("workspace.manifest", "ok", {"projectId": workspace.project_id}))
    checks.append(_check_roots(workspace))
    checks.append(_check_control_store(workspace))
    checks.append(_check_migration(workspace))
    objects = _check_objects(workspace, deep=deep)
    if objects is not None:
        checks.append(objects)
    checks.append(_check_assets())
    checks.append(_check_platform())
    return _report(project_id, checks, now=now)


def plan_migration(root: Path) -> dict[str, object]:
    """Report the schema versions a workspace can move between.

    Downgrade is refused rather than approximated: a store written by a newer
    build may contain facts this build cannot represent, and silently
    rewriting historical rows would break digest history.
    """

    workspace = load_workspace(root)
    if not workspace.control_db.exists():
        raise RecoveryError("control-store-missing", "the workspace control store is missing")
    current = read_header_version(workspace.control_db)
    if current is None:
        raise RecoveryError("control-store-unreadable", "the workspace control store is unreadable")
    supported = sorted({migration.version for migration in MIGRATIONS} | {SCHEMA_VERSION})
    return {
        "currentVersion": current,
        "supportedVersions": supported,
        "targetVersion": SCHEMA_VERSION,
        "upgradeAvailable": current < SCHEMA_VERSION,
        "downgradeSupported": False,
        "migrations": [
            {"version": migration.version, "name": migration.name} for migration in MIGRATIONS
        ],
    }


def preflight_port(host: str, port: int) -> DiagnosticCheck:
    """Report whether the local API port can be bound before starting a server."""

    from llm_research_os.web.serve import port_is_free

    free = port_is_free(host, port)
    return _check(
        "network.port",
        "ok" if free else "failed",
        {"port": port, "bindable": free},
    )


def _check_roots(workspace: Workspace) -> DiagnosticCheck:
    """Fail closed when control and Worker roots overlap.

    A Worker root inside the control root would put Worker material next to the
    control SQLite file, which the R07 boundary forbids.
    """

    control = workspace.control_db.parent.resolve()
    worker = workspace.worker_root.resolve()
    cas = workspace.cas_root.resolve()
    overlaps = _contains(control, worker) or _contains(control, cas)
    return _check(
        "workspace.roots",
        "failed" if overlaps else "ok",
        {
            "workerRootIsolated": not _contains(control, worker),
            "casRootIsolated": not _contains(control, cas),
            "workerRootExists": workspace.worker_root.is_dir(),
        },
    )


def _check_control_store(workspace: Workspace) -> DiagnosticCheck:
    if not workspace.control_db.exists():
        return _check("control.store", "failed", {"reason": "absent"})
    try:
        with EventStore(workspace.control_db, create=False) as store:
            high_water = store.freeze_high_water()
    except (EventStoreError, OSError):
        return _check("control.store", "failed", {"reason": "unreadable"})
    return _check(
        "control.store",
        "ok",
        {"highWater": high_water, "schemaVersion": SCHEMA_VERSION},
    )


def _check_migration(workspace: Workspace) -> DiagnosticCheck:
    if not workspace.control_db.exists():
        return _check("control.migration", "failed", {"reason": "absent"})
    current = read_header_version(workspace.control_db)
    if current is None:
        return _check("control.migration", "failed", {"reason": "unreadable"})
    if current == SCHEMA_VERSION:
        return _check("control.migration", "ok", {"currentVersion": current})
    if current < SCHEMA_VERSION:
        return _check(
            "control.migration",
            "warning",
            {"currentVersion": current, "upgradeAvailable": True},
        )
    return _check(
        "control.migration",
        "failed",
        {"currentVersion": current, "downgradeSupported": False},
    )


def _check_objects(workspace: Workspace, *, deep: bool) -> DiagnosticCheck | None:
    """Report referenced-object coverage. ``deep`` re-verifies bytes, not just presence."""

    if not workspace.control_db.exists():
        return _check("objects.referenced", "failed", {"reason": "absent"})
    try:
        with EventStore(workspace.control_db, create=False) as store:
            high_water = store.freeze_high_water()
            referenced: set[str] = set()
            for stored in replay_events(store, until_sequence=high_water, freeze_high_water=False):
                for digest, _role in referenced_digests(stored.event):
                    if digest.startswith("sha256:"):
                        referenced.add(digest)
    except (EventStoreError, EventIntegrityError, OSError):
        return _check("objects.referenced", "failed", {"reason": "unreadable"})
    try:
        store_objects = LocalArtifactStore(workspace.cas_root)
    except (ArtifactStoreError, OSError, ValueError):
        return _check("objects.referenced", "failed", {"reason": "cas-unreadable"})
    missing = 0
    corrupt = 0
    for digest in sorted(referenced):
        if not store_objects.exists(digest):
            missing += 1
        elif deep:
            try:
                store_objects.verify(digest)
            except (ArtifactStoreError, OSError, ValueError):
                corrupt += 1
    status = "ok" if missing == 0 and corrupt == 0 else "failed"
    return _check(
        "objects.referenced",
        status,
        {
            "referenced": len(referenced),
            "missing": missing,
            "corrupt": corrupt if deep else 0,
            "verified": deep,
        },
    )


def _check_assets() -> DiagnosticCheck:
    """Report the packaged workbench bundle.

    A missing bundle is a startup failure, not an empty project, so it is
    reported before an operator opens a browser.
    """

    present = (STATIC_ROOT / INDEX_NAME).is_file()
    return _check(
        "web.assets",
        "ok" if present else "failed",
        {"bundlePresent": present},
    )


def _check_platform() -> DiagnosticCheck:
    version = sys.version_info[:2]
    supported = version >= MINIMUM_PYTHON
    free = shutil.disk_usage(Path(os.getcwd())).free
    status = "ok" if supported and free >= MIN_FREE_BYTES else "warning"
    if not supported:
        status = "failed"
    return _check(
        "platform.runtime",
        status,
        {
            "pythonSupported": supported,
            "freeSpaceSufficient": free >= MIN_FREE_BYTES,
        },
    )


def read_header_version(database: Path) -> int | None:
    """Return ``PRAGMA user_version`` without opening an EventStore.

    ``EventStore.__init__`` refuses a header this build does not support, so a
    too-new store would surface as an opaque "unreadable" and a downgrade report
    could never be produced. A plain connection reads the header first so the
    operator is told which direction the version is wrong in.
    """

    try:
        encoded = quote(database.absolute().as_posix(), safe="/")
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=5.0)
    except (sqlite3.Error, ValueError):
        return None
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if row is None:  # pragma: no cover - PRAGMA user_version always returns a row
        return None
    value = row[0]
    return int(value) if isinstance(value, int) else None


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _check(identifier: str, status: str, detail: dict[str, object]) -> DiagnosticCheck:
    """Build one check with its detail passed through the shared redactor."""

    redacted = redact_object(detail)
    if not isinstance(redacted, dict):  # pragma: no cover - redact_object preserves dicts
        raise RecoveryError("diagnostic-invalid", "diagnostic detail could not be rendered")
    return DiagnosticCheck(id=identifier, status=status, detail=redacted)  # type: ignore[arg-type]


def _report(
    project_id: str | None,
    checks: list[DiagnosticCheck],
    *,
    now: datetime,
) -> DiagnosticReport:
    healthy = all(check.status != "failed" for check in checks)
    return DiagnosticReport(
        projectId=project_id,
        healthy=healthy,
        generatedAt=now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        pythonVersion=".".join(str(part) for part in sys.version_info[:3]),
        schemaVersion=SCHEMA_VERSION,
        checks=list(checks),
    )
