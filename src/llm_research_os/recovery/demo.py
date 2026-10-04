"""The offline demonstration: a usable workspace from an installed package.

R15's install bar is that a new operator needs neither a source checkout nor
Node, a model key, or a GPU. This command proves it in one step: it
materializes a workspace, records a complete offline research chain from the
corpus packaged inside the wheel, diagnoses the result, and prints the next
commands.

The demonstration is deliberately bounded. It creates one workspace in a
directory the caller names, touches no network, starts no Worker, and spends no
money. A simulated ``completed`` is a controlled lifecycle finish, not a
training result and not a scientific conclusion (ADR-0062, TM-023).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm_research_os.application.workspace import init_workspace
from llm_research_os.m1.prove import prove_checkpoint
from llm_research_os.recovery.doctor import diagnose
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.storage.store import EventStore

DEMO_CORPUS = Path(__file__).resolve().parents[1] / "examples" / "offline-demo"
DEMO_PROJECT = "example-minimal"


@dataclass(frozen=True, slots=True)
class DemoResult:
    """What the demonstration produced, in a shape the CLI can print."""

    project_id: str
    root: Path
    high_water: int
    event_types: tuple[str, ...]
    queued: bool
    run_id: str | None
    healthy: bool
    backup_command: str
    serve_command: str


def run_demo(root: Path, *, now: datetime) -> DemoResult:
    """Create and populate one offline workspace, then diagnose it.

    The project id is the one the packaged corpus already carries rather than a
    name chosen here. A workspace whose manifest named a different project than
    its events would restore and back up inconsistently, and the restore ledger
    check refuses exactly that.

    The corpus is copied to a temporary directory because the packaged files are
    a read-only installed artifact and a caller must not be able to mutate them
    by running the demonstration.
    """

    target = root.absolute()
    if target.exists():
        if not target.is_dir():
            raise RecoveryError("demo-path-invalid", "the demonstration root is not a directory")
        if any(target.iterdir()):
            raise RecoveryError("demo-path-occupied", "the demonstration root is not empty")
    workspace = init_workspace(
        target,
        project_id=DEMO_PROJECT,
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )
    with tempfile.TemporaryDirectory(prefix="researchos-demo-") as staging:
        corpus = Path(staging) / "corpus"
        shutil.copytree(DEMO_CORPUS, corpus)
        result = prove_checkpoint(corpus, workspace.control_db, decision="accept")
    with EventStore(workspace.control_db, require_existing=True) as store:
        high_water = store.last_sequence()
    report = diagnose(workspace.root, now=now)
    return DemoResult(
        project_id=workspace.project_id,
        root=workspace.root,
        high_water=high_water,
        event_types=tuple(result.event_types),
        queued=result.queued,
        run_id=result.run_id,
        healthy=report.healthy,
        backup_command=(
            f"researchos backup create --root {workspace.root} --out {workspace.root}-backup"
        ),
        serve_command=f"researchos web serve --root {workspace.root} --port 8787",
    )


__all__ = ["DEMO_CORPUS", "DEMO_PROJECT", "DemoResult", "run_demo"]
