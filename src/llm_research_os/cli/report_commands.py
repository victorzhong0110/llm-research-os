"""Static HTML/Markdown report rebuilt from EventStore facts."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.budget.errors import BudgetError
from llm_research_os.cli.output import print_error
from llm_research_os.report import ReportError, build_run_report, render_html, render_markdown
from llm_research_os.research.errors import ResearchLedgerError
from llm_research_os.runs.errors import RunStateError
from llm_research_os.storage import EventStore, EventStoreError

_INPUT_ERRORS = (
    BudgetError,
    EventStoreError,
    OSError,
    ResearchLedgerError,
    RunStateError,
    ValidationError,
    ValueError,
)


def run_report(args: argparse.Namespace) -> int:
    return _report_run(args.run_id, args.database, args.project, args.format)


def _report_run(
    run_id: str,
    database: Path,
    project_id: str | None,
    output_format: str,
) -> int:
    try:
        with EventStore(database, create=False) as store:
            report = build_run_report(store, run_id, project_id=project_id)
    except ReportError as exc:
        print_error(exc, "text")
        return 1 if exc.code == "run-not-found" else 2
    except _INPUT_ERRORS as exc:
        print_error(exc, "text")
        return 2
    if output_format == "html":
        print(render_html(report), end="")
        return 0
    print(render_markdown(report), end="")
    return 0
