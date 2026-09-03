"""ResearchSpec validate, diff, dry-run, and schema commands."""

from __future__ import annotations

import argparse
import json

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.contracts import schema_command
from llm_research_os.cli.output import print_error, print_problem, problem_report, safe_text
from llm_research_os.execution import TrustedKernel
from llm_research_os.execution.models import (
    DryRunReport,
    DryRunStatus,
    ExecutionPlan,
    PlannedApproval,
    PlannedGraph,
    PlannedLoop,
    PlannedTask,
)
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import SpecLoadError, load_spec


def run_validate(args: argparse.Namespace) -> int:
    try:
        spec = load_spec(args.document)
    except (SpecLoadError, ValidationError) as exc:
        print_problem(problem_report(exc), "json")
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


def run_schema(args: argparse.Namespace) -> int:
    return schema_command(
        output=args.output,
        check=args.check,
        check_all=args.check_all,
        contract=args.contract,
    )


def run_diff(args: argparse.Namespace) -> int:
    try:
        old = load_spec(args.old)
        new = load_spec(args.new)
        changes = semantic_diff(old, new)
    except (SpecLoadError, ValidationError, ValueError) as exc:
        print_problem(problem_report(exc), "json")
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


def run_dry_run(args: argparse.Namespace) -> int:
    try:
        spec = load_spec(args.document)
        registry = build_registry(args.registry)
        report = TrustedKernel(registry).dry_run(spec, workflow_id=args.workflow)
    except (
        ManifestLoadError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        OSError,
    ) as exc:
        print_error(exc, args.format)
        return 2
    _print_dry_run(report, args.format)
    return 0 if report.status is DryRunStatus.READY else 1


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
            f"{safe_text(diagnostic.path)}: {safe_text(diagnostic.message)}"
        )
    if report.plan is not None:
        _print_plan(report.plan)


def _print_plan(plan: ExecutionPlan) -> None:
    print("resources:")
    if not plan.resources:
        print("  (none)")
    for resource in plan.resources:
        provider = safe_text(resource.provider) if resource.provider is not None else "unspecified"
        model = safe_text(resource.model) if resource.model is not None else "unspecified"
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
                    f"{indent}  - approval {path}: role={safe_text(node.required_role)}; "
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
                f"({safe_text(edge.source_value_type)} -> "
                f"{safe_text(edge.target_value_type)})"
            )
        else:
            print(f"{indent}  - control {source} -> {target}")
