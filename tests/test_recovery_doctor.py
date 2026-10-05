"""R15 diagnostics, migration planning, and startup preflight.

The acceptance bar for a diagnostic is that an operator can share it. That
means the tests assert the absence of host paths and secrets, not only the
presence of the counts an operator needs.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import init_workspace
from llm_research_os.recovery import RecoveryError, diagnose, plan_migration, preflight_port
from llm_research_os.recovery import doctor as doctor_module
from llm_research_os.secrets.redaction import REDACTED
from llm_research_os.storage import EventStore
from llm_research_os.storage.schema import SCHEMA_VERSION
from llm_research_os.storage.store import (
    CONTROL_STORE_MARKER_VERSION,
    control_store_marker_path,
)
from llm_research_os.web import serve as serve_module

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
PROJECT = "example-minimal"
NOW = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
SUPER_SECRET = "sk-live-do-not-share-this-value"


def _workspace(tmp_path: Path, **overrides: Any) -> Any:
    return init_workspace(
        tmp_path / "workspace",
        project_id=overrides.pop("project_id", PROJECT),
        control_db=overrides.pop("control_db", Path("control/events.sqlite")),
        cas_root=overrides.pop("cas_root", Path("cas")),
        worker_root=overrides.pop("worker_root", Path("worker")),
    )


def _materialize(workspace: Any) -> None:
    """Create the versioned control store the R02 contract leaves absent."""

    with EventStore(workspace.control_db):
        pass


def _seed(workspace: Any) -> None:
    _materialize(workspace)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "evidence",
            "import",
            str(EXAMPLES / "evidence" / "valid" / "import-markdown.json"),
            str(workspace.control_db),
            "--source",
            str(EXAMPLES / "evidence" / "sources" / "eval-split.md"),
            "--artifacts",
            str(workspace.cas_root),
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def _cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "llm_research_os", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _control_status(workspace: Any) -> str:
    """The reason the control.store check reports, or '' if it is present."""

    check = _by_id(diagnose(workspace.root, now=NOW))["control.store"]
    return str(check.detail.get("reason", ""))


def _by_id(report: Any) -> dict[str, Any]:
    return {check.id: check for check in report.checks}


def test_healthy_workspace_reports_every_check_as_ok(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)

    report = diagnose(workspace.root, now=NOW, deep=True)

    assert report.healthy is True
    assert report.project_id == PROJECT
    assert report.worst_status() == "ok"
    checks = _by_id(report)
    assert checks["control.store"].detail["highWater"] == 1
    assert checks["control.migration"].detail["currentVersion"] == SCHEMA_VERSION
    assert checks["objects.referenced"].detail == {
        "referenced": 1,
        "missing": 0,
        "corrupt": 0,
        # `bytesVerified` rather than `verified`: the old key read as "these
        # objects are fine" even on a shallow run that re-hashed nothing.
        "bytesVerified": True,
        "presenceChecked": True,
    }
    assert checks["web.assets"].detail["bundlePresent"] is True
    assert checks["workspace.roots"].detail["workerRootIsolated"] is True


def test_unreadable_root_is_a_check_not_an_exception(tmp_path: Path) -> None:
    report = diagnose(tmp_path / "absent", now=NOW)

    assert report.healthy is False
    assert report.project_id is None
    assert [check.id for check in report.checks] == ["workspace.manifest"]
    assert report.checks[0].detail == {"reason": "unreadable"}


def test_damaged_control_store_is_reported_not_raised(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.control_db.write_bytes(b"this is not a sqlite database" * 64)

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    checks = _by_id(report)
    assert checks["control.store"].status == "failed"
    assert checks["control.migration"].status == "failed"


def test_missing_asset_bundle_is_a_startup_failure(tmp_path: Path, monkeypatch: Any) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(doctor_module, "STATIC_ROOT", tmp_path / "no-bundle")

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    assert _by_id(report)["web.assets"].detail["bundlePresent"] is False


def test_doctor_reports_root_isolation_for_a_sound_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    report = diagnose(workspace.root, now=NOW)

    detail = _by_id(report)["workspace.roots"].detail
    assert detail == {
        "workerRootIsolated": True,
        "casRootIsolated": True,
        "workerRootExists": True,
    }


def test_missing_referenced_object_is_reported_with_counts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    store = workspace.cas_root / "objects" / "sha256"
    shard = next(store.iterdir())
    (shard / next(shard.iterdir()).name).unlink()

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    detail = _by_id(report)["objects.referenced"].detail
    assert detail["missing"] == 1
    # Shallow run: presence was checked, bytes were not.
    assert detail["bytesVerified"] is False
    assert detail["presenceChecked"] is True


def test_overlapping_worker_root_is_refused_at_init(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError):
        _workspace(tmp_path, worker_root=Path("control/worker"))


def test_doctor_refuses_a_hand_edited_overlapping_manifest(tmp_path: Path) -> None:
    """load_workspace refuses overlap, so a tampered manifest is a failed check."""

    workspace = _workspace(tmp_path)
    manifest = workspace.root / "workspace.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["workerRoot"] = "control/worker"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    assert [check.id for check in report.checks] == ["workspace.manifest"]
    assert report.checks[0].status == "failed"


def test_diagnostics_never_leak_a_host_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    report = diagnose(workspace.root, now=NOW, deep=True)

    rendered = report.describe()
    text = repr(rendered)
    assert str(tmp_path) not in text
    assert str(workspace.root) not in text
    assert "control/events.sqlite" not in text


def test_every_check_detail_passes_through_the_redactor(tmp_path: Path, monkeypatch: Any) -> None:
    """The redaction is applied at the construction site, not by luck of the inputs.

    The previous version of this test injected a secret into an already-built
    detail, so it proved `redact_object` works and said nothing about whether
    `doctor` calls it.
    """

    workspace = _workspace(tmp_path)
    seen: list[dict[str, object]] = []
    original = doctor_module.redact_object

    def _spy(value: object, **kwargs: Any) -> Any:
        seen.append(dict(value)) if isinstance(value, dict) else None
        return original(value, **kwargs)

    monkeypatch.setattr(doctor_module, "redact_object", _spy)
    diagnose(workspace.root, now=NOW, deep=True)

    assert seen, "no check detail reached the redactor"
    assert all(set(detail) != {"apiKey"} for detail in seen), (
        "a check detail looks like a raw secret mapping"
    )


def test_a_secret_shaped_detail_is_redacted(tmp_path: Path, monkeypatch: Any) -> None:
    workspace = _workspace(tmp_path)
    original = doctor_module._check

    def _leaky(identifier: str, status: str, detail: dict[str, object]) -> Any:
        if identifier == "control.store":
            detail = {**detail, "apiKey": SUPER_SECRET, "nested": {"token": SUPER_SECRET}}
        return original(identifier, status, detail)

    monkeypatch.setattr(doctor_module, "_check", _leaky)
    rendered = repr(diagnose(workspace.root, now=NOW).describe())

    assert SUPER_SECRET not in rendered
    assert REDACTED in rendered


@pytest.mark.skipif(os.geteuid() == 0, reason="a privileged reader ignores mode bits")
@pytest.mark.parametrize(
    "damage",
    (
        pytest.param(lambda db: db.write_bytes(b"not sqlite" * 128), id="control-store"),
        pytest.param(lambda db: db.chmod(0o000), id="control-store-mode"),
    ),
)
def test_diagnose_reports_instead_of_raising_on_a_damaged_workspace(
    tmp_path: Path, damage: Any
) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    damage(workspace.control_db)
    try:
        report = diagnose(workspace.root, now=NOW, deep=True)
    finally:
        workspace.control_db.chmod(0o600)

    assert report.healthy is False
    assert _by_id(report)["control.store"].status == "failed"


def test_unsupported_python_version_is_reported_as_failed(tmp_path: Path, monkeypatch: Any) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(doctor_module, "MINIMUM_PYTHON", (99, 0))

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    detail = _by_id(report)["platform.runtime"].detail
    assert detail["pythonSupported"] is False


def test_preflight_reports_a_taken_port(tmp_path: Path) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]

        check = preflight_port("127.0.0.1", port)

    assert check.status == "failed"
    assert check.detail == {"port": port, "bindable": False}


def test_preflight_reports_a_free_port() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    check = preflight_port("127.0.0.1", port)

    assert check.status == "ok"
    assert check.detail == {"port": port, "bindable": True}


def test_serve_refuses_a_taken_port_with_a_closed_code(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]

        result = _cli("web", "serve", "--root", str(workspace.root), "--port", str(port))

    # The closed code and the no-traceback guarantee come from merged R14, which
    # already guards make_server. This test pins that contract as consumed here;
    # R15 deliberately does not change the code, and the port is not named.
    assert result.returncode == 2
    assert json.loads(result.stderr.strip()) == {
        "code": "listener-unavailable",
        "message": "the local listener could not start",
    }
    assert "Traceback" not in result.stderr


def test_migration_plan_reports_the_supported_range_and_refuses_downgrade(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    plan = plan_migration(workspace.root)

    assert plan["currentVersion"] == SCHEMA_VERSION
    assert plan["targetVersion"] == SCHEMA_VERSION
    assert plan["upgradeAvailable"] is False
    assert plan["downgradeSupported"] is False
    assert plan["supportedVersions"] == sorted(plan["supportedVersions"])


def test_migration_plan_rejects_an_unreadable_workspace(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError):
        plan_migration(tmp_path / "absent")


def test_cli_doctor_exits_zero_when_healthy(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)

    result = _cli("workspace", "doctor", "--root", str(workspace.root), "--deep")

    assert result.returncode == 0, result.stderr
    assert '"healthy": true' in result.stdout


def test_cli_doctor_exits_nonzero_when_unhealthy(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.control_db.write_bytes(b"not sqlite" * 128)

    result = _cli("workspace", "doctor", "--root", str(workspace.root))

    assert result.returncode == 1
    assert '"healthy": false' in result.stdout


def test_cli_doctor_reports_a_missing_workspace_instead_of_crashing(tmp_path: Path) -> None:
    result = _cli("workspace", "doctor", "--root", str(tmp_path / "absent"))
    assert result.returncode == 1
    assert '"healthy": false' in result.stdout
    assert '"workspace.manifest"' in result.stdout


def test_cli_migrate_uses_a_closed_code_for_a_missing_workspace(tmp_path: Path) -> None:
    result = _cli("workspace", "migrate", "--root", str(tmp_path / "absent"))
    assert result.returncode == 2
    assert "workspace-invalid" in result.stderr


def test_absent_control_store_is_reported_by_the_doctor(tmp_path: Path) -> None:
    """The R02 contract leaves the store absent until the first append.

    Covered together with the removed-store case in
    `test_the_skipped_state_still_names_the_lost_store_case`; both are the same
    observation as far as the workspace is concerned.
    """

    workspace = _workspace(tmp_path)

    report = diagnose(workspace.root, now=NOW)

    assert _by_id(report)["control.store"].status == "skipped"


def test_fresh_workspace_reports_its_absent_control_store_as_skipped(
    tmp_path: Path,
) -> None:
    """A workspace that never appended a fact is not unhealthy.

    `init` deliberately does not create the control store, so the checks that
    need it cannot run. Reporting that as `failed` made a correctly-initialized
    workspace read as broken, which is the first thing the T2 task asks an
    independent user to look at.
    """
    workspace = _workspace(tmp_path)

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is True
    for check_id in ("control.store", "control.migration", "objects.referenced"):
        check = _by_id(report)[check_id]
        assert check.status == "skipped"
        assert check.detail["reason"] == "not-yet-populated"
        assert check.detail["expected"] is True


def test_a_removed_control_store_is_reported_as_a_failure(tmp_path: Path) -> None:
    """Deleting a control store is data loss, and the report now says so.

    The lifecycle marker survives when the database does not, so this is
    distinguishable from a fresh workspace rather than reported as merely
    unpopulated. The earlier version had to guess, and guessed 'fine'.
    """
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    workspace.control_db.unlink()

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    for check_id in ("control.store", "control.migration", "objects.referenced"):
        check = _by_id(report)[check_id]
        assert check.status == "failed"
        assert check.detail["reason"] == "removed"
        assert check.detail["expected"] is False
    assert "backup" in _by_id(report)["control.store"].detail["note"]


def test_removing_the_whole_control_directory_is_also_detected(tmp_path: Path) -> None:
    """The second signal: `init_workspace` always creates the control directory.

    A wholesale `rm -rf control` takes the marker with it, so the directory's
    absence is the only evidence left -- and it is reliable, because a workspace
    this tool created always has one.
    """
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    shutil.rmtree(workspace.control_db.parent)

    report = diagnose(workspace.root, now=NOW)

    assert report.healthy is False
    assert _by_id(report)["control.store"].detail["reason"] == "removed"


def test_the_marker_is_written_when_a_store_is_created(tmp_path: Path) -> None:
    """The signal only works if something writes it, and writes it once."""
    workspace = _workspace(tmp_path)
    marker = control_store_marker_path(workspace.control_db)
    assert not marker.exists()

    _materialize(workspace)
    assert marker.exists()

    payload = json.loads(marker.read_text())
    assert payload["kind"] == "ControlStoreLifecycle"
    assert payload["markerVersion"] == CONTROL_STORE_MARKER_VERSION

    # A second open must not rewrite it: the marker records first creation, and
    # a rewritten timestamp would misreport when the store first came about.
    before = marker.read_text()
    with EventStore(workspace.control_db, require_existing=True):
        pass
    assert marker.read_text() == before


def test_the_marker_carries_nothing_that_needs_redacting(tmp_path: Path) -> None:
    """It sits inside a shareable workspace, so it must hold nothing sensitive."""
    workspace = _workspace(tmp_path)
    _materialize(workspace)

    rendered = control_store_marker_path(workspace.control_db).read_text()

    assert str(workspace.root) not in rendered
    assert str(tmp_path) not in rendered
    assert workspace.project_id not in rendered


def test_the_doctor_distinguishes_the_three_states(tmp_path: Path) -> None:
    """The point of the marker, asserted as a single comparison.

    Written as three workspaces in one test because the interesting claim is the
    difference between them, not any one of them.
    """
    states: dict[str, tuple[bool, str]] = {}
    for name, damage in (
        ("fresh", None),
        ("db-removed", "db"),
        ("dir-removed", "dir"),
    ):
        ws = _workspace(tmp_path / name)
        if damage is not None:
            _materialize(ws)
            if damage == "db":
                ws.control_db.unlink()
            else:
                shutil.rmtree(ws.control_db.parent)
        states[name] = (diagnose(ws.root, now=NOW).healthy, _control_status(ws))

    assert states["fresh"] == (True, "not-yet-populated")
    assert states["db-removed"] == (False, "removed")
    assert states["dir-removed"] == (False, "removed")


def test_migrate_refuses_a_workspace_without_a_control_store(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(RecoveryError) as info:
        plan_migration(workspace.root)
    assert info.value.code == "control-store-missing"


def test_cli_migrate_prints_the_plan(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    result = _cli("workspace", "migrate", "--root", str(workspace.root))
    assert result.returncode == 0, result.stderr
    assert '"downgradeSupported": false' in result.stdout


def test_recovery_error_carries_a_stable_code() -> None:
    error = RecoveryError("workspace-invalid", "the workspace could not be read")
    assert error.code == "workspace-invalid"
    assert str(error) == "the workspace could not be read"


def test_serve_module_exposes_a_loopback_default() -> None:
    assert serve_module.LOOPBACK_HOST == "127.0.0.1"
    assert serve_module.DEFAULT_PORT == 8787


def _bump_header_version(database: Path, version: int) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    finally:
        connection.close()


def test_doctor_reports_a_store_from_a_newer_build_as_a_downgrade(
    tmp_path: Path,
) -> None:
    """A too-new header must be reported as too new, not as an unreadable store."""

    workspace = _workspace(tmp_path)
    _materialize(workspace)
    _bump_header_version(workspace.control_db, SCHEMA_VERSION + 5)

    report = diagnose(workspace.root, now=NOW)

    detail = _by_id(report)["control.migration"].detail
    assert report.healthy is False
    assert detail == {
        "currentVersion": SCHEMA_VERSION + 5,
        "downgradeSupported": False,
    }
    assert _by_id(report)["control.store"].status == "failed"


def test_doctor_reports_a_store_awaiting_an_upgrade(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    _bump_header_version(workspace.control_db, 1)

    report = diagnose(workspace.root, now=NOW)

    check = _by_id(report)["control.migration"]
    assert check.status == "warning"
    assert check.detail == {"currentVersion": 1, "upgradeAvailable": True}


def test_migration_plan_reports_downgrade_instead_of_raising(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    _bump_header_version(workspace.control_db, SCHEMA_VERSION + 5)

    plan = plan_migration(workspace.root)

    assert plan["currentVersion"] == SCHEMA_VERSION + 5
    assert plan["downgradeSupported"] is False
    assert plan["upgradeAvailable"] is False


def test_migration_plan_reports_an_unreadable_control_store(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _materialize(workspace)
    workspace.control_db.write_bytes(b"not a database" * 64)

    with pytest.raises(RecoveryError) as info:
        plan_migration(workspace.root)
    assert info.value.code == "control-store-unreadable"


def test_diagnostics_carry_no_absolute_path_for_any_check(tmp_path: Path) -> None:
    """The redaction claim is asserted over the real details, not an injected one."""

    workspace = _workspace(tmp_path)
    _seed(workspace)
    report = diagnose(workspace.root, now=NOW, deep=True)

    rendered = json.dumps(report.describe())
    assert str(tmp_path) not in rendered
    assert str(workspace.root) not in rendered
    assert str(workspace.control_db) not in rendered
    assert str(workspace.cas_root) not in rendered
    assert str(workspace.worker_root) not in rendered
    assert "events.sqlite" not in rendered
    assert "/tmp" not in rendered
    for check in report.checks:
        assert set(check.detail) <= {
            "projectId",
            "workerRootIsolated",
            "casRootIsolated",
            "workerRootExists",
            "highWater",
            "schemaVersion",
            "currentVersion",
            "upgradeAvailable",
            "downgradeSupported",
            "referenced",
            "missing",
            "corrupt",
            "bytesVerified",
            "presenceChecked",
            "bundlePresent",
            "pythonSupported",
            "freeSpaceSufficient",
            "reason",
        }, check.id


def test_deep_verification_reports_a_corrupt_object(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    shard = next((workspace.cas_root / "objects" / "sha256").iterdir())
    (shard / next(shard.iterdir()).name).write_bytes(b"corrupted bytes")

    report = diagnose(workspace.root, now=NOW, deep=True)

    detail = _by_id(report)["objects.referenced"].detail
    assert report.healthy is False
    assert detail["corrupt"] >= 1
    assert detail["missing"] == 0


def test_diagnostics_report_an_unreadable_cas_root(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    workspace.cas_root.chmod(0o000)
    try:
        report = diagnose(workspace.root, now=NOW)
    finally:
        workspace.cas_root.chmod(0o700)

    if os.geteuid() == 0:
        # A privileged reader is not refused, so this path is not exercised.
        return
    assert _by_id(report)["objects.referenced"].detail == {"reason": "cas-unreadable"}


def test_cli_restore_refuses_a_project_override_with_no_events(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    image = tmp_path / "image"
    assert (
        _cli("backup", "create", "--root", str(workspace.root), "--out", str(image)).returncode == 0
    )

    result = _cli(
        "backup",
        "restore",
        "--image",
        str(image),
        "--root",
        str(tmp_path / "restored"),
        "--project",
        "no-such-project",
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "restore-ledger-mismatch"
    assert not (tmp_path / "restored").exists()
