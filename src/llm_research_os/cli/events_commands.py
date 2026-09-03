"""Event store query, replay, and integrity commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from llm_research_os.cli.output import (
    dumps_json,
    event_document,
    print_error,
    print_event,
    print_problem,
    safe_text,
)
from llm_research_os.problem import ProblemDetail, ProblemReport
from llm_research_os.projections import replay_events
from llm_research_os.storage import EventStore, EventStoreError


def run_events(args: argparse.Namespace) -> int:
    if args.events_command == "get":
        return _events_get(args.database, args.event_id, args.format)
    if args.events_command == "list":
        return _events_list(args.database, args.after_sequence, args.limit, args.format)
    if args.events_command == "replay":
        return _events_replay(args.database, args.after_sequence, args.page_size)
    if args.events_command == "verify":
        return _events_verify(args.database, args.format)
    raise AssertionError(f"unhandled events command: {args.events_command}")


def _events_get(database: Path, event_id: str, output_format: str) -> int:
    try:
        with EventStore(database, create=False) as store:
            stored = store.get_event(event_id)
    except (EventStoreError, OSError, ValueError) as exc:
        print_error(exc, output_format)
        return 2
    if stored is None:
        print_problem(
            ProblemReport(
                apiVersion="researchos.dev/v0alpha1",
                kind="ProblemReport",
                valid=False,
                errors=(
                    ProblemDetail(
                        message=f"event not found: {event_id}",
                        type="event-not-found",
                    ),
                ),
            ),
            output_format,
        )
        return 1
    print_event(stored.event, output_format)
    return 0


def _events_list(
    database: Path,
    after_sequence: int,
    limit: int,
    output_format: str,
) -> int:
    try:
        with EventStore(database, create=False) as store:
            page = store.read_events(after_sequence=after_sequence, limit=limit)
            events = [item.event for item in page]
    except (EventStoreError, OSError, ValueError) as exc:
        print_error(exc, output_format)
        return 2
    if output_format == "json":
        payload = {"events": [event_document(event) for event in events]}
        print(dumps_json(payload))
        return 0
    if not events:
        print("events: 0")
        return 0
    for event in events:
        print(
            f"{safe_text(event.sequence)} {safe_text(event.id)} "
            f"{safe_text(event.type)} {safe_text(event.streamid)}"
        )
    return 0


def _events_replay(database: Path, after_sequence: int, page_size: int) -> int:
    try:
        with EventStore(database, create=False) as store:
            for stored in replay_events(
                store,
                after_sequence=after_sequence,
                page_size=page_size,
            ):
                print(dumps_json(event_document(stored.event), indent=None))
    except (EventStoreError, OSError, ValueError) as exc:
        print_error(exc, "json")
        return 2
    return 0


def _events_verify(database: Path, output_format: str) -> int:
    try:
        with EventStore(database, create=False) as store:
            event_count = store.verify_integrity()
    except (EventStoreError, OSError, ValueError) as exc:
        print_error(exc, output_format)
        return 2
    if output_format == "json":
        print(dumps_json({"eventCount": event_count, "valid": True}))
        return 0
    print(f"valid: {event_count} event(s)")
    return 0
