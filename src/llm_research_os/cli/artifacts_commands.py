"""Local artifact object import and verify commands."""

from __future__ import annotations

import argparse

from pydantic import ValidationError

from llm_research_os.artifacts import (
    ArtifactNotFoundError,
    ArtifactObjectReport,
    ArtifactStoreError,
    LocalArtifactStore,
)
from llm_research_os.cli.output import dumps_json, print_error


def run_artifacts(args: argparse.Namespace) -> int:
    try:
        store = LocalArtifactStore(args.root)
        if args.artifacts_command == "put":
            record = store.put(args.source)
            report = ArtifactObjectReport.from_record(record, operation="put")
        elif args.artifacts_command == "verify":
            record = store.verify(args.digest)
            report = ArtifactObjectReport.from_record(record, operation="verify")
        else:
            raise AssertionError(f"unhandled artifacts command: {args.artifacts_command}")
    except ArtifactNotFoundError as exc:
        print_error(exc, args.format)
        return 1
    except (ArtifactStoreError, OSError, ValidationError, ValueError) as exc:
        print_error(exc, args.format)
        return 2
    _print_artifact_result(report, args.format)
    return 0


def _print_artifact_result(report: ArtifactObjectReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print(f"artifact operation: {report.operation}")
    print(f"digest: {report.digest}")
    print(f"size bytes: {report.size_bytes}")
    print(f"storage key: {report.storage_key}")
    print("integrity verified: true")
