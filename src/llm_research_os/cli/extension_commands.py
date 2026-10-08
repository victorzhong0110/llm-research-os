"""Explicit installed extension lifecycle; no automatic fetch or execution."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Literal, cast

from llm_research_os.application.errors import ApplicationError
from llm_research_os.cli.output import dumps_json
from llm_research_os.extensions.manifest import MAX_MESSAGE_BYTES, ExtensionError
from llm_research_os.extensions.package import Role, existing_cpu_evaluator, parse_package
from llm_research_os.extensions.persistent import PersistentExtensions


def add_extension_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("extensions", help="explicit reviewed extension lifecycle")
    commands = parser.add_subparsers(dest="extension_command", required=True)
    for action in (
        "inspect",
        "install",
        "install-cpu-example",
        "enable",
        "disable",
        "uninstall",
        "run",
    ):
        command = commands.add_parser(action)
        command.add_argument("--root", type=Path, required=True)
        if action in {"install", "install-cpu-example"}:
            command.add_argument(
                "--trust", choices=["inert", "reviewed-same-user", "untrusted"], default="inert"
            )
        if action == "install":
            command.add_argument("--package", type=Path, required=True)
        if action in {"enable", "disable", "uninstall", "run"}:
            command.add_argument("--id", required=True)
            command.add_argument("--version", required=True)
        if action == "run":
            command.add_argument(
                "--role", choices=["brick", "evaluator", "provider"], required=True
            )
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--timeout", type=float, default=10)


def run_extensions(args: argparse.Namespace) -> int:
    try:
        registry = PersistentExtensions(args.root)
        action = args.extension_command
        if action == "inspect":
            result = registry.inspect()
        elif action == "install":
            result = registry.install(args.package, trust=args.trust)
        elif action == "install-cpu-example":
            result = registry.install_package(
                parse_package(existing_cpu_evaluator()), trust=args.trust
            )
        elif action in {"enable", "disable", "uninstall"}:
            result = registry.change(
                args.id, args.version, cast(Literal["enable", "disable", "uninstall"], action)
            )
        elif action == "run":
            with args.input.open("rb") as stream:
                raw = stream.read(MAX_MESSAGE_BYTES + 1)
            if len(raw) > MAX_MESSAGE_BYTES:
                raise ExtensionError("message-too-large", "the adapter input is too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ExtensionError("message-invalid", "input must be an object")
            result = registry.run(
                args.id, args.version, cast(Role, args.role), payload, timeout=args.timeout
            )
        else:
            raise AssertionError("unhandled extension command")
        print(dumps_json(result))
        return 1 if action == "run" and result["response"] is None else 0
    except ExtensionError as exc:
        print(dumps_json({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    except (ApplicationError, OSError, ValueError, sqlite3.Error, TypeError):
        print(
            dumps_json(
                {"code": "extension-operation-failed", "message": "the extension operation failed"}
            ),
            file=sys.stderr,
        )
        return 2
