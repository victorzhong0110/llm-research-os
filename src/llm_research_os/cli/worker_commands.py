"""Worker registration and HMAC grant commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStore, EventStoreError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.workers.binding import require_authorized_execution_citation
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.errors import WorkerError, WorkerRequestError
from llm_research_os.workers.requests import (
    load_authorization_grant_request,
    load_worker_register_request,
)

_INPUT_ERRORS = (
    EventStoreError,
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_grants(args: argparse.Namespace) -> int:
    if args.grants_command == "record":
        return _record_grant(args.request, args.database, args.format)
    raise AssertionError(f"unhandled grants command: {args.grants_command}")


def run_workers(args: argparse.Namespace) -> int:
    if args.workers_command == "register":
        return _register_worker(args.request, args.database, args.format)
    raise AssertionError(f"unhandled workers command: {args.workers_command}")


def _record_grant(request_path: Path, database: Path, output_format: str) -> int:
    try:
        request = load_authorization_grant_request(request_path)
        with EventStore(database, require_existing=True) as store:
            require_authorized_execution_citation(
                store,
                project_id=request.project_id,
                event_id=request.authorization_event_id,
                sequence=request.authorization_sequence,
            )
            stored = WorkerControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except WorkerRequestError as exc:
        print_error(exc, output_format)
        return 2
    except WorkerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(stored, output_format)
    return 0


def _register_worker(request_path: Path, database: Path, output_format: str) -> int:
    try:
        request = load_worker_register_request(request_path)
        with EventStore(database, require_existing=True) as store:
            stored = WorkerControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except WorkerRequestError as exc:
        print_error(exc, output_format)
        return 2
    except WorkerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(stored, output_format)
    return 0


def _print_receipt(stored: StoredEvent, output_format: str) -> int | None:
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
        return None
    print(f"event: {safe_text(stored.event.id)}")
    print(f"type: {safe_text(stored.event.type)}")
    print(f"sequence: {stored.sequence}")
    print(f"project: {safe_text(stored.event.data.project_id)}")
    return None
