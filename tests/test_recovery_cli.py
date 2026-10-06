"""The R15 and R16 CLI surfaces, driven as a user drives them.

The library functions behind these commands are covered by the other recovery
suites. What those cannot catch is the layer in between: the argument names, the
exit codes, the stderr shape, and the branches that only a bad invocation
reaches. Three of the weakest-covered modules in the project were exactly this
layer, so the tests below go through the real command line rather than calling
the handlers, because the handler is not what a participant types.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from llm_research_os.cli import main
from llm_research_os.storage.store import EventStore

NOW_SUFFIX = "-now"


@dataclass
class _Run:
    """The observable result of one CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> Callable[..., _Run]:
    """Invoke the real command line in-process and capture what a user sees.

    In-process rather than `subprocess` for one reason beyond convenience: a
    child process writes its coverage to a different file, so a suite that
    spawns the CLI cannot be measured. `main(argv)` runs the same
    `build_parser` and the same handlers and returns the same exit code, so
    what is under test is unchanged and the numbers mean something.

    The two things it cannot show are what happens before `main` is reached --
    a bad interpreter, a missing console script -- and an uncaught crash's exit
    status. Both are covered by the installed-wheel smoke, which does run the
    real entrypoint.
    """

    def _run(*arguments: str) -> _Run:
        try:
            code = main(list(arguments))
        except SystemExit as exit_request:
            # argparse exits the process directly for `--help`, a missing
            # required argument, or a bare subcommand group. A subprocess would
            # show that as an exit status, so the fixture records it as one
            # rather than letting the test runner treat it as a test failure.
            code = int(exit_request.code or 0)
        captured = capsys.readouterr()
        return _Run(returncode=code, stdout=captured.out, stderr=captured.err)

    return _run


def _workspace(run_cli: Callable[..., _Run], root: Path, project: str = "example") -> None:
    result = run_cli(
        "app",
        "init",
        "--root",
        str(root),
        "--project",
        project,
        "--control-db",
        "control/events.sqlite",
        "--cas-root",
        "cas",
        "--worker-root",
        "worker",
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# app init


def test_app_init_accepts_only_a_root_and_a_project(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """The common case is two flags, because the guide is not always at hand.

    The trial task forbids cloning the repository, so `--help` is the only
    documentation a participant has, and it used to require four arguments with
    no defaults.
    """
    root = tmp_path / "workspace"
    result = run_cli("app", "init", "--root", str(root), "--project", "my-project")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["projectId"] == "my-project"
    assert payload["controlDb"] == "control/events.sqlite"
    assert (root / "workspace.json").is_file()


def test_app_init_still_honours_explicit_layout(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """The defaults are a convenience, not a replacement."""

    root = tmp_path / "workspace"
    result = run_cli(
        "app",
        "init",
        "--root",
        str(root),
        "--project",
        "my-project",
        "--control-db",
        "db/store.sqlite",
        "--cas-root",
        "objects",
        "--worker-root",
        "agents",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["controlDb"] == "db/store.sqlite"
    assert payload["casRoot"] == "objects"
    assert payload["workerRoot"] == "agents"


def test_app_init_names_its_defaults_in_help(tmp_path: Path, run_cli: Callable[..., _Run]) -> None:
    """Someone reading only `--help` must be able to see the convention."""

    result = run_cli("app", "init", "--help")

    assert result.returncode == 0
    for flag in ("--control-db", "--cas-root", "--worker-root"):
        assert flag in result.stdout
    assert "default:" in result.stdout
    assert "control/events.sqlite" in result.stdout


def test_app_init_refuses_a_workspace_that_already_exists(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "workspace"
    _workspace(run_cli, root)

    result = run_cli("app", "init", "--root", str(root), "--project", "my-project")

    assert result.returncode == 2
    assert "workspace-exists" in result.stderr


def test_app_init_reports_an_overlapping_worker_root(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    result = run_cli(
        "app",
        "init",
        "--root",
        str(tmp_path / "workspace"),
        "--project",
        "my-project",
        "--worker-root",
        "control/worker",
    )

    assert result.returncode == 2
    assert "code" in result.stderr


def test_app_execute_reports_a_missing_workspace(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """The failure branch of `app execute` exists and must be reachable."""

    result = run_cli("app", "execute", "--root", str(tmp_path / "absent"), "command.json")

    assert result.returncode == 2
    assert result.stdout == ""
    # Application errors render as a closed code plus a message, not a traceback.
    problem = json.loads(result.stderr)
    assert problem["code"] == "command-invalid"
    assert "Traceback" not in result.stderr


def test_app_execute_reports_an_unreadable_command_root(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """The workspace failure branch, with a command that would otherwise load."""

    root = tmp_path / "workspace"
    _workspace(run_cli, root)
    command = tmp_path / "command.json"
    command.write_text(json.dumps({"apiVersion": "researchos.dev/v0alpha1"}), encoding="utf-8")

    result = run_cli("app", "execute", "--root", str(root), str(command))

    assert result.returncode == 2
    assert json.loads(result.stderr)["code"]


# --------------------------------------------------------------------------
# workspace doctor / migrate / demo


def test_workspace_doctor_reports_a_missing_root_as_a_report(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """A workspace that cannot be opened is a report, not a crash."""

    result = run_cli("workspace", "doctor", "--root", str(tmp_path / "absent"))

    # Exit 1, not 2: the diagnostic itself succeeded, the workspace did not open.
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["healthy"] is False
    assert payload["kind"] == "WorkspaceDiagnostic"
    assert result.stderr == ""


def test_workspace_doctor_json_output_carries_no_host_path(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "workspace"
    _workspace(run_cli, root)
    run_cli("workspace", "demo", "--root", str(tmp_path / "demo"))

    result = run_cli("workspace", "doctor", "--root", str(root), "--deep")

    assert result.returncode == 0
    assert str(tmp_path) not in result.stdout
    assert "/tmp" not in result.stdout


def test_workspace_migrate_reports_the_supported_range(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "workspace"
    _workspace(run_cli, root)
    with EventStore(root / "control" / "events.sqlite"):
        pass

    result = run_cli("workspace", "migrate", "--root", str(root))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["downgradeSupported"] is False


def test_workspace_demo_refuses_an_occupied_root(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    (root / "stray").write_text("x", encoding="utf-8")

    result = run_cli("workspace", "demo", "--root", str(root))

    assert result.returncode == 2
    assert "demo-path-occupied" in result.stderr


def test_workspace_demo_refuses_a_file_where_a_directory_belongs(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "demo"
    root.write_text("not a directory", encoding="utf-8")

    result = run_cli("workspace", "demo", "--root", str(root))

    assert result.returncode == 2
    assert "demo-path-invalid" in result.stderr


def test_workspace_demo_prints_a_runnable_evidence_import(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """The hint has to work when pasted, or it is decoration.

    T1 forbids cloning the repository, so anything the demonstration suggests
    has to be reachable from the installed package alone.
    """
    root = tmp_path / "demo"
    result = run_cli("workspace", "demo", "--root", str(root))
    assert result.returncode == 0
    next_commands = json.loads(result.stdout)["next"]

    import_command = next_commands[0]
    assert import_command.startswith("researchos evidence import ")

    pasted = import_command.replace("researchos ", f"{sys.executable} -m llm_research_os ", 1)
    imported = subprocess.run(
        pasted, shell=True, check=False, capture_output=True, text=True, timeout=300
    )
    assert imported.returncode == 0, imported.stderr
    assert "evidence: imported" in imported.stdout


# --------------------------------------------------------------------------
# backup create / verify / restore


def test_backup_create_verify_and_restore_through_therun_cli(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "demo"
    assert run_cli("workspace", "demo", "--root", str(root)).returncode == 0
    image = tmp_path / "image"

    created = run_cli("backup", "create", "--root", str(root), "--out", str(image))
    assert created.returncode == 0, created.stderr
    assert json.loads(created.stdout)["verified"] is True

    verified = run_cli("backup", "verify", "--image", str(image))
    assert verified.returncode == 0
    assert json.loads(verified.stdout)["verified"] is True

    restored = run_cli("backup", "restore", "--image", str(image), "--out", str(tmp_path / "back"))
    assert restored.returncode == 0, restored.stderr
    payload = json.loads(restored.stdout)
    assert payload["appendedEvents"] == 0
    assert payload["relaunchPolicy"] == "not-relaunched"
    assert payload["ledgerMatches"] is True


def test_backup_restore_accepts_out_and_root_alike(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """`--root` named the source on `create` and the destination on `restore`.

    A participant copying the flag vocabulary from one subcommand to the other
    got an error from the product rather than from their own mistake.
    """
    root = tmp_path / "demo"
    assert run_cli("workspace", "demo", "--root", str(root)).returncode == 0
    image = tmp_path / "image"
    assert run_cli("backup", "create", "--root", str(root), "--out", str(image)).returncode == 0

    via_out = run_cli("backup", "restore", "--image", str(image), "--out", str(tmp_path / "a"))
    via_root = run_cli("backup", "restore", "--image", str(image), "--root", str(tmp_path / "b"))

    assert via_out.returncode == 0, via_out.stderr
    assert via_root.returncode == 0, via_root.stderr
    assert (
        json.loads(via_out.stdout)["restoredHighWater"]
        == json.loads(via_root.stdout)["restoredHighWater"]
    )


def test_backup_restore_refuses_two_different_destinations(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "demo"
    assert run_cli("workspace", "demo", "--root", str(root)).returncode == 0
    image = tmp_path / "image"
    assert run_cli("backup", "create", "--root", str(root), "--out", str(image)).returncode == 0

    result = run_cli(
        "backup",
        "restore",
        "--image",
        str(image),
        "--root",
        str(tmp_path / "a"),
        "--out",
        str(tmp_path / "b"),
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "backup-restore-ambiguous"


def test_backup_restore_requires_a_destination(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    result = run_cli("backup", "restore", "--image", str(tmp_path / "absent"))

    assert result.returncode != 0


def test_backup_restore_reports_an_unreadable_image(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    result = run_cli(
        "backup", "restore", "--image", str(tmp_path / "absent"), "--out", str(tmp_path / "out")
    )

    assert result.returncode == 2
    assert "code" in result.stderr


def test_backup_verify_reports_a_tampered_image(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    root = tmp_path / "demo"
    assert run_cli("workspace", "demo", "--root", str(root)).returncode == 0
    image = tmp_path / "image"
    assert run_cli("backup", "create", "--root", str(root), "--out", str(image)).returncode == 0

    snapshot = image / "events.sqlite3"
    assert snapshot.is_file()
    snapshot.write_bytes(b"not a database at all")

    result = run_cli("backup", "verify", "--image", str(image))

    assert result.returncode == 2
    assert "code" in result.stderr


# --------------------------------------------------------------------------
# trial scaffold / validate / aggregate


def test_trial_scaffold_writes_invalid_slots_and_exits_nonzero(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """An unrun trial must read as unrun in a machine-readable way."""

    kit = tmp_path / "kit"
    result = run_cli("trial", "scaffold", "--root", str(kit), "--participant", "participant-a")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["scaffolded"]

    for name in payload["scaffolded"]:
        slot = json.loads((kit / name).read_text(encoding="utf-8"))
        assert slot["participantConfirmed"] is False
        # Deliberately incomplete: `validate` must still refuse it.
        assert run_cli("trial", "validate", str(kit / name)).returncode == 2


def test_trial_scaffold_refuses_an_occupied_directory(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "stray").write_text("x", encoding="utf-8")

    result = run_cli("trial", "scaffold", "--root", str(kit), "--participant", "participant-a")

    assert result.returncode == 2
    assert "trial-path-occupied" in result.stderr


def test_trial_validate_reports_a_complete_record(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    record = _confirmed_record(tmp_path)

    result = run_cli("trial", "validate", str(record))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["confirmed"] is True
    assert payload["pendingConfirmation"] is False


def test_trial_validate_reports_a_record_awaiting_the_participant(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    record = _confirmed_record(tmp_path, confirmed=False, confirmed_at=None)

    result = run_cli("trial", "validate", str(record))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["confirmed"] is False
    assert payload["pendingConfirmation"] is True


def test_trial_validate_reports_an_invalid_record(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    record = tmp_path / "record.json"
    record.write_text('{"apiVersion": "researchos.dev/trial/v0alpha1"}', encoding="utf-8")

    result = run_cli("trial", "validate", str(record))

    assert result.returncode == 2
    assert "trial-record-invalid" in result.stderr


def test_trial_validate_reports_an_unreadable_record(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    result = run_cli("trial", "validate", str(tmp_path / "absent.json"))

    assert result.returncode == 2
    assert "trial-record-unreadable" in result.stderr


def test_trial_aggregate_keeps_checkpoint_d_closed_on_unconfirmed_records(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    """Two observed records are not two people who took part."""

    kit = tmp_path / "kit"
    assert run_cli("trial", "scaffold", "--root", str(kit), "--participant", "a").returncode == 1

    records = [
        _confirmed_record(
            kit / "T1",
            trial_id="TRIAL-01/A/1",
            alias="a",
            confirmed=False,
            confirmed_at=None,
            task="T1",
        ),
        _confirmed_record(
            kit / "T1",
            trial_id="TRIAL-01/B/1",
            alias="b",
            confirmed=False,
            confirmed_at=None,
            task="T1",
        ),
    ]
    _write_kit(kit, records=records, blockers=[])

    result = run_cli("trial", "aggregate", "--root", str(kit))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["observedParticipants"] == ["a", "b"]
    assert payload["participants"] == []
    assert payload["pendingConfirmation"] == ["TRIAL-01/A/1", "TRIAL-01/B/1"]
    assert payload["completedTasks"] == 0
    assert payload["checkpointD"] is False


def test_trial_aggregate_counts_only_confirmed_records(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    kit = tmp_path / "kit"
    kit.mkdir()
    records = [
        _confirmed_record(kit, trial_id="TRIAL-01/A/1", alias="a", task="T1"),
        _confirmed_record(kit, trial_id="TRIAL-02/B/1", alias="b", task="REMOTE"),
    ]
    _write_kit(kit, records=records, blockers=[])

    result = run_cli("trial", "aggregate", "--root", str(kit))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["participants"] == ["a", "b"]
    assert payload["pendingConfirmation"] == []
    # Both records completed a core journey, one of which was the remote one.
    assert payload["completedTasks"] == 2
    assert payload["remoteJourneys"] == 1
    assert payload["checkpointD"] is False
    assert payload["trialTaskCoverageComplete"] is False


def test_trial_aggregate_reports_an_unreadable_kit(
    tmp_path: Path, run_cli: Callable[..., _Run]
) -> None:
    kit = tmp_path / "kit"
    kit.mkdir()

    result = run_cli("trial", "aggregate", "--root", str(kit))

    assert result.returncode == 2
    assert "trial-kit-unreadable" in result.stderr


def _confirmed_record(
    root: Path,
    *,
    trial_id: str = "TRIAL-01/A/2026-10-06",
    alias: str = "participant-a",
    task: str = "T1",
    confirmed: bool = True,
    confirmed_at: str | None = "2026-10-06T17:30:00Z",
) -> Path:
    """Write one complete record, optionally left unconfirmed."""

    root.mkdir(parents=True, exist_ok=True)
    record = {
        "apiVersion": "researchos.dev/trial/v0alpha1",
        "kind": "TrialRecord",
        "trialId": trial_id,
        "task": task,
        "participantAlias": alias,
        "recordedAt": "2026-10-06T09:00:00Z",
        "recordedBy": "observer",
        "participantConfirmed": confirmed,
        "confirmedAt": confirmed_at,
        "buildUnderTest": "llm_research_os-0.0.0-py3-none-any.whl",
        "platform": "Linux 6.8, x86_64",
        "pythonVersion": "3.12.14",
        "modelKey": "absent",
        "gpu": "absent",
        "node": "absent",
        "sourceCheckout": "absent",
        "taskTextGiven": "Install the wheel and run the demonstration.",
        "completed": True,
        "exitState": "workspace demo reported a healthy workspace",
        "elapsedSeconds": 240,
        "interventions": [],
        "confusionObserved": [],
        "recoveryObserved": [],
        "defectsFound": [],
        "evidenceAttached": ["doctor.json"],
        "verdict": "core-journey-completed",
    }
    path = root / f"{trial_id.replace('/', '_')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _write_kit(root: Path, *, records: list[Path], blockers: list[str]) -> None:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in records]
    (root / "trial-kit.json").write_text(
        json.dumps(
            {
                "apiVersion": "researchos.dev/trial/v0alpha1",
                "kind": "TrialKit",
                "records": payloads,
                "blockers": blockers,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "command",
    [
        ("trial",),
        ("backup",),
        ("workspace",),
    ],
)
def test_a_subcommand_group_without_an_action_is_refused(
    command: tuple[str, ...], run_cli: Callable[..., _Run]
) -> None:
    """A group name alone is not a command, and must not be treated as one."""

    result = run_cli(*command)

    assert result.returncode != 0
