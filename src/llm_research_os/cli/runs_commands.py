"""Simulated run and cancellation-request commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.execution import (
    SimulatedRuntime,
    SimulationDisposition,
    SimulationError,
    load_simulation_request,
)
from llm_research_os.runs import (
    AttemptCancellationTarget,
    RunCancellationTarget,
    RunSnapshot,
    RunStateError,
    load_run_cancellation_request,
    request_cancellation,
)
from llm_research_os.spec.io import SpecLoadError, load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore, EventStoreError


def run_runs(args: argparse.Namespace) -> int:
    if args.runs_command == "simulate":
        return _runs_simulate(
            args.spec,
            args.request,
            args.database,
            args.registry,
            args.format,
        )
    if args.runs_command == "cancel":
        return _runs_cancel(args.request, args.database, args.format)
    raise AssertionError(f"unhandled runs command: {args.runs_command}")


def _runs_simulate(
    spec_path: Path,
    request_path: Path,
    database: Path,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(spec_path, reject_symlinks=True))
        request = load_simulation_request(request_path)
        registry = build_registry(registry_paths)
        with EventStore(database) as store:
            result = SimulatedRuntime(
                store,
                registry,
                project_id=str(spec.metadata.id),
                run_id=request.run_id,
            ).run(spec, request.runtime_request())
    except (
        EventStoreError,
        ManifestLoadError,
        OSError,
        RegistryError,
        RunStateError,
        SimulationError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_simulation_result(
        result.snapshot,
        result.disposition,
        len(result.stored),
        output_format,
    )
    return 0 if result.disposition is SimulationDisposition.COMPLETED else 1


def _runs_cancel(request_path: Path, database: Path, output_format: str) -> int:
    try:
        request = load_run_cancellation_request(request_path)
        with EventStore(database, require_existing=True) as store:
            result = request_cancellation(store, request)
    except (
        EventStoreError,
        OSError,
        RunStateError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_cancellation_result(result.snapshot, request.target, output_format)
    return 0


def _print_simulation_result(
    snapshot: RunSnapshot,
    disposition: SimulationDisposition,
    appended_events: int,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = snapshot.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print(f"simulation disposition: {disposition.value}")
    print(f"project: {safe_text(snapshot.project_id)}")
    print(f"run: {safe_text(snapshot.run_id)}")
    print(f"workflow: {safe_text(snapshot.workflow_id)}")
    print(f"status: {snapshot.status.value}")
    print(f"appended events: {appended_events}")
    print(f"last sequence: {snapshot.last_sequence}")
    print("scientific conclusion: not evaluated")


def _print_cancellation_result(
    snapshot: RunSnapshot,
    target: RunCancellationTarget | AttemptCancellationTarget,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = snapshot.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print("cancellation request: recorded")
    print(f"project: {safe_text(snapshot.project_id)}")
    print(f"run: {safe_text(snapshot.run_id)}")
    if isinstance(target, AttemptCancellationTarget):
        print(f"target: attempt {safe_text(target.attempt_id)}")
        print("attempt cancellation requested: true")
    else:
        print("target: run")
    print(f"run status: {snapshot.status.value}")
    print(f"run cancellation requested: {str(snapshot.cancellation_requested).lower()}")
    print(f"last sequence: {snapshot.last_sequence}")
    print("process signal sent: false")
    print("cancellation outcome: not observed")
