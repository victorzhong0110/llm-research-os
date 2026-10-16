"""Read and compose a workspace map through the same contracts as the browser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import load_workspace
from llm_research_os.dashboard.agents import AgentInbox, AgentInboxDocument, AgentReply, AgentTask
from llm_research_os.dashboard.models import DashboardDocument
from llm_research_os.dashboard.observations import Observation, ObservationStore
from llm_research_os.dashboard.store import DashboardStore, read_json_input, read_write_request


def add_dashboard_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("dashboard", help="inspect and compose the workspace map")
    commands = parser.add_subparsers(dest="dashboard_command", required=True)
    show = commands.add_parser("show")
    show.add_argument("--root", type=Path, required=True)
    show.add_argument("--revision", type=int)
    apply = commands.add_parser("apply")
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("document", type=Path)
    inbox = commands.add_parser("inbox")
    inbox.add_argument("--root", type=Path, required=True)
    reply = commands.add_parser("reply")
    reply.add_argument("--root", type=Path, required=True)
    reply.add_argument("document", type=Path)
    observe = commands.add_parser("observe")
    observe.add_argument("--root", type=Path, required=True)
    observe.add_argument("document", type=Path)


def run_dashboard(args: argparse.Namespace) -> int:
    try:
        result: DashboardDocument | AgentInboxDocument | AgentTask | Observation
        store = DashboardStore(load_workspace(args.root))
        if args.dashboard_command == "show":
            result = store.read(args.revision)
        elif args.dashboard_command == "inbox":
            result = AgentInbox(load_workspace(args.root)).list_tasks()
        elif args.dashboard_command == "observe":
            raw = read_json_input(args.document, max_bytes=32768)
            result = ObservationStore(load_workspace(args.root)).observe(
                Observation.model_validate_json(raw)
            )
        elif args.dashboard_command == "reply":
            raw = read_json_input(args.document)
            result = AgentInbox(load_workspace(args.root)).reply(
                AgentReply.model_validate_json(raw)
            )
        else:
            result = store.write(read_write_request(args.document))
        print(result.model_dump_json(by_alias=True, indent=2))
        return 0
    except (ApplicationError, OSError, ValueError) as exc:
        print(json.dumps({"error": "dashboard-refused", "reason": type(exc).__name__}))
        return 1
