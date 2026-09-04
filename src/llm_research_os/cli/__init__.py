"""Command-line entry point for the M0 protocol, planning and event-query toolchain."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import NoReturn

from llm_research_os.cli.artifacts_commands import run_artifacts
from llm_research_os.cli.authz_commands import run_authorizations, run_authorize
from llm_research_os.cli.blocks_commands import run_blocks
from llm_research_os.cli.events_commands import run_events
from llm_research_os.cli.models_commands import run_models
from llm_research_os.cli.native_commands import run_native
from llm_research_os.cli.parser import build_parser
from llm_research_os.cli.research_commands import (
    run_decisions,
    run_dissents,
    run_proposals,
    run_research,
)
from llm_research_os.cli.runs_commands import run_runs
from llm_research_os.cli.spec_commands import run_diff, run_dry_run, run_schema, run_validate

_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "validate": run_validate,
    "schema": run_schema,
    "diff": run_diff,
    "dry-run": run_dry_run,
    "authorize": run_authorize,
    "authorizations": run_authorizations,
    "native": run_native,
    "blocks": run_blocks,
    "events": run_events,
    "runs": run_runs,
    "artifacts": run_artifacts,
    "models": run_models,
    "proposals": run_proposals,
    "dissents": run_dissents,
    "decisions": run_decisions,
    "research": run_research,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        handler = _COMMANDS[args.command]
    except KeyError:
        raise AssertionError(f"unhandled command: {args.command}") from None
    return handler(args)


def entrypoint() -> NoReturn:
    raise SystemExit(main())
