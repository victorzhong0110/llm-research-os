"""Local Markdown/PDF evidence import commands."""

from __future__ import annotations

import argparse

from pydantic import ValidationError

from llm_research_os.artifacts import ArtifactStoreError, LocalArtifactStore
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.evidence.control import EvidenceControl, EvidenceImportResult
from llm_research_os.evidence.errors import EvidenceError, EvidenceRequestError
from llm_research_os.evidence.requests import load_evidence_import_request
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStore, EventStoreError

_INPUT_ERRORS = (
    ArtifactStoreError,
    EventStoreError,
    EvidenceRequestError,
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_evidence(args: argparse.Namespace) -> int:
    if args.evidence_command == "import":
        return _import_source(args)
    raise AssertionError(f"unhandled evidence command: {args.evidence_command}")


def _import_source(args: argparse.Namespace) -> int:
    try:
        request = load_evidence_import_request(args.request)
        artifacts = LocalArtifactStore(args.artifacts)
        with EventStore(args.database, require_existing=True) as store:
            result = EvidenceControl(store, project_id=request.project_id).import_source(
                request,
                args.source,
                artifacts,
            )
    except EvidenceError as rec:
        print_error(rec, args.format)
        return 1
    except _INPUT_ERRORS as rec:
        print_error(rec, args.format)
        return 2
    _print_receipt(result, args.format)
    return 0


def _print_receipt(result: EvidenceImportResult, output_format: str) -> None:
    event = result.stored.event
    evidence_id = event.data.payload.get("evidenceId")
    if type(evidence_id) is not str:
        raise EvidenceError("committed payload is missing evidenceId", code="missing-evidence-id")
    if output_format == "json":
        print(
            dumps_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "EvidenceImportReceipt",
                    "evidenceId": evidence_id,
                    "eventId": event.id,
                    "sequence": event.sequence,
                    "projectId": event.data.project_id,
                    "snapshotDigest": result.snapshot_digest,
                    "textDigest": result.text_digest,
                    "license": event.data.payload.get("license"),
                }
            )
        )
        return
    print("evidence: imported")
    print(f"evidence: {safe_text(evidence_id)}")
    print(f"event: {safe_text(event.id)}")
    print(f"project: {safe_text(event.data.project_id)}")
    print(f"sequence: {safe_text(event.sequence)}")
