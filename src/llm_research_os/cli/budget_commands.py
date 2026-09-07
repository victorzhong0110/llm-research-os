"""Human-recorded project budget limit commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.errors import BudgetError, BudgetRequestError
from llm_research_os.budget.requests import load_budget_limit_request
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStore, EventStoreError
from llm_research_os.storage.models import StoredEvent

_INPUT_ERRORS = (
    EventStoreError,
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_budget(args: argparse.Namespace) -> int:
    if args.budget_command == "record-limit":
        return _record_limit(args.request, args.database, args.format)
    raise AssertionError(f"unhandled budget command: {args.budget_command}")


def _record_limit(request_path: Path, database: Path, output_format: str) -> int:
    try:
        request = load_budget_limit_request(request_path)
        with EventStore(database, require_existing=True) as store:
            stored = BudgetControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except BudgetRequestError as exc:
        print_error(exc, output_format)
        return 2
    except BudgetError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(stored, output_format)
    return 0


def _print_receipt(stored: StoredEvent, output_format: str) -> None:
    if output_format == "json":
        print(
            dumps_json(
                {
                    "eventId": stored.event.id,
                    "type": stored.event.type,
                    "sequence": stored.sequence,
                    "projectId": stored.event.data.project_id,
                }
            )
        )
        return
    print(f"event: {safe_text(stored.event.id)}")
    print(f"type: {safe_text(stored.event.type)}")
    print(f"sequence: {stored.sequence}")
    print(f"project: {safe_text(stored.event.data.project_id)}")
