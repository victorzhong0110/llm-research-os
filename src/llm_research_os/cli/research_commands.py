"""Proposal, dissent, decision, and research-ledger commands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.errors import (
    ResearchControlError,
    ResearchDecisionError,
    ResearchLedgerError,
    ResearchPayloadError,
    ResearchRequestError,
)
from llm_research_os.research.models import research_ledger_document
from llm_research_os.research.requests import (
    DecisionRecordRequestDocument,
    DissentRecordRequestDocument,
    ProposalSubmitRequestDocument,
    load_decision_record_request,
    load_dissent_record_request,
    load_proposal_submit_request,
)
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStore, EventStoreError
from llm_research_os.storage.models import StoredEvent

_INPUT_ERRORS = (
    EventStoreError,
    OSError,
    ResearchControlError,
    ResearchPayloadError,
    ResearchRequestError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_proposals(args: argparse.Namespace) -> int:
    if args.proposals_command == "submit":
        return _append_research_request(
            load_proposal_submit_request,
            args.request,
            args.database,
            args.format,
        )
    raise AssertionError(f"unhandled proposals command: {args.proposals_command}")


def run_dissents(args: argparse.Namespace) -> int:
    if args.dissents_command == "record":
        return _append_research_request(
            load_dissent_record_request,
            args.request,
            args.database,
            args.format,
        )
    raise AssertionError(f"unhandled dissents command: {args.dissents_command}")


def run_decisions(args: argparse.Namespace) -> int:
    if args.decisions_command == "record":
        return _append_research_request(
            load_decision_record_request,
            args.request,
            args.database,
            args.format,
        )
    raise AssertionError(f"unhandled decisions command: {args.decisions_command}")


def run_research(args: argparse.Namespace) -> int:
    if args.research_command == "ledger":
        return _research_ledger(args.database, args.project, args.format)
    raise AssertionError(f"unhandled research command: {args.research_command}")


def _append_research_request(
    loader: Callable[
        [Path],
        ProposalSubmitRequestDocument
        | DissentRecordRequestDocument
        | DecisionRecordRequestDocument,
    ],
    request_path: Path,
    database: Path,
    output_format: str,
) -> int:
    try:
        request = loader(request_path)
        with EventStore(database, require_existing=True) as store:
            result = ResearchControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except ResearchLedgerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(result.stored, output_format)
    return 0


def _research_ledger(database: Path, project_id: str, output_format: str) -> int:
    try:
        with EventStore(database, require_existing=True) as store:
            head = ResearchControl(store, project_id=project_id).rebuild()
    except ResearchLedgerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    payload = research_ledger_document(head.snapshot)
    if output_format == "json":
        print(dumps_json(payload))
        return 0
    print(f"project: {safe_text(head.snapshot.project_id)}")
    print(f"last sequence: {head.snapshot.last_sequence}")
    print(f"proposals: {len(head.snapshot.proposals)}")
    print(f"dissents: {len(head.snapshot.dissents)}")
    print(f"decisions: {head.snapshot.decision_count}")
    print(f"rationale characters: {head.snapshot.rationale_characters}")
    print(f"overridden dissents: {head.snapshot.overridden_dissent_count}")
    print("questions: 0")
    return 0


def _print_receipt(stored: StoredEvent, output_format: str) -> None:
    event = stored.event
    object_id = _object_id(event.data.payload)
    if output_format == "json":
        print(
            dumps_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "ResearchFactReceipt",
                    "eventId": event.id,
                    "type": event.type,
                    "sequence": event.sequence,
                    "projectId": event.data.project_id,
                    "objectId": object_id,
                }
            )
        )
        return
    print("research fact: recorded")
    print(f"type: {safe_text(event.type)}")
    print(f"event: {safe_text(event.id)}")
    print(f"object: {safe_text(object_id)}")
    print(f"project: {safe_text(event.data.project_id)}")
    print(f"sequence: {safe_text(event.sequence)}")


def _object_id(payload: dict[str, object]) -> str:
    for key in ("proposalId", "dissentId", "decisionId"):
        value = payload.get(key)
        if type(value) is str:
            return value
    raise ResearchDecisionError(
        "committed payload is missing its object id",
        code="missing-object-id",
    )
