"""Inert BlockManifest inspection commands."""

from __future__ import annotations

import argparse
import json

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError, load_manifest
from llm_research_os.blocks.registry import RegistryError, UnknownBlockError, build_registry
from llm_research_os.blocks.reports import (
    BlockManifestValidationReport,
    BlockRegistryEntry,
    BlockRegistryReport,
)
from llm_research_os.canonical import content_digest
from llm_research_os.cli.output import print_error
from llm_research_os.spec.io import SpecLoadError


def run_blocks(args: argparse.Namespace) -> int:
    if args.blocks_command == "validate":
        try:
            manifest = load_manifest(args.manifest)
        except (ManifestLoadError, SpecLoadError, ValidationError) as exc:
            print_error(exc, args.format)
            return 2
        manifest_payload = manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        result = BlockManifestValidationReport(
            apiVersion="researchos.dev/v0alpha1",
            kind="BlockManifestValidationReport",
            valid=True,
            id=manifest.metadata.id,
            version=manifest.metadata.version,
            manifestDigest=content_digest(manifest_payload),
        )
        _print_manifest_result(result, args.format)
        return 0

    try:
        registry = build_registry(args.registry)
    except (ManifestLoadError, RegistryError, SpecLoadError, ValidationError, OSError) as exc:
        print_error(exc, args.format)
        return 2

    blocks = registry.blocks()
    if args.blocks_command == "show":
        try:
            blocks = (registry.resolve(args.block_id, args.version),)
        except UnknownBlockError as exc:
            print_error(exc, args.format)
            return 1
    entries = tuple(
        BlockRegistryEntry.model_validate(
            block.public_detail() if args.blocks_command == "show" else block.public_summary()
        )
        for block in blocks
    )
    report = BlockRegistryReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="BlockRegistryReport",
        operation=args.blocks_command,
        registryDigest=registry.digest(),
        blocks=entries,
    )
    _print_registry_result(report, args.format)
    return 0


def _print_manifest_result(report: BlockManifestValidationReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"valid block manifest: {report.id}@{report.version} ({report.manifest_digest})")


def _print_registry_result(report: BlockRegistryReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.public_payload()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"registry: {report.registry_digest}")
    for block in report.blocks:
        print(f"{block.id}@{block.version} ({block.runtime_type.value}, {block.manifest_digest})")
        if report.operation == "show":
            if block.manifest is None:
                raise RuntimeError("show reports always carry the resolved manifest")
            manifest = block.manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
            print("manifest:")
            print(
                json.dumps(manifest, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
            )
