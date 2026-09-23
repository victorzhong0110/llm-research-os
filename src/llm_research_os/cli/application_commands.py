"""CLI façade for shared application commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import load_application_command
from llm_research_os.application.service import ApplicationService
from llm_research_os.application.workspace import init_workspace
from llm_research_os.cli.output import dumps_json


def add_app_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    app = subparsers.add_parser(
        "app",
        help="shared workspace commands for CLI and Python callers",
    )
    commands = app.add_subparsers(dest="app_command", required=True)
    init = commands.add_parser("init", help="bind a project workspace")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--project", required=True)
    init.add_argument("--control-db", type=Path, required=True)
    init.add_argument("--cas-root", type=Path, required=True)
    init.add_argument("--worker-root", type=Path, required=True)
    execute = commands.add_parser("execute", help="execute or replay one application command")
    execute.add_argument("--root", type=Path, required=True)
    execute.add_argument("command_path", type=Path)


def run_app(args: argparse.Namespace) -> int:
    try:
        if args.app_command == "init":
            workspace = init_workspace(
                args.root,
                project_id=args.project,
                control_db=args.control_db,
                cas_root=args.cas_root,
                worker_root=args.worker_root,
            )
            print(dumps_json(workspace.describe()))
            return 0
        if args.app_command == "execute":
            command = load_application_command(args.command_path)
            document = ApplicationService.open(args.root).execute(command)
            print(dumps_json(document))
            return 0
    except ApplicationError as exc:
        print(dumps_json({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValidationError, ValueError):
        print(
            dumps_json({"code": "command-invalid", "message": "application command failed"}),
            file=sys.stderr,
        )
        return 2
    raise AssertionError(f"unhandled app command: {args.app_command}")
