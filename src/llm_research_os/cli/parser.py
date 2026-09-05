"""Argument parser for the researchos command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from llm_research_os.cli.contracts import DEFAULT_SCHEMA_CONTRACT, SCHEMA_CONTRACTS
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="researchos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a ResearchSpec document")
    validate.add_argument("document", type=Path)

    schema = subparsers.add_parser("schema", help="print, write, or check a JSON Schema")
    schema.add_argument(
        "--contract",
        choices=tuple(SCHEMA_CONTRACTS),
        default=DEFAULT_SCHEMA_CONTRACT,
    )
    schema_group = schema.add_mutually_exclusive_group()
    schema_group.add_argument("--output", type=Path)
    schema_group.add_argument("--check", type=Path)
    schema_group.add_argument(
        "--check-all",
        action="store_true",
        help="verify every registered committed schema against generated contracts",
    )

    diff = subparsers.add_parser("diff", help="compare two immutable ResearchSpec revisions")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)

    dry_run = subparsers.add_parser(
        "dry-run", help="compile a deterministic plan without executing any block"
    )
    dry_run.add_argument("document", type=Path, help="ResearchSpec YAML or JSON file")
    dry_run.add_argument(
        "--workflow",
        metavar="ID",
        help="exact workflow ID (required when the spec contains multiple workflows)",
    )
    dry_run.add_argument(
        "--registry",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="manifest file or non-recursive directory; repeat to add more",
    )
    dry_run.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="human-readable overview or versioned complete JSON",
    )

    authorize = subparsers.add_parser(
        "authorize",
        help="evaluate an exact plan-bound policy without executing any block",
    )
    authorize.add_argument("spec", type=Path, help="ResearchSpec YAML or JSON file")
    authorize.add_argument(
        "request",
        type=Path,
        help="PlanAuthorizationRequest v0alpha1 YAML or JSON file",
    )
    authorize.add_argument(
        "--workflow",
        metavar="ID",
        help="exact workflow ID (required when the spec contains multiple workflows)",
    )
    add_registry_arguments(authorize)

    authorizations = subparsers.add_parser(
        "authorizations",
        help="record and reconstruct auditable authorization evaluation facts",
    )
    authorization_commands = authorizations.add_subparsers(
        dest="authorizations_command",
        required=True,
    )
    authorization_record = authorization_commands.add_parser(
        "record",
        help="recompute and append one audit-only authorization fact",
    )
    authorization_record.add_argument("spec", type=Path, help="ResearchSpec YAML or JSON file")
    authorization_record.add_argument(
        "authorization_request",
        type=Path,
        help="PlanAuthorizationRequest v0alpha1 YAML or JSON file",
    )
    authorization_record.add_argument(
        "event_request",
        type=Path,
        help="PlanAuthorizationEventRequest v0alpha1 YAML or JSON file",
    )
    authorization_record.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    authorization_record.add_argument(
        "--workflow",
        metavar="ID",
        help="exact workflow ID (required when the spec contains multiple workflows)",
    )
    add_registry_arguments(authorization_record)
    authorization_find = authorization_commands.add_parser(
        "find",
        help="reconstruct audit-only authorization facts for one plan identity",
    )
    authorization_find.add_argument(
        "query",
        type=Path,
        help="PlanAuthorizationLineageQuery v0alpha1 YAML or JSON file",
    )
    authorization_find.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    add_event_format_argument(authorization_find)

    native = subparsers.add_parser(
        "native",
        help="review native-process launch contracts without executing them",
    )
    native_commands = native.add_subparsers(dest="native_command", required=True)
    native_preflight = native_commands.add_parser(
        "preflight",
        help="freeze one non-launchable native Python process review",
    )
    native_preflight.add_argument("spec", type=Path, help="ResearchSpec YAML or JSON file")
    native_preflight.add_argument(
        "authorization_request",
        type=Path,
        help="PlanAuthorizationRequest v0alpha1 YAML or JSON file",
    )
    native_preflight.add_argument(
        "preflight_request",
        type=Path,
        help="NativeProcessPreflightRequest v0alpha1 YAML or JSON file",
    )
    native_preflight.add_argument(
        "--workflow",
        metavar="ID",
        help="exact workflow ID (required when the spec contains multiple workflows)",
    )
    add_registry_arguments(native_preflight)

    blocks = subparsers.add_parser("blocks", help="inspect inert BlockManifest registrations")
    block_commands = blocks.add_subparsers(dest="blocks_command", required=True)
    blocks_list = block_commands.add_parser("list", help="list exact registered block versions")
    add_registry_arguments(blocks_list)
    blocks_show = block_commands.add_parser("show", help="show one exact block registration")
    blocks_show.add_argument("block_id", help="exact block ID")
    blocks_show.add_argument("--version", required=True, help="exact semantic version")
    add_registry_arguments(blocks_show)
    blocks_validate = block_commands.add_parser(
        "validate", help="validate one BlockManifest document"
    )
    blocks_validate.add_argument("manifest", type=Path, help="BlockManifest YAML or JSON file")
    blocks_validate.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="human-readable overview or versioned complete JSON",
    )

    events = subparsers.add_parser("events", help="query and replay stored ResearchEvents")
    event_commands = events.add_subparsers(dest="events_command", required=True)
    events_get = event_commands.add_parser("get", help="read one verified ResearchEvent")
    events_get.add_argument("database", type=Path)
    events_get.add_argument("event_id")
    add_event_format_argument(events_get)
    events_list = event_commands.add_parser("list", help="read one bounded page of events")
    events_list.add_argument("database", type=Path)
    events_list.add_argument(
        "--after-sequence",
        type=int,
        default=0,
        metavar="N",
        help="return events with sequence greater than N",
    )
    events_list.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help=f"maximum events to return (1..{MAX_READ_PAGE_SIZE})",
    )
    add_event_format_argument(events_list)
    events_replay = event_commands.add_parser(
        "replay", help="emit verified events as JSON Lines using paged reads"
    )
    events_replay.add_argument("database", type=Path)
    events_replay.add_argument(
        "--after-sequence",
        type=int,
        default=0,
        metavar="N",
        help="start after this global sequence",
    )
    events_replay.add_argument(
        "--page-size",
        type=int,
        default=100,
        metavar="N",
        help=f"store page size (1..{MAX_READ_PAGE_SIZE})",
    )
    events_verify = event_commands.add_parser(
        "verify", help="run full event-store integrity checks"
    )
    events_verify.add_argument("database", type=Path)
    add_event_format_argument(events_verify)

    runs = subparsers.add_parser("runs", help="execute and inspect controlled Runs")
    run_commands = runs.add_subparsers(dest="runs_command", required=True)
    runs_simulate = run_commands.add_parser(
        "simulate",
        help="append one deterministic simulated lifecycle",
    )
    runs_simulate.add_argument("spec", type=Path, help="ResearchSpec YAML or JSON file")
    runs_simulate.add_argument(
        "request",
        type=Path,
        help="SimulationRequest v0alpha1 YAML or JSON file",
    )
    runs_simulate.add_argument(
        "database",
        type=Path,
        help="SQLite event store to create or resume",
    )
    add_registry_arguments(runs_simulate)
    runs_cancel = run_commands.add_parser(
        "cancel",
        help="append one cancellation request without claiming the target stopped",
    )
    runs_cancel.add_argument(
        "request",
        type=Path,
        help="RunCancellationRequest v0alpha1 YAML or JSON file",
    )
    runs_cancel.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    add_event_format_argument(runs_cancel)

    artifacts = subparsers.add_parser(
        "artifacts",
        help="import and verify immutable local artifact objects",
    )
    artifact_commands = artifacts.add_subparsers(dest="artifacts_command", required=True)
    artifacts_put = artifact_commands.add_parser(
        "put",
        help="stream one regular file into an existing local artifact root",
    )
    artifacts_put.add_argument("root", type=Path, help="existing local artifact root")
    artifacts_put.add_argument("source", type=Path, help="regular source file to import")
    add_event_format_argument(artifacts_put)
    artifacts_verify = artifact_commands.add_parser(
        "verify",
        help="re-hash one stored object and verify its digest",
    )
    artifacts_verify.add_argument("root", type=Path, help="existing local artifact root")
    artifacts_verify.add_argument("digest", help="sha256:<64 lowercase hex> object digest")
    add_event_format_argument(artifacts_verify)

    models = subparsers.add_parser(
        "models",
        help="record deterministic mock model calls as EventStore facts",
    )
    model_commands = models.add_subparsers(dest="models_command", required=True)
    models_generate = model_commands.add_parser(
        "generate",
        help="append ai.call.started and ai.call.completed for one fixture",
    )
    models_generate.add_argument(
        "request",
        type=Path,
        help="ModelGenerateRequest v0alpha1 YAML or JSON file",
    )
    models_generate.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    models_generate.add_argument(
        "--fixture",
        required=True,
        type=Path,
        metavar="PATH",
        help="ModelFixture v0alpha1 YAML or JSON file; prompt/output stay off events",
    )
    models_generate.add_argument(
        "--artifacts",
        type=Path,
        metavar="ROOT",
        help="optional existing local artifact root for prompt/output object refs",
    )
    add_event_format_argument(models_generate)

    proposals = subparsers.add_parser(
        "proposals",
        help="record structured research proposals as EventStore facts",
    )
    proposal_commands = proposals.add_subparsers(dest="proposals_command", required=True)
    proposal_submit = proposal_commands.add_parser(
        "submit",
        help="append one proposal.submitted fact",
    )
    proposal_submit.add_argument(
        "request",
        type=Path,
        help="ProposalSubmitRequest v0alpha1 YAML or JSON file",
    )
    proposal_submit.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    add_event_format_argument(proposal_submit)

    dissents = subparsers.add_parser(
        "dissents",
        help="record structured objections as EventStore facts",
    )
    dissent_commands = dissents.add_subparsers(dest="dissents_command", required=True)
    dissent_record = dissent_commands.add_parser(
        "record",
        help="append one dissent.recorded fact",
    )
    dissent_record.add_argument(
        "request",
        type=Path,
        help="DissentRecordRequest v0alpha1 YAML or JSON file",
    )
    dissent_record.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    add_event_format_argument(dissent_record)

    decisions = subparsers.add_parser(
        "decisions",
        help="record researcher decisions with rationale as EventStore facts",
    )
    decision_commands = decisions.add_subparsers(dest="decisions_command", required=True)
    decision_record = decision_commands.add_parser(
        "record",
        help="append one decision.recorded fact",
    )
    decision_record.add_argument(
        "request",
        type=Path,
        help="DecisionRecordRequest v0alpha1 YAML or JSON file",
    )
    decision_record.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    add_event_format_argument(decision_record)

    research = subparsers.add_parser(
        "research",
        help="rebuild read-only research projections from EventStore",
    )
    research_commands = research.add_subparsers(dest="research_command", required=True)
    research_ledger = research_commands.add_parser(
        "ledger",
        help="rebuild the ResearchLedger for one project",
    )
    research_ledger.add_argument(
        "database",
        type=Path,
        help="existing SQLite event store; missing paths are not created",
    )
    research_ledger.add_argument(
        "--project",
        required=True,
        metavar="ID",
        help="projectId to fold",
    )
    add_event_format_argument(research_ledger)
    return parser


def add_event_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="human-readable overview or deterministic JSON",
    )


def add_registry_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registry",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="manifest file or non-recursive directory; repeat to add more",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="human-readable overview or versioned complete JSON",
    )
