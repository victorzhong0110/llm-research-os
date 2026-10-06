"""Exercise the installed wheel outside the checkout, without training extras.

The R15 clean-install bar is that a new operator needs neither a source
checkout nor Node: the packaged workbench bundle, the packaged example corpus,
the CLI, and a full initialize -> work -> diagnose -> backup -> restore journey
must all work from the installed wheel with no model key and no GPU.

This takes no arguments on purpose. Every input it needs ships inside the
wheel, so a passing run cannot be borrowing fixtures from a source checkout.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import llm_research_os
from llm_research_os.recovery.demo import DEMO_CORPUS, DEMO_PROJECT

package = Path(llm_research_os.__file__).resolve()
if "site-packages" not in package.parts:
    raise SystemExit("smoke must import an installed wheel, not the source checkout")
if importlib.util.find_spec("torch") is not None or importlib.util.find_spec("swift") is not None:
    raise SystemExit("smoke environment must not contain training extras")
if not DEMO_CORPUS.is_dir():
    raise SystemExit("the installed wheel does not contain the offline demonstration corpus")


def cli(*arguments: object, cwd: Path) -> "subprocess.CompletedProcess[str]":
    """Run the installed CLI in an isolated interpreter with no shell."""

    return subprocess.run(  # noqa: S603 - fixed argv, isolated interpreter, no shell
        [sys.executable, "-I", "-m", "llm_research_os", *(str(item) for item in arguments)],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


receipts: dict[str, object] = {}
journey: dict[str, object] = {}
with tempfile.TemporaryDirectory(prefix="researchos-wheel-") as directory:
    root = Path(directory)
    shutil.copytree(DEMO_CORPUS, root / "corpus")
    for decision in ("accept", "reject"):
        result = cli(
            "m1",
            "prove",
            root / "corpus",
            root / f"{decision}.db",
            "--decision",
            decision,
            "--format",
            "json",
            cwd=root,
        )
        receipt = json.loads(result.stdout)
        accepted = decision == "accept"
        if receipt["queued"] is not accepted:
            raise SystemExit("checkpoint decision/queue mismatch")
        if accepted and (
            "run.completed" not in receipt["eventTypes"]
            or receipt["answeredQuestionCount"] != 1
            or receipt["overriddenDissentCount"] != 1
            or receipt["rationaleCharacters"] <= 0
        ):
            raise SystemExit("accepted checkpoint lacks research or execution evidence")
        if not accepted and (receipt["runId"] is not None or "run.queued" in receipt["eventTypes"]):
            raise SystemExit("rejected checkpoint unexpectedly queued execution")
        receipts[decision] = receipt

    # R15 offline journey from the installed wheel: no key, no GPU, no checkout.
    # The project id must be the one the packaged corpus already carries. A
    # workspace whose manifest names a different project than its events is
    # refused by the restore ledger comparison, which is that check working.
    workspace = root / "workspace"
    cli(
        "app",
        "init",
        "--root",
        workspace,
        "--project",
        DEMO_PROJECT,
        "--control-db",
        "control/events.sqlite",
        "--cas-root",
        "cas",
        "--worker-root",
        "worker",
        cwd=root,
    )
    shutil.copy(root / "accept.db", workspace / "control" / "events.sqlite")
    doctor = json.loads(cli("workspace", "doctor", "--root", workspace, "--deep", cwd=root).stdout)
    if not doctor["healthy"]:
        raise SystemExit(f"installed workspace is not healthy: {doctor}")
    journey["doctorHealthy"] = doctor["healthy"]

    bundle = package.parent / "web" / "static" / "index.html"
    if not bundle.is_file():
        raise SystemExit("the installed wheel does not contain the built workbench bundle")
    journey["packagedBundle"] = True

    backup = json.loads(
        cli("backup", "create", "--root", workspace, "--out", root / "image", cwd=root).stdout
    )
    verified = json.loads(cli("backup", "verify", "--image", root / "image", cwd=root).stdout)
    restored = json.loads(
        cli(
            "backup",
            "restore",
            "--image",
            root / "image",
            "--root",
            root / "restored",
            cwd=root,
        ).stdout
    )
    if backup["highWater"] != verified["highWater"]:
        raise SystemExit(
            "a verified image reports a different prefix than the backup that wrote it"
        )
    if restored["ledgerMatches"] is not True or restored["appendedEvents"] != 0:
        raise SystemExit("restore did not reproduce the ledger or appended events")
    if restored["relaunchPolicy"] != "not-relaunched":
        raise SystemExit("restore did not record the no-relaunch policy")
    journey["backup"] = backup
    journey["restored"] = restored

print(
    json.dumps(
        {"installedWheel": True, "trainingExtras": False, "receipts": receipts, "journey": journey},
        indent=2,
    )
)
