"""Plan authorization evaluation, recording, and lineage commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.output import dumps_json, print_error, print_event, safe_text
from llm_research_os.execution import (
    PlanAuthorizationError,
    PlanAuthorizationEventRecordResult,
    PlanAuthorizationLineageError,
    PlanAuthorizationLineageReport,
    PlanAuthorizationRecordError,
    PlanAuthorizationReport,
    PlanAuthorizationStatus,
    PlanningInputError,
    TrustedKernel,
    authorize_plan,
    load_plan_authorization_event_request,
    load_plan_authorization_lineage_query,
    load_plan_authorization_request,
    query_plan_authorization_lineage,
    record_plan_authorization_event,
)
from llm_research_os.spec.io import SpecLoadError, load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore, EventStoreError


def run_authorize(args: argparse.Namespace) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(args.spec, reject_symlinks=True))
        request = load_plan_authorization_request(args.request)
        registry = build_registry(args.registry)
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=args.workflow)
        result = authorize_plan(dry_run, request.policy())
        report = PlanAuthorizationReport.from_result(result)
    except (
        ManifestLoadError,
        OSError,
        PlanAuthorizationError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, args.format)
        return 2
    _print_authorization_result(report, args.format)
    return 0 if report.status is PlanAuthorizationStatus.AUTHORIZED else 1


def run_authorizations(args: argparse.Namespace) -> int:
    if args.authorizations_command == "record":
        return _record_authorization_event(
            args.spec,
            args.authorization_request,
            args.event_request,
            args.database,
            args.workflow,
            args.registry,
            args.format,
        )
    if args.authorizations_command == "find":
        return _find_authorization_lineage(args.query, args.database, args.format)
    raise AssertionError(f"unhandled authorizations command: {args.authorizations_command}")


def _record_authorization_event(
    spec_path: Path,
    authorization_request_path: Path,
    event_request_path: Path,
    database: Path,
    workflow_id: str | None,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(spec_path, reject_symlinks=True))
        authorization_request = load_plan_authorization_request(authorization_request_path)
        event_request = load_plan_authorization_event_request(event_request_path)
        registry = build_registry(registry_paths)
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
        with EventStore(database, require_existing=True) as store:
            result = record_plan_authorization_event(
                store,
                dry_run,
                authorization_request.policy(),
                event_request,
            )
    except (
        EventStoreError,
        ManifestLoadError,
        OSError,
        PlanAuthorizationError,
        PlanAuthorizationRecordError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_authorization_event_result(result, output_format)
    return 0 if result.authorization.status is PlanAuthorizationStatus.AUTHORIZED else 1


def _find_authorization_lineage(
    query_path: Path,
    database: Path,
    output_format: str,
) -> int:
    try:
        query = load_plan_authorization_lineage_query(query_path)
        with EventStore(database, create=False) as store:
            report = query_plan_authorization_lineage(store, query)
    except (
        EventStoreError,
        OSError,
        PlanAuthorizationLineageError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_authorization_lineage_result(report, output_format)
    return 0


def _print_authorization_result(
    report: PlanAuthorizationReport,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print(f"plan authorization: {report.status.value}")
    print(f"spec digest: {report.binding.spec_digest}")
    print(f"registry digest: {report.binding.registry_digest}")
    print(f"plan digest: {report.binding.plan_digest}")
    print(f"decision digest: {report.decision_digest}")
    print(f"missing capabilities: {len(report.missing_capabilities)}")
    print(f"missing permissions: {len(report.missing_permissions)}")
    print(f"pending requirements: {len(report.pending_requirements)}")
    print(f"denied requirements: {len(report.denied_requirements)}")
    print("approval authentication: not-authenticated")
    print("persistent receipt: false")
    print("execution performed: false")
    print("side effects: 0 blocks, 0 network requests, 0 writes, 0 paid actions")


def _print_authorization_event_result(
    result: PlanAuthorizationEventRecordResult,
    output_format: str,
) -> None:
    if output_format == "json":
        print_event(result.stored.event, "json")
        return
    print("authorization event: recorded")
    print(f"event id: {safe_text(result.stored.event.id)}")
    print(f"sequence: {result.stored.event.sequence}")
    print(f"event digest: {result.stored.digest}")
    print(f"plan authorization: {result.authorization.status.value}")
    print(f"decision digest: {result.authorization.decision_digest}")
    print("approval authentication: not-authenticated")
    print("event authority: audit-only")
    print("execution performed: false")


def _print_authorization_lineage_result(
    report: PlanAuthorizationLineageReport,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        print(dumps_json(payload))
        return
    print("authorization lineage: reconstructed")
    print(f"matches: {report.match_count}")
    print(f"high-water sequence: {report.high_water_sequence}")
    print("approval authentication: not-authenticated")
    print("event authority: audit-only")
    print("execution performed: false")
    print("runtime consumption: not-consumed")
    print("persistent writes: false")
    for match in report.matches:
        print(
            f"match sequence {match.sequence}: {safe_text(match.event_id)} "
            f"status={match.status.value}"
        )
