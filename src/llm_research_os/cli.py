"""Command-line entry point for the M0 protocol and planning toolchain."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError, load_manifest
from llm_research_os.blocks.registry import RegistryError, UnknownBlockError, build_registry
from llm_research_os.blocks.report_schema import canonical_schema as canonical_block_report_schema
from llm_research_os.blocks.report_schema import schema_matches as block_report_schema_matches
from llm_research_os.blocks.report_schema import write_schema as write_block_report_schema
from llm_research_os.blocks.reports import (
    BlockManifestValidationReport,
    BlockRegistryEntry,
    BlockRegistryReport,
)
from llm_research_os.blocks.schema import canonical_schema as canonical_block_schema
from llm_research_os.blocks.schema import schema_matches as block_schema_matches
from llm_research_os.blocks.schema import write_schema as write_block_schema
from llm_research_os.canonical import content_digest
from llm_research_os.execution import PlanningInputError, TrustedKernel
from llm_research_os.execution.models import (
    DryRunReport,
    DryRunStatus,
    ExecutionPlan,
    PlannedApproval,
    PlannedGraph,
    PlannedLoop,
    PlannedTask,
)
from llm_research_os.execution.schema import canonical_schema as canonical_dry_run_schema
from llm_research_os.execution.schema import schema_matches as dry_run_schema_matches
from llm_research_os.execution.schema import write_schema as write_dry_run_schema
from llm_research_os.problem import ProblemDetail, ProblemReport
from llm_research_os.problem_schema import canonical_schema as canonical_problem_schema
from llm_research_os.problem_schema import schema_matches as problem_schema_matches
from llm_research_os.problem_schema import write_schema as write_problem_schema
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import SpecLoadError, load_spec
from llm_research_os.spec.schema import canonical_schema as canonical_research_schema
from llm_research_os.spec.schema import schema_matches as research_schema_matches
from llm_research_os.spec.schema import write_schema as write_research_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="researchos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a ResearchSpec document")
    validate.add_argument("document", type=Path)

    schema = subparsers.add_parser("schema", help="print, write, or check a JSON Schema")
    schema.add_argument(
        "--contract",
        choices=(
            "research-spec",
            "block-manifest",
            "block-command-report",
            "dry-run-report",
            "problem-report",
        ),
        default="research-spec",
    )
    schema_group = schema.add_mutually_exclusive_group()
    schema_group.add_argument("--output", type=Path)
    schema_group.add_argument("--check", type=Path)

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

    blocks = subparsers.add_parser("blocks", help="inspect inert BlockManifest registrations")
    block_commands = blocks.add_subparsers(dest="blocks_command", required=True)
    blocks_list = block_commands.add_parser("list", help="list exact registered block versions")
    _add_registry_arguments(blocks_list)
    blocks_show = block_commands.add_parser("show", help="show one exact block registration")
    blocks_show.add_argument("block_id", help="exact block ID")
    blocks_show.add_argument("--version", required=True, help="exact semantic version")
    _add_registry_arguments(blocks_show)
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
    return parser


def _add_registry_arguments(parser: argparse.ArgumentParser) -> None:
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.document)
    if args.command == "schema":
        return _schema(args.output, args.check, args.contract)
    if args.command == "diff":
        return _diff(args.old, args.new)
    if args.command == "dry-run":
        return _dry_run(args.document, args.workflow, args.registry, args.format)
    if args.command == "blocks":
        return _blocks(args)
    raise AssertionError(f"unhandled command: {args.command}")


def _validate(document: Path) -> int:
    try:
        spec = load_spec(document)
    except (SpecLoadError, ValidationError) as exc:
        _print_problem(_problem_report(exc), "json")
        return 2
    print(
        json.dumps(
            {
                "valid": True,
                "projectId": spec.metadata.id,
                "revision": spec.metadata.revision,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _schema(output: Path | None, check: Path | None, contract: str) -> int:
    canonical: Callable[[], str]
    matches: Callable[[str | Path], bool]
    write: Callable[[str | Path], None]
    if contract == "research-spec":
        canonical = canonical_research_schema
        matches = research_schema_matches
        write = write_research_schema
    elif contract == "block-manifest":
        canonical = canonical_block_schema
        matches = block_schema_matches
        write = write_block_schema
    elif contract == "block-command-report":
        canonical = canonical_block_report_schema
        matches = block_report_schema_matches
        write = write_block_report_schema
    elif contract == "dry-run-report":
        canonical = canonical_dry_run_schema
        matches = dry_run_schema_matches
        write = write_dry_run_schema
    else:
        canonical = canonical_problem_schema
        matches = problem_schema_matches
        write = write_problem_schema
    if check is not None:
        if matches(check):
            print(f"schema is current: {check}")
            return 0
        print(f"schema differs from generated contract: {check}", file=sys.stderr)
        return 1
    if output is not None:
        write(output)
        print(f"wrote schema: {output}")
        return 0
    print(canonical(), end="")
    return 0


def _diff(old_path: Path, new_path: Path) -> int:
    try:
        old = load_spec(old_path)
        new = load_spec(new_path)
        changes = semantic_diff(old, new)
    except (SpecLoadError, ValidationError, ValueError) as exc:
        _print_problem(_problem_report(exc), "json")
        return 2
    print(
        json.dumps(
            {
                "projectId": old.metadata.id,
                "fromRevision": old.metadata.revision,
                "toRevision": new.metadata.revision,
                "changes": [change.as_dict() for change in changes],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _dry_run(
    document: Path,
    workflow_id: str | None,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        spec = load_spec(document)
        registry = build_registry(registry_paths)
        report = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
    except (
        ManifestLoadError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        OSError,
    ) as exc:
        _print_error(exc, output_format)
        return 2
    _print_dry_run(report, output_format)
    return 0 if report.status is DryRunStatus.READY else 1


def _blocks(args: argparse.Namespace) -> int:
    if args.blocks_command == "validate":
        try:
            manifest = load_manifest(args.manifest)
        except (ManifestLoadError, SpecLoadError, ValidationError) as exc:
            _print_error(exc, args.format)
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
        _print_error(exc, args.format)
        return 2

    blocks = registry.blocks()
    if args.blocks_command == "show":
        try:
            blocks = (registry.resolve(args.block_id, args.version),)
        except UnknownBlockError as exc:
            _print_error(exc, args.format)
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


def _print_dry_run(report: DryRunReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"dry-run {report.status.value}: {report.project.id}@revision-{report.project.revision}")
    if report.workflow_id is not None:
        print(f"workflow: {report.workflow_id}")
    if report.digests.plan is not None:
        print(f"plan: {report.digests.plan}")
    node_label = "planned nodes" if report.summary.basis == "planned" else "source nodes"
    if report.summary.truncated:
        node_label += " (truncated at planner limit)"
    print(
        f"{node_label}: "
        f"{report.summary.task_count} task(s), "
        f"{report.summary.approval_count} approval(s), "
        f"{report.summary.loop_count} loop(s)"
    )
    print("side effects: 0 blocks, 0 network requests, 0 writes, 0 paid actions")
    for diagnostic in report.diagnostics:
        print(
            f"{diagnostic.severity.value}: {diagnostic.code} at "
            f"{_safe_text(diagnostic.path)}: {_safe_text(diagnostic.message)}"
        )
    if report.plan is not None:
        _print_plan(report.plan)


def _print_plan(plan: ExecutionPlan) -> None:
    print("resources:")
    if not plan.resources:
        print("  (none)")
    for resource in plan.resources:
        provider = _safe_text(resource.provider) if resource.provider is not None else "unspecified"
        model = _safe_text(resource.model) if resource.model is not None else "unspecified"
        bounds = []
        if resource.max_cost is not None:
            bounds.append(f"maxCost={resource.max_cost} {resource.currency}")
        if resource.max_wall_time_seconds is not None:
            bounds.append(f"maxWallTime={resource.max_wall_time_seconds}s")
        bounds_suffix = f", {', '.join(bounds)}" if bounds else ""
        print(
            f"  - {resource.id}: {resource.kind.value} x{resource.count}, "
            f"paid={str(resource.paid).lower()}, provider={provider}, model={model}{bounds_suffix}"
        )

    print("policy requirements:")
    if not plan.policy_requirements:
        print("  (none)")
    for requirement in plan.policy_requirements:
        print(f"  - {requirement.kind}: {requirement.subject} ({requirement.disposition})")
    print("graph:")
    _print_graph(plan.graph, indent="  ")


def _print_graph(graph: PlannedGraph, *, indent: str) -> None:
    for stage in graph.stages:
        print(f"{indent}stage {stage.index}:")
        for node in stage.nodes:
            path = "/" + "/".join(node.node_path)
            dependencies = ", ".join(node.depends_on) if node.depends_on else "none"
            if isinstance(node, PlannedTask):
                resources = ",".join(node.resource_refs) if node.resource_refs else "none"
                capabilities = (
                    ",".join(node.declared_capabilities) if node.declared_capabilities else "none"
                )
                permissions = (
                    ",".join(node.declared_permissions) if node.declared_permissions else "none"
                )
                print(
                    f"{indent}  - task {path}: {node.block.id}@{node.block.version}; "
                    f"dependsOn={dependencies}; resources={resources}; "
                    f"authorization={node.authorization}; execution={node.execution}; "
                    f"capabilities={capabilities}; permissions={permissions}; "
                    f"manifest={node.block.manifest_digest}; config={node.config_digest}"
                )
            elif isinstance(node, PlannedApproval):
                print(
                    f"{indent}  - approval {path}: role={_safe_text(node.required_role)}; "
                    f"dependsOn={dependencies}; disposition={node.disposition}; "
                    f"prompt={node.prompt_digest}"
                )
            elif isinstance(node, PlannedLoop):
                bounds = [f"maxIterations={node.max_iterations}"]
                if node.max_cost is not None:
                    bounds.append(f"maxCost={node.max_cost} {node.currency}")
                if node.max_wall_time_seconds is not None:
                    bounds.append(f"maxWallTime={node.max_wall_time_seconds}s")
                bounds.extend(
                    (
                        f"mayIncurCost={str(node.may_incur_cost).lower()}",
                        f"checkpoint={str(node.checkpoint).lower()}",
                    )
                )
                if node.until is not None:
                    bounds.append(
                        f"until={node.until.expression_digest}, "
                        f"evaluated={str(node.until.evaluated).lower()}"
                    )
                print(
                    f"{indent}  - loop {path}: {', '.join(bounds)}; "
                    f"dependsOn={dependencies}; execution={node.execution}"
                )
                _print_graph(node.body, indent=indent + "    ")
    if graph.edges:
        print(f"{indent}edges:")
    for edge in graph.edges:
        source = "/" + "/".join(edge.source_path)
        target = "/" + "/".join(edge.target_path)
        if edge.kind == "data":
            print(
                f"{indent}  - data {source}.{edge.source_port} -> "
                f"{target}.{edge.target_port} "
                f"({_safe_text(edge.source_value_type)} -> "
                f"{_safe_text(edge.target_value_type)})"
            )
        else:
            print(f"{indent}  - control {source} -> {target}")


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
            assert block.manifest is not None
            manifest = block.manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
            print("manifest:")
            print(
                json.dumps(manifest, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
            )


def _print_error(exc: Exception, output_format: str) -> None:
    _print_problem(_problem_report(exc), output_format)


def _print_problem(report: ProblemReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        print(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return
    for error in report.errors:
        display_path = error.path or "<root>"
        print(
            f"error: {_safe_text(error.type)} at {_safe_text(display_path)}: "
            f"{_safe_text(error.message)}",
            file=sys.stderr,
        )


def _safe_text(value: object) -> str:
    rendered = json.dumps(str(value), ensure_ascii=True)
    return rendered[1:-1]


def _problem_report(exc: Exception) -> ProblemReport:
    if isinstance(exc, ValidationError):
        errors = [
            ProblemDetail(
                path=_json_pointer(_source_location(error["loc"])),
                message=error["msg"],
                type=error["type"],
            )
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
    elif isinstance(exc, PlanningInputError):
        errors = [ProblemDetail(path=exc.path, message=str(exc), type=exc.code)]
    else:
        errors = [ProblemDetail(message=str(exc), type=type(exc).__name__)]
    return ProblemReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="ProblemReport",
        valid=False,
        errors=tuple(errors),
    )


def _source_location(parts: tuple[str | int, ...]) -> tuple[str, ...]:
    """Remove Pydantic discriminated-union labels absent from source documents."""

    workflow_node_tags = {"task", "approval", "loop"}
    cleaned: list[str | int] = []
    for index, part in enumerate(parts):
        is_workflow_branch_label = (
            isinstance(part, str)
            and part in workflow_node_tags
            and index >= 2
            and parts[index - 2] == "nodes"
            and isinstance(parts[index - 1], int)
        )
        if not is_workflow_branch_label:
            cleaned.append(part)
    return tuple(str(part) for part in cleaned)


def _json_pointer(parts: tuple[str, ...]) -> str:
    if not parts:
        return ""
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def entrypoint() -> NoReturn:
    raise SystemExit(main())
