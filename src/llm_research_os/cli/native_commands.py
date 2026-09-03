"""Native-process preflight review commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.output import dumps_json, print_error
from llm_research_os.execution import (
    NativeProcessPreflightError,
    NativeProcessPreflightReport,
    PlanningInputError,
    TrustedKernel,
    load_native_process_preflight_request,
    load_plan_authorization_request,
    preflight_native_process,
)
from llm_research_os.spec.io import SpecLoadError, load_document
from llm_research_os.spec.models import ResearchSpec


def run_native(args: argparse.Namespace) -> int:
    if args.native_command == "preflight":
        return _native_preflight(
            args.spec,
            args.authorization_request,
            args.preflight_request,
            args.workflow,
            args.registry,
            args.format,
        )
    raise AssertionError(f"unhandled native command: {args.native_command}")


def _native_preflight(
    spec_path: Path,
    authorization_request_path: Path,
    preflight_request_path: Path,
    workflow_id: str | None,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(spec_path, reject_symlinks=True))
        authorization_request = load_plan_authorization_request(authorization_request_path)
        preflight_request = load_native_process_preflight_request(preflight_request_path)
        registry = build_registry(registry_paths)
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
        result = preflight_native_process(
            dry_run,
            registry,
            authorization_request.policy(),
            preflight_request.policy(),
        )
        report = NativeProcessPreflightReport.from_result(result)
    except (
        ManifestLoadError,
        NativeProcessPreflightError,
        OSError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_native_process_preflight(report, output_format)
    return 0


def _print_native_process_preflight(
    report: NativeProcessPreflightReport,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print(f"native process preflight: {report.status}")
    print(f"preflight digest: {report.preflight_digest}")
    print(f"task path: /{'/'.join(report.task.task_path)}")
    print(f"entrypoint digest: {report.task.entrypoint_digest}")
    print("launch allowed: false")
    print("authorization authentication: not-authenticated")
    print("authorization persistence: not-persisted")
    print("process isolation enforced: false")
    print("execution performed: false")
    print(
        "side effects: 0 blocks, 0 entrypoint imports, 0 processes, 0 signals, "
        "0 network requests, 0 writes, 0 paid actions"
    )
