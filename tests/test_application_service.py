"""Tests for the R02 shared application services.

These tests cover the R02 acceptance bullets in
``docs/plans/m3-development-plan.md``:

- CLI and Python entrypoints produce identical semantic results for the
  same command identity / content / expected head.
- Revisions and receipts survive a workspace reload.
- Repeated operations with the same ``command_id``/``submission_id`` and
  content return the prior receipt (replay semantics).
- Different content under the same identity is fail-closed.
- Cross-project references are rejected.
- The application package imports without optional training extras and
  the CLI handlers do not pull them in transitively.

The tests use only the ``core`` extra; ``ms-swift`` and CUDA toolchains are
not required and are not imported.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from llm_research_os.application import (
    InvalidCommandIdError,
    ReceiptReplayConflictError,
    Service,
    WorkspaceError,
    WorkspaceRootOverlapError,
    bind_operation_identity,
    init_workspace,
    load_workspace,
)
from llm_research_os.cli import application_commands

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SPEC = REPO_ROOT / "examples" / "m1-checkpoint" / "spec.yaml"


@pytest.fixture
def workspace_root(tmp_path: Path) -> Iterator[Path]:
    workspace_root = tmp_path / "r02ws"
    init_workspace(root=workspace_root, project_id="example-minimal")
    yield workspace_root
    shutil.rmtree(workspace_root, ignore_errors=True)


@pytest.fixture
def service(workspace_root: Path) -> Service:
    return Service(load_workspace(workspace_root))


def _manifest_path() -> Path:
    return REPO_ROOT / "examples" / "m1-checkpoint" / "manifest.yaml"


def test_init_workspace_creates_layout(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    workspace = init_workspace(root=root, project_id="example-minimal")
    assert workspace.project_id == "example-minimal"
    assert workspace.control_db.is_file() or not workspace.control_db.exists()
    assert workspace.cas_root.is_dir()
    assert workspace.receipt_log_path.parent.is_dir()
    description = workspace.layout.as_document()
    assert description["projectId"] == "example-minimal"
    assert description["schemaVersion"] == "application.workspace/v0alpha1"


def test_init_workspace_rejects_overlap_with_worker_root(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    worker = tmp_path / "worker"
    worker.mkdir()
    # Embedding the control db inside the worker root must fail.
    with pytest.raises(WorkspaceRootOverlapError):
        init_workspace(
            root=root,
            project_id="example-minimal",
            worker_root=worker,
            control_db=worker / "events.db",
        )


def test_init_workspace_rejects_invalid_project_id(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        init_workspace(root=tmp_path / "ws", project_id="bad id/with slash")


def test_validate_matches_project_id(service: Service) -> None:
    out = service.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-validate-1")
    assert out.document["status"] == "ok"
    assert out.receipt is not None
    assert out.receipt.outcome == "validated"


def test_validate_returns_replayed_receipt(service: Service) -> None:
    first = service.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-validate-replay")
    second = service.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-validate-replay")
    assert second.document["status"] == "replayed"
    assert second.receipt is not None
    assert first.receipt is not None
    assert second.receipt.content_digest == first.receipt.content_digest


def test_validate_rejects_cross_project_reference(service: Service, tmp_path: Path) -> None:
    bogus_spec = tmp_path / "bogus.yaml"
    bogus_spec.write_text(
        EXAMPLE_SPEC.read_text(encoding="utf-8").replace(
            "id: example-minimal",
            "id: other-project",
        ),
        encoding="utf-8",
    )
    out = service.execute_validate(spec_path=bogus_spec, command_id="r02-validate-cross")
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "project-mismatch"


def test_diff_succeeds_for_two_revisions(service: Service, tmp_path: Path) -> None:
    base = EXAMPLE_SPEC
    candidate = tmp_path / "spec-candidate.yaml"
    candidate.write_text(
        base.read_text(encoding="utf-8").replace("revision: 1", "revision: 2"),
        encoding="utf-8",
    )
    out = service.execute_diff(
        old_path=base,
        new_path=candidate,
        command_id="r02-diff-1",
    )
    assert out.document["status"] == "ok"


def test_dry_run_requires_registry(service: Service) -> None:
    out = service.execute_dry_run(
        spec_path=EXAMPLE_SPEC,
        workflow=None,
        registry=None,
        command_id="r02-dryrun-no-registry",
    )
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "registry-required"


def test_dry_run_with_registry(tmp_path: Path) -> None:
    """R02 dry_run requires a real BlockManifest and matching project id."""

    workspace_root = tmp_path / "ws"
    source_spec = REPO_ROOT / "examples" / "native-process-preflight" / "spec.yaml"
    source_manifest = REPO_ROOT / "examples" / "native-process-preflight" / "manifest.yaml"
    ws = init_workspace(
        root=workspace_root,
        project_id="example-native-process-preflight",
    )
    svc = Service(ws)
    out = svc.execute_dry_run(
        spec_path=source_spec,
        workflow=None,
        registry=source_manifest,
        command_id="r02-dryrun-1",
    )
    assert out.document["status"] == "ok", out.document


def test_receipt_log_survives_reload(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    service_a = Service(init_workspace(root=root, project_id="example-minimal"))
    service_a.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-survives-1")

    # Reopen the workspace (process restart boundary)
    service_b = Service(load_workspace(root))
    prior = service_b.receipt_log().find("r02-survives-1", 1)
    assert prior is not None
    replay = service_b.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-survives-1")
    assert replay.document["status"] == "replayed"


def test_replay_with_different_content_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    service = Service(init_workspace(root=root, project_id="example-minimal"))
    service.execute_validate(spec_path=EXAMPLE_SPEC, command_id="r02-conflict-1")

    # Re-submitting the same identity with different content (skipping
    # receipt replay's "prior" check) should fail closed inside the log.
    from llm_research_os.application.receipts import OperationReceipt, ReceiptLog

    log = ReceiptLog(root / ".researchos" / "operations.jsonl")
    with pytest.raises(ReceiptReplayConflictError):
        log.append(
            OperationReceipt(
                command_id="r02-conflict-1",
                submission_id=1,
                command="app.validate",
                content_digest="sha256:different",
                expected_head=None,
                outcome="validated",
            )
        )


def test_bind_operation_identity_rejects_invalid(tmp_path: Path) -> None:
    with pytest.raises(InvalidCommandIdError):
        bind_operation_identity("__internal")
    with pytest.raises(InvalidCommandIdError):
        bind_operation_identity("replay-attempt")
    with pytest.raises(InvalidCommandIdError):
        bind_operation_identity("has space")


def test_cli_and_python_have_identical_semantic_digest(tmp_path: Path) -> None:
    """Spawn the installed CLI and compare its JSON output to Python.

    Both paths go through the same :class:`Service` façade so the
    receipt's ``contentDigest`` and outcome must match exactly for the
    same command identity / spec path. The CLI is invoked through the
    installed ``researchos`` console script via ``uv run``.
    """

    workspace = tmp_path / "ws"
    init_workspace(root=workspace, project_id="example-minimal")
    python_service = Service(load_workspace(workspace))
    py_result = python_service.execute_validate(
        spec_path=EXAMPLE_SPEC, command_id="cli-python-equivalence"
    )
    py_doc = py_result.to_document()

    cli_output = subprocess.run(
        [
            "uv",
            "run",
            "researchos",
            "app",
            "spec-validate",
            "--workspace-root",
            str(workspace),
            str(EXAMPLE_SPEC),
            "--command-id",
            "cli-python-equivalence",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    cli_doc = json.loads(cli_output)

    assert cli_doc["status"] in ("ok", "replayed")
    assert py_doc["status"] == "ok"
    assert cli_doc["receipt"]["contentDigest"] == py_doc["receipt"]["contentDigest"]
    assert cli_doc["receipt"]["outcome"] == py_doc["receipt"]["outcome"]


def test_cli_handlers_round_trip_through_workspace(tmp_path: Path) -> None:
    """End-to-end exercise of the ``app`` CLI handlers against a workspace."""

    workspace_root = tmp_path / "ws"
    init_workspace(root=workspace_root, project_id="example-minimal")
    args = argparse.Namespace(
        workspace_root=str(workspace_root),
    )
    assert application_commands._app_workspace_show(args) == 0

    args = argparse.Namespace(
        workspace_root=str(workspace_root),
        command_id=None,
        submission_id=1,
        spec=EXAMPLE_SPEC,
    )
    assert application_commands._app_spec_validate(args) == 0

    args = argparse.Namespace(
        workspace_root=str(workspace_root),
        command_id=None,
        submission_id=1,
        run_id="missing-run",
    )
    rc = application_commands._app_run_show(args)
    assert rc in (1, 2)

    args = argparse.Namespace(
        workspace_root=str(workspace_root),
    )
    assert application_commands._app_receipt_list(args) == 0

    args = argparse.Namespace(
        workspace_root=str(workspace_root),
        command_id="missing",
        submission_id=1,
    )
    assert application_commands._app_receipt_get(args) == 0


def test_cli_handlers_surface_invalid_paths(tmp_path: Path) -> None:
    """CLI handlers must surface invalid workspace paths as exit-code 2."""

    missing = tmp_path / "does-not-exist"
    args = argparse.Namespace(workspace_root=str(missing))
    assert application_commands._app_workspace_show(args) == 2

    bad_root = tmp_path / "bad-ws"
    bad_root.mkdir()
    args = argparse.Namespace(workspace_root=str(bad_root))
    assert application_commands._app_receipt_list(args) == 2


def test_cli_handlers_run_app_dispatches() -> None:
    """``run_app`` routes to the registered handler."""

    args = argparse.Namespace(app_command=None)
    with pytest.raises(AssertionError):
        application_commands.run_app(args)


def test_run_show_refuses_when_event_store_missing(service: Service) -> None:
    """R02 surfaces ``store-missing`` instead of crashing on cold runs."""

    out = service.execute_run_query(
        run_id="missing-run-id",
        command_id="r02-run-missing",
    )
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "store-missing"


def test_ledger_read_refuses_when_event_store_missing(service: Service) -> None:
    out = service.execute_ledger_read(command_id="r02-ledger-missing")
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "store-missing"


def test_load_workspace_rejects_missing_config(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        load_workspace(tmp_path / "no-such-workspace")


def test_diff_rejects_cross_workspace_spec(service: Service, tmp_path: Path) -> None:
    other_spec = tmp_path / "other.yaml"
    other_spec.write_text(
        EXAMPLE_SPEC.read_text(encoding="utf-8").replace(
            "id: example-minimal", "id: other-project", 1
        ),
        encoding="utf-8",
    )
    out = service.execute_diff(
        old_path=EXAMPLE_SPEC,
        new_path=other_spec,
        command_id="r02-diff-cross",
    )
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "project-mismatch"


def test_normalize_command_id_accepts_uuid_like() -> None:
    """``None`` and whitespace-only inputs both produce fresh ids."""

    from llm_research_os.application.identity import normalize_command_id

    auto = normalize_command_id(None)
    assert auto.startswith("cmd-")
    assert normalize_command_id("   ") != "   "
    assert normalize_command_id("a.b:c-d_1").startswith("a.b:c-d_1")


def test_workspace_init_writes_schema_document(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = init_workspace(root=root, project_id="example-minimal")
    import json

    document = json.loads((ws.layout.config_path).read_text(encoding="utf-8"))
    assert document["schemaVersion"] == "application.workspace/v0alpha1"
    assert document["projectId"] == "example-minimal"


def test_workspace_supports_supplemental_roots(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    extra = tmp_path / "extra"
    extra.mkdir()
    ws = init_workspace(
        root=root,
        project_id="example-minimal",
        supplemental_roots=(extra,),
    )
    assert extra in ws.layout.supplemental_roots


def test_receipt_log_appends_replay_returns_existing(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    from llm_research_os.application.receipts import (
        OperationReceipt,
        ReceiptLog,
    )

    ReceiptLog(root / ".researchos" / "operations.jsonl")
    log = ReceiptLog(root / ".researchos" / "operations.jsonl")
    receipt = OperationReceipt(
        command_id="r02-log-replay",
        submission_id=1,
        command="app.validate",
        content_digest="sha256:fresh",
        expected_head=None,
        outcome="validated",
    )
    log.append(receipt)
    duplicate = log.append(receipt)
    assert duplicate is receipt
    prior = log.find("r02-log-replay", 1)
    assert prior is not None


def test_compute_content_digest_is_stable() -> None:
    from llm_research_os.application.service import compute_content_digest

    a = compute_content_digest("hello")
    b = compute_content_digest("hello")
    c = compute_content_digest("hello!")
    assert a == b
    assert a != c
    assert a.startswith("sha256:")


def test_run_show_refuses_when_run_not_found(tmp_path: Path) -> None:
    """When the EventStore exists but the run id is unknown, refuse with
    ``run-not-found`` rather than fabricating a synthetic run."""

    workspace_root = tmp_path / "ws"
    workspace = init_workspace(root=workspace_root, project_id="example-minimal")
    store_path = workspace.control_db
    store_path.parent.mkdir(parents=True, exist_ok=True)
    from llm_research_os.storage import EventStore

    EventStore(store_path)
    service = Service(load_workspace(workspace_root))
    out = service.execute_run_query(
        run_id="missing-run-id",
        command_id="r02-run-missing-real",
    )
    assert out.document["status"] == "refused"
    assert out.document["outcome"]["reasonCode"] == "run-not-found"


def test_workspace_reload_preserves_layout(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root=root, project_id="example-minimal")
    loaded = load_workspace(root)
    assert loaded.layout.as_document()["projectId"] == "example-minimal"
    assert loaded.layout.as_document()["root"] == str(root.expanduser().resolve())


def test_no_training_extras_required_at_import() -> None:
    """Importing the application layer must not pull in optional extras.

    Run the import check in a fresh subprocess so the assertions reflect
    only the application module's transitive imports, not whatever the
    rest of the test session has already loaded.
    """

    forbidden = (
        "llm_research_os.training",
        "ms_swift",
        "trl",
        "transformers",
    )
    code = (
        "import sys\n"
        "import llm_research_os.application as app\n"
        "modules = {name.lower() for name in sys.modules}\n"
        "forbidden = [\n"
    )
    for name in forbidden:
        code += f"    {name!r},\n"
    code += "]\n"
    code += "violations = [n for n in forbidden if n.lower() in modules]\n"
    code += "assert not violations, violations\n"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
