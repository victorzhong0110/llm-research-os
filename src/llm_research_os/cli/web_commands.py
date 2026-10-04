"""CLI façade for the local workbench API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_research_os.web.serve import DEFAULT_PORT, LOOPBACK_HOST, serve


def add_web_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    web = subparsers.add_parser("web", help="local browser workbench API")
    commands = web.add_subparsers(dest="web_command", required=True)
    start = commands.add_parser("serve", help="serve the local API on loopback")
    start.add_argument("--root", type=Path, required=True, help="workspace root")
    start.add_argument("--host", default=LOOPBACK_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)


def run_web(args: argparse.Namespace) -> int:
    if args.web_command == "serve":
        return serve(args.root, host=args.host, port=args.port)
    print(
        '{"code":"command-invalid","message":"unhandled web command"}',
        file=sys.stderr,
    )
    return 2
