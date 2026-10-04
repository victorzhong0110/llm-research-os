"""R15 recovery contracts and the clean-install packaging boundary.

The published JSON Schemas are the external contract, so these tests validate
real CLI output against the committed files and guard the build configuration
that keeps the workbench bundle inside the wheel.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.cli.contracts import SCHEMA_CONTRACTS
from llm_research_os.recovery import create_backup, diagnose, restore_backup, verify_backup
from llm_research_os.recovery.demo import DEMO_CORPUS, DEMO_PROJECT, run_demo
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.recovery.models import (
    BackupManifest,
    BackupReport,
    DiagnosticReport,
    RestoreReport,
)
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
PROJECT = "example-minimal"
NOW = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)

RECOVERY_CONTRACTS = (
    "backup-manifest",
    "backup-report",
    "restore-report",
    "workspace-diagnostic",
)


def _validator(name: str) -> Draft202012Validator:
    committed = SCHEMA_CONTRACTS[name].committed_path
    return Draft202012Validator(json.loads((ROOT / committed).read_text(encoding="utf-8")))


def _workspace(tmp_path: Path) -> Any:
    return init_workspace(
        tmp_path / "workspace",
        project_id=PROJECT,
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )


def _seed(workspace: Any) -> None:
    with EventStore(workspace.control_db):
        pass
    for arguments in (
        [
            "m1",
            "prove",
            str(EXAMPLES / "m1-checkpoint"),
            str(workspace.control_db),
            "--decision",
            "accept",
            "--format",
            "json",
        ],
        [
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
    ):
        result = subprocess.run(
            [sys.executable, "-m", "llm_research_os", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", RECOVERY_CONTRACTS)
def test_recovery_contract_is_registered_and_current(name: str) -> None:
    contract = SCHEMA_CONTRACTS[name]
    assert contract.matches(ROOT / contract.committed_path), f"{name} schema is stale"


@pytest.mark.parametrize("name", RECOVERY_CONTRACTS)
def test_recovery_contract_declares_the_recovery_api_version(name: str) -> None:
    schema = _validator(name).schema
    rendered = json.dumps(schema)
    assert schema["$id"].startswith("https://researchos.dev/schemas/")
    assert "researchos.dev/recovery/v0alpha1" in rendered


@pytest.mark.parametrize("name", RECOVERY_CONTRACTS)
def test_recovery_contract_writes_a_file_that_matches(tmp_path: Path, name: str) -> None:
    """The committed file and the generator must agree through the write path."""

    contract = SCHEMA_CONTRACTS[name]
    written = tmp_path / name / "v0alpha1.schema.json"

    contract.write(written)

    assert written.is_file()
    assert contract.matches(written)
    assert written.read_text(encoding="utf-8") == contract.canonical()
    assert contract.matches(tmp_path / "absent.json") is False


def test_manifest_validates_against_the_published_schema(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    payload = json.loads((image / "backup-manifest.json").read_text(encoding="utf-8"))

    _validator("backup-manifest").validate(payload)
    manifest = BackupManifest.model_validate(payload)
    assert manifest.object_count() == len(manifest.objects)


def test_backup_report_validates_against_the_published_schema(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    report = create_backup(workspace, tmp_path / "image", now=NOW)

    _validator("backup-report").validate(report.model_dump(mode="json", by_alias=True))


def test_restore_report_validates_against_the_published_schema(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    report = restore_backup(image, tmp_path / "restored")

    _validator("restore-report").validate(report.model_dump(mode="json", by_alias=True))


def test_diagnostic_report_validates_against_the_published_schema(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    report = diagnose(workspace.root, now=NOW, deep=True)

    _validator("workspace-diagnostic").validate(report.describe())


def test_reports_reject_an_unknown_status(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="status"):
        DiagnosticReport(
            projectId=PROJECT,
            healthy=True,
            generatedAt="2026-10-05T04:00:00Z",
            pythonVersion="3.12.14",
            schemaVersion=2,
            checks=[{"id": "x", "status": "probably-fine"}],
        )


def test_manifest_rejects_a_malformed_snapshot_digest() -> None:
    with pytest.raises(ValueError, match="snapshotDigest"):
        BackupManifest(
            projectId=PROJECT,
            createdAt="2026-10-05T04:00:00Z",
            highWater=0,
            eventCount=0,
            schemaVersion=2,
            schemaDigest="sha256:" + "0" * 64,
            snapshotDigest="not-a-digest",
            snapshotBytes=1,
            objects=[],
            totalObjectBytes=0,
        )


def test_restore_report_rejects_a_relaunchable_policy(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relaunchPolicy"):
        RestoreReport(
            projectId=PROJECT,
            restoredHighWater=0,
            restoredEventCount=0,
            restoredObjectCount=0,
            ledgerMatches=True,
            relaunchPolicy="resume",
            reconciledRuns=[],
        )


def test_backup_report_round_trips_through_its_own_json(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    original = create_backup(workspace, tmp_path / "image", now=NOW)

    restored = BackupReport.model_validate_json(
        original.model_dump_json(by_alias=True, exclude_none=True)
    )

    assert restored == original


def test_verify_report_matches_the_creating_report(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed(workspace)
    image = tmp_path / "image"
    created = create_backup(workspace, image, now=NOW)

    assert verify_backup(image) == created


def test_wheel_target_ships_the_package_tree_including_the_bundle() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/llm_research_os"]

    # The bundle is a build product inside that package tree. A build change
    # that stopped including non-Python files would silently drop it, so the
    # assets and the recovery module are asserted to exist under it.
    package_root = ROOT / packages[0]
    assert (package_root / "web" / "static" / "index.html").is_file()
    assert (package_root / "recovery" / "backup.py").is_file()
    assert (package_root / "py.typed").is_file()


def test_packaged_corpus_ships_inside_the_wheel() -> None:
    """The demonstration must not borrow a corpus from a source checkout."""

    package_root = ROOT / "src" / "llm_research_os"
    corpus = package_root / "examples" / "offline-demo"
    assert corpus.is_dir()
    assert (corpus / "spec.yaml").is_file()
    assert (corpus / "simulation.json").is_file()
    # The corpus the demo reads must live inside the installed package tree, not
    # in the checkout's examples/ directory. Asserting absolute path equality
    # would only hold for whichever tree the import happened to resolve to.
    assert DEMO_CORPUS.parent.name == "examples"
    assert DEMO_CORPUS.parent.parent.name == "llm_research_os"
    assert {path.name for path in DEMO_CORPUS.iterdir()} >= {
        "spec.yaml",
        "simulation.json",
        "fixture.json",
        "README.md",
    }


def test_offline_demo_builds_a_healthy_workspace_from_packaged_data(
    tmp_path: Path,
) -> None:
    result = run_demo(tmp_path / "demo", now=NOW)

    assert result.healthy is True
    assert result.project_id == DEMO_PROJECT
    assert result.project_id != "offline-demo"
    assert result.high_water == 14
    assert "run.completed" in result.event_types
    assert result.queued is True
    assert "backup create" in result.backup_command
    assert "web serve" in result.serve_command


def test_offline_demo_leaves_the_packaged_corpus_untouched(tmp_path: Path) -> None:
    before = sorted(path.name for path in DEMO_CORPUS.iterdir())
    run_demo(tmp_path / "demo", now=NOW)
    assert sorted(path.name for path in DEMO_CORPUS.iterdir()) == before


def test_offline_demo_journey_backs_up_and_restores(tmp_path: Path) -> None:
    """The demonstration output is a real workspace the recovery path accepts."""

    result = run_demo(tmp_path / "demo", now=NOW)
    image = tmp_path / "image"
    report = create_backup(load_workspace(result.root), image, now=NOW)

    assert report.high_water == result.high_water
    restored = restore_backup(image, tmp_path / "restored")
    assert restored.ledger_matches is True
    assert restored.appended_events == 0
    assert diagnose(load_workspace(tmp_path / "restored").root, now=NOW).healthy is True


def test_offline_demo_refuses_an_occupied_root(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "mine.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        run_demo(target, now=NOW)

    assert info.value.code == "demo-path-occupied"
    assert (target / "mine.txt").read_text(encoding="utf-8") == "keep"


def test_offline_demo_cli_prints_the_next_commands(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "workspace",
            "demo",
            "--root",
            str(tmp_path / "d"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["healthy"] is True
    assert any("backup create" in command for command in payload["next"])
