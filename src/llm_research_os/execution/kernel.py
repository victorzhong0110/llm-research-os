"""Minimal trusted M0 kernel boundary for side-effect-free planning."""

from __future__ import annotations

from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.canonical import content_digest
from llm_research_os.execution.models import (
    DiagnosticSeverity,
    DryRunReport,
    DryRunStatus,
    PlanDiagnostic,
    PlanDigests,
    PlanSummary,
    ProjectRef,
)
from llm_research_os.execution.planner import (
    PlannerLimits,
    PlanningBlocked,
    compile_plan,
)
from llm_research_os.spec.models import (
    ApprovalBlock,
    LoopBlock,
    ResearchSpec,
    TaskBlock,
    WorkflowGraph,
    WorkflowNode,
)


class TrustedKernel:
    """Coordinate immutable snapshots and planning without executing block code."""

    def __init__(self, registry: BlockRegistry, *, limits: PlannerLimits | None = None) -> None:
        self._registry = registry
        self._limits = limits or PlannerLimits()

    def dry_run(self, spec: ResearchSpec, *, workflow_id: str | None = None) -> DryRunReport:
        input_payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
        snapshot = ResearchSpec.model_validate(input_payload)
        snapshot_payload = snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
        project = ProjectRef(id=snapshot.metadata.id, revision=snapshot.metadata.revision)
        spec_digest = content_digest(snapshot_payload)
        registry_digest = self._registry.digest()
        selected_workflow_id = workflow_id
        selected_graph: WorkflowGraph | None = None
        if workflow_id is None and len(snapshot.workflows) == 1:
            selected_workflow_id = str(snapshot.workflows[0].id)
            selected_graph = snapshot.workflows[0].graph
        elif workflow_id is not None:
            selected_graph = next(
                (
                    workflow.graph
                    for workflow in snapshot.workflows
                    if str(workflow.id) == workflow_id
                ),
                None,
            )
        try:
            compiled = compile_plan(
                snapshot,
                self._registry,
                workflow_id=workflow_id,
                limits=self._limits,
            )
        except PlanningBlocked as exc:
            if selected_workflow_id is None or selected_graph is None:
                # compile_plan only raises PlanningBlocked after resolving the workflow.
                raise RuntimeError("PlanningBlocked without a resolved workflow") from exc
            task_count, approval_count, loop_count, truncated = _source_counts(
                selected_graph,
                max_nodes=self._limits.max_nodes,
            )
            return DryRunReport(
                apiVersion="researchos.dev/v0alpha1",
                kind="DryRunReport",
                status=DryRunStatus.BLOCKED,
                project=project,
                workflowId=selected_workflow_id,
                digests=PlanDigests(spec=spec_digest, registry=registry_digest),
                summary=PlanSummary(
                    basis="source",
                    truncated=truncated,
                    taskCount=task_count,
                    approvalCount=approval_count,
                    loopCount=loop_count,
                    stageCount=0,
                ),
                diagnostics=(
                    PlanDiagnostic(
                        code=exc.code,
                        severity=DiagnosticSeverity.ERROR,
                        path=exc.path,
                        message=str(exc),
                    ),
                ),
            )

        plan_payload = compiled.plan.model_dump(mode="json", by_alias=True, exclude_none=True)
        # The exact source identity is reported separately as specDigest. Excluding it here
        # keeps semantically irrelevant YAML list reordering from changing the compiled plan.
        plan_payload.pop("specDigest")
        plan_digest = content_digest(plan_payload)
        return DryRunReport(
            apiVersion="researchos.dev/v0alpha1",
            kind="DryRunReport",
            status=DryRunStatus.READY,
            project=project,
            workflowId=compiled.plan.workflow_id,
            digests=PlanDigests(
                spec=compiled.plan.spec_digest,
                registry=compiled.plan.registry_digest,
                plan=plan_digest,
            ),
            summary=PlanSummary(
                basis="planned",
                taskCount=compiled.task_count,
                approvalCount=compiled.approval_count,
                loopCount=compiled.loop_count,
                stageCount=compiled.stage_count,
            ),
            plan=compiled.plan,
        )


def _source_counts(
    graph: WorkflowGraph,
    *,
    max_nodes: int,
) -> tuple[int, int, int, bool]:
    task_count = 0
    approval_count = 0
    loop_count = 0
    total = 0
    stack: list[tuple[list[WorkflowNode], int]] = [(graph.nodes, 0)]
    while stack:
        nodes, index = stack.pop()
        if index >= len(nodes):
            continue
        if total >= max_nodes:
            return task_count, approval_count, loop_count, True
        stack.append((nodes, index + 1))
        node = nodes[index]
        total += 1
        if isinstance(node, TaskBlock):
            task_count += 1
        elif isinstance(node, ApprovalBlock):
            approval_count += 1
        elif isinstance(node, LoopBlock):
            loop_count += 1
            stack.append((node.body.nodes, 0))
    return task_count, approval_count, loop_count, False
