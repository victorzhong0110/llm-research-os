"""M2-0 CPU Worker checkpoint command. This path does not close Issue #38."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.artifacts.errors import ArtifactStoreError
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.execution.errors import (
    PlanAuthorizationError,
    PlanAuthorizationRecordError,
    SimulationError,
)
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.m2.oci_prove import prove_oci_loop
from llm_research_os.m2.prove import M2CheckpointResult, prove_cpu_loop
from llm_research_os.report.errors import ReportError
from llm_research_os.runs.errors import RunStateError
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStoreError
from llm_research_os.workers.errors import WorkerError, WorkerRequestError

_INPUT_ERRORS = (
    ArtifactStoreError,
    EventStoreError,
    OSError,
    PlanningInputError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_m2(args: argparse.Namespace) -> int:
    if args.m2_command == "prove":
        artifacts = args.artifacts
        if artifacts is None:
            artifacts = args.database.with_name(f"{args.database.stem}-artifacts")
        return _prove(prove_cpu_loop, args.corpus, args.database, artifacts, args.format)
    if args.m2_command == "oci":
        artifacts = args.artifacts
        if artifacts is None:
            artifacts = args.database.with_name(f"{args.database.stem}-artifacts")
        return _prove(prove_oci_loop, args.corpus, args.database, artifacts, args.format)
    raise AssertionError(f"unhandled m2 command: {args.m2_command}")


def _prove(
    loop: Callable[[Path, Path, Path], M2CheckpointResult],
    corpus: Path,
    database: Path,
    artifacts: Path,
    output_format: str,
) -> int:
    try:
        result = loop(corpus, database, artifacts)
    except M2CheckpointError as exc:
        print_error(exc, output_format)
        return 2
    except (
        PlanAuthorizationError,
        PlanAuthorizationRecordError,
        ReportError,
        RunStateError,
        SimulationError,
        WorkerError,
    ) as exc:
        print_error(exc, output_format)
        return 1
    except WorkerRequestError as exc:
        print_error(exc, output_format)
        return 2
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(result, output_format)
    return 0


def _print_receipt(result: M2CheckpointResult, output_format: str) -> None:
    if output_format == "json":
        print(
            dumps_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "M2CheckpointReceipt",
                    "projectId": result.project_id,
                    "runId": result.run_id,
                    "workerId": result.worker_id,
                    "imageDigest": result.image_digest,
                    "artifactDigest": result.artifact_digest,
                    "eventTypes": list(result.event_types),
                    "eventIds": list(result.event_ids),
                }
            )
        )
        return
    print("m2 checkpoint: recorded")
    print(f"project: {safe_text(result.project_id)}")
    print(f"run: {safe_text(result.run_id)}")
    print(f"worker: {safe_text(result.worker_id)}")
    print(f"image: {safe_text(result.image_digest)}")
    print(f"artifact: {safe_text(result.artifact_digest)}")
    print(f"events: {safe_text(len(result.event_types))}")
    print()
    print(result.report_markdown, end="")
