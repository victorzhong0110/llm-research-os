"""Read and compose a workspace map through the same contracts as the browser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import load_workspace
from llm_research_os.dashboard.store import DashboardStore, read_write_request


def add_dashboard_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("dashboard", help="inspect and compose the workspace map")
    commands = parser.add_subparsers(dest="dashboard_command", required=True)
    show = commands.add_parser("show")
    show.add_argument("--root", type=Path, required=True)
    show.add_argument("--revision", type=int)
    apply = commands.add_parser("apply")
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("document", type=Path)


def run_dashboard(args: argparse.Namespace) -> int:
    try:
        store = DashboardStore(load_workspace(args.root))
        if args.dashboard_command == "show":
            result = store.read(args.revision)
        else:
            result = store.write(read_write_request(args.document))
        print(result.model_dump_json(by_alias=True, indent=2))
        return 0
    except (ApplicationError, OSError, ValueError) as exc:
        print(json.dumps({"error": "dashboard-refused", "reason": type(exc).__name__}))
        return 1
