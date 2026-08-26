"""Immutable output models for the deterministic M0 planning kernel."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from llm_research_os.blocks.models import RuntimeType
from llm_research_os.canonical import ContentDigest, content_digest
from llm_research_os.spec.models import (
    CurrencyCode,
    Identifier,
    NonEmptyText,
    ResourceKind,
    SemanticVersion,
    StrictModel,
)

NonNegativeInt = Annotated[int, Field(ge=0)]


class FrozenPlanModel(StrictModel):
    """Base class for plan snapshots returned to callers."""

    model_config = ConfigDict(frozen=True)


class DryRunStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ProjectRef(FrozenPlanModel):
    id: Identifier
    revision: int = Field(ge=1)


class PlanDigests(FrozenPlanModel):
    spec: ContentDigest
    registry: ContentDigest
    plan: ContentDigest | None = None


class PlanDiagnostic(FrozenPlanModel):
    code: Identifier
    severity: DiagnosticSeverity
    path: NonEmptyText
    message: NonEmptyText


class SideEffectSummary(FrozenPlanModel):
    blocks_executed: Literal[0] = Field(default=0, alias="blocksExecuted")
    network_requests: Literal[0] = Field(default=0, alias="networkRequests")
    persistent_writes: Literal[0] = Field(default=0, alias="persistentWrites")
    paid_actions: Literal[0] = Field(default=0, alias="paidActions")


class PlanSummary(FrozenPlanModel):
    basis: Literal["planned", "source"]
    truncated: bool = False
    task_count: NonNegativeInt = Field(alias="taskCount")
    approval_count: NonNegativeInt = Field(alias="approvalCount")
    loop_count: NonNegativeInt = Field(alias="loopCount")
    stage_count: NonNegativeInt = Field(alias="stageCount")


class ResolvedBlock(FrozenPlanModel):
    id: Identifier
    version: SemanticVersion
    manifest_digest: ContentDigest = Field(alias="manifestDigest")
    runtime_type: RuntimeType = Field(alias="runtimeType")


class PlannedResource(FrozenPlanModel):
    id: Identifier
    kind: ResourceKind
    count: int = Field(ge=1)
    provider: NonEmptyText | None = None
    model: NonEmptyText | None = None
    paid: bool
    max_cost: Decimal | None = Field(default=None, alias="maxCost")
    currency: CurrencyCode
    max_wall_time_seconds: int | None = Field(default=None, ge=1, alias="maxWallTimeSeconds")


class PlannedCondition(FrozenPlanModel):
    language: Literal["researchos.expr/v0alpha1"]
    expression_digest: ContentDigest = Field(alias="expressionDigest")
    evaluated: Literal[False] = False


class PlannedTask(FrozenPlanModel):
    kind: Literal["task"] = "task"
    node_path: tuple[Identifier, ...] = Field(min_length=1, alias="nodePath")
    depends_on: tuple[NonEmptyText, ...] = Field(default_factory=tuple, alias="dependsOn")
    block: ResolvedBlock
    config_digest: ContentDigest = Field(alias="configDigest")
    resource_refs: tuple[Identifier, ...] = Field(default_factory=tuple, alias="resourceRefs")
    declared_capabilities: tuple[Identifier, ...] = Field(
        default_factory=tuple, alias="declaredCapabilities"
    )
    declared_permissions: tuple[Identifier, ...] = Field(
        default_factory=tuple, alias="declaredPermissions"
    )
    authorization: Literal["not-evaluated"] = "not-evaluated"
    execution: Literal["not-executed"] = "not-executed"


class PlannedApproval(FrozenPlanModel):
    kind: Literal["approval"] = "approval"
    node_path: tuple[Identifier, ...] = Field(min_length=1, alias="nodePath")
    depends_on: tuple[NonEmptyText, ...] = Field(default_factory=tuple, alias="dependsOn")
    required_role: NonEmptyText = Field(alias="requiredRole")
    prompt_digest: ContentDigest = Field(alias="promptDigest")
    disposition: Literal["would-pause"] = "would-pause"


class PlannedLoop(FrozenPlanModel):
    kind: Literal["loop"] = "loop"
    node_path: tuple[Identifier, ...] = Field(min_length=1, alias="nodePath")
    depends_on: tuple[NonEmptyText, ...] = Field(default_factory=tuple, alias="dependsOn")
    max_iterations: int = Field(ge=1, alias="maxIterations")
    max_wall_time_seconds: int | None = Field(default=None, ge=1, alias="maxWallTimeSeconds")
    max_cost: Decimal | None = Field(default=None, ge=0, alias="maxCost")
    currency: CurrencyCode
    may_incur_cost: bool = Field(alias="mayIncurCost")
    checkpoint: bool
    until: PlannedCondition | None = None
    body: PlannedGraph
    execution: Literal["not-executed"] = "not-executed"


PlanNode = Annotated[PlannedTask | PlannedApproval | PlannedLoop, Field(discriminator="kind")]


class PlanStage(FrozenPlanModel):
    index: NonNegativeInt
    nodes: tuple[PlanNode, ...] = Field(min_length=1)


class PlannedEdge(FrozenPlanModel):
    kind: Literal["control", "data"]
    source_path: tuple[Identifier, ...] = Field(min_length=1, alias="sourcePath")
    target_path: tuple[Identifier, ...] = Field(min_length=1, alias="targetPath")
    source_port: Identifier | None = Field(default=None, alias="sourcePort")
    target_port: Identifier | None = Field(default=None, alias="targetPort")
    source_value_type: NonEmptyText | None = Field(default=None, alias="sourceValueType")
    target_value_type: NonEmptyText | None = Field(default=None, alias="targetValueType")

    @model_validator(mode="after")
    def edge_shape_matches_kind(self) -> Self:
        data_fields = (
            self.source_port,
            self.target_port,
            self.source_value_type,
            self.target_value_type,
        )
        if self.kind == "data" and any(value is None for value in data_fields):
            raise ValueError("data edges require ports and value types")
        if self.kind == "control" and any(value is not None for value in data_fields):
            raise ValueError("control edges must not declare ports or value types")
        return self


class PlannedGraph(FrozenPlanModel):
    stages: tuple[PlanStage, ...] = Field(min_length=1)
    edges: tuple[PlannedEdge, ...] = Field(default_factory=tuple)


class PolicyRequirement(FrozenPlanModel):
    id: NonEmptyText
    kind: Identifier
    subject: NonEmptyText
    disposition: Literal["required-not-evaluated"] = Field(
        default="required-not-evaluated", alias="disposition"
    )


class ExecutionPlan(FrozenPlanModel):
    planner_version: Literal["researchos.planner/v0alpha1"] = Field(alias="plannerVersion")
    project: ProjectRef
    workflow_id: Identifier = Field(alias="workflowId")
    spec_digest: ContentDigest = Field(alias="specDigest")
    registry_digest: ContentDigest = Field(alias="registryDigest")
    resources: tuple[PlannedResource, ...] = Field(default_factory=tuple)
    policy_requirements: tuple[PolicyRequirement, ...] = Field(
        default_factory=tuple, alias="policyRequirements"
    )
    graph: PlannedGraph


class DryRunReport(FrozenPlanModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["DryRunReport"]
    status: DryRunStatus
    project: ProjectRef
    workflow_id: Identifier = Field(alias="workflowId")
    digests: PlanDigests
    summary: PlanSummary
    side_effects: SideEffectSummary = Field(default_factory=SideEffectSummary, alias="sideEffects")
    plan: ExecutionPlan | None = None
    diagnostics: tuple[PlanDiagnostic, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def status_and_plan_are_consistent(self) -> Self:
        error_diagnostics = tuple(
            item for item in self.diagnostics if item.severity is DiagnosticSeverity.ERROR
        )
        if self.status is DryRunStatus.BLOCKED:
            if self.plan is not None or self.digests.plan is not None:
                raise ValueError("blocked reports must not contain a plan or plan digest")
            if not error_diagnostics:
                raise ValueError("blocked reports require at least one error diagnostic")
            if self.summary.basis != "source":
                raise ValueError("blocked report summaries must be based on source nodes")
            if self.summary.stage_count != 0:
                raise ValueError("blocked report summaries must have zero planned stages")
            return self

        if self.plan is None or self.digests.plan is None:
            raise ValueError("ready reports require a plan and plan digest")
        if error_diagnostics:
            raise ValueError("ready reports must not contain error diagnostics")
        if self.summary.basis != "planned":
            raise ValueError("ready report summaries must be based on the compiled plan")
        if self.summary.truncated:
            raise ValueError("ready report summaries must not be truncated")
        actual_summary = _plan_counts(self.plan.graph)
        reported_summary = (
            self.summary.task_count,
            self.summary.approval_count,
            self.summary.loop_count,
            self.summary.stage_count,
        )
        if reported_summary != actual_summary:
            raise ValueError("ready report summary does not match the embedded plan")
        if self.project != self.plan.project or self.workflow_id != self.plan.workflow_id:
            raise ValueError("report identity must match the embedded plan")
        if (
            self.digests.spec != self.plan.spec_digest
            or self.digests.registry != self.plan.registry_digest
        ):
            raise ValueError("report digests must match the embedded plan")
        plan_payload = self.plan.model_dump(mode="json", by_alias=True, exclude_none=True)
        plan_payload.pop("specDigest")
        if self.digests.plan != content_digest(plan_payload):
            raise ValueError("plan digest does not match the embedded semantic plan")
        return self


def _plan_counts(graph: PlannedGraph) -> tuple[int, int, int, int]:
    task_count = 0
    approval_count = 0
    loop_count = 0
    stage_count = 0
    pending = [graph]
    while pending:
        current = pending.pop()
        stage_count += len(current.stages)
        for stage in current.stages:
            for node in stage.nodes:
                if isinstance(node, PlannedTask):
                    task_count += 1
                elif isinstance(node, PlannedApproval):
                    approval_count += 1
                elif isinstance(node, PlannedLoop):
                    loop_count += 1
                    pending.append(node.body)
    return task_count, approval_count, loop_count, stage_count


PlannedLoop.model_rebuild()
PlanStage.model_rebuild()
PlannedGraph.model_rebuild()
ExecutionPlan.model_rebuild()
DryRunReport.model_rebuild()
