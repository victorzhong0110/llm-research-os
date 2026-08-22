"""Pydantic authoring models for ResearchSpec v0alpha1.

The generated JSON Schema is the external, language-neutral contract. These
models intentionally type the research invariants while leaving backend-specific
configuration inside explicit ``config`` objects.
"""

from __future__ import annotations

import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    model_validator,
)


def _require_json_object(value: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain only finite JSON-compatible data") from exc
    return value


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
NonNegativeMoney = Annotated[Decimal, Field(ge=0)]
JsonObject = Annotated[dict[str, Any], AfterValidator(_require_json_object)]


class StrictModel(BaseModel):
    """Base model for protocol objects: unknown structural fields are errors."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RightsStatus(StrEnum):
    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class DataUse(StrEnum):
    RESEARCH_READ = "research-read"
    RETRIEVAL = "retrieval"
    TRAINING = "training"
    REDISTRIBUTION = "redistribution"


class EvidenceSourceType(StrEnum):
    PAPER = "paper"
    CODE = "code"
    NOTE = "note"
    DATASET = "dataset"
    WEB = "web"
    EXPERIMENT = "experiment"
    OTHER = "other"


class ResourceKind(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    TPU = "tpu"
    ASCEND = "ascend"
    REMOTE_SERVICE = "remote-service"
    OTHER = "other"


class ProjectMetadata(StrictModel):
    id: Identifier
    revision: PositiveInt
    title: NonEmptyText
    description: NonEmptyText | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class ResearchQuestion(StrictModel):
    id: Identifier
    question: NonEmptyText
    rationale: NonEmptyText | None = None
    tags: list[NonEmptyText] = Field(default_factory=list)


class Prediction(StrictModel):
    id: Identifier
    statement: NonEmptyText
    metric: Identifier | None = None
    expected_direction: Literal["increase", "decrease", "unchanged", "range", "unknown"] = Field(
        default="unknown", alias="expectedDirection"
    )


class Hypothesis(StrictModel):
    id: Identifier
    statement: NonEmptyText
    question_refs: list[Identifier] = Field(default_factory=list, alias="questionRefs")
    predictions: list[Prediction] = Field(default_factory=list)


class EvidenceRecord(StrictModel):
    id: Identifier
    source_uri: NonEmptyText = Field(alias="sourceUri")
    source_type: EvidenceSourceType = Field(alias="sourceType")
    title: NonEmptyText | None = None
    snapshot_uri: NonEmptyText | None = Field(default=None, alias="snapshotUri")
    content_digest: NonEmptyText | None = Field(default=None, alias="contentDigest")
    rights: RightsStatus = RightsStatus.UNKNOWN
    license: NonEmptyText | None = None
    claims: list[NonEmptyText] = Field(default_factory=list)


class DatasetSource(StrictModel):
    uri: NonEmptyText
    version: NonEmptyText | None = None
    digest: NonEmptyText | None = None
    rights: RightsStatus = RightsStatus.UNKNOWN
    license: NonEmptyText | None = None
    allowed_uses: list[DataUse] = Field(
        default_factory=lambda: [DataUse.RESEARCH_READ], alias="allowedUses"
    )

    @model_validator(mode="after")
    def unknown_rights_cannot_authorize_training(self) -> Self:
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ValueError("allowedUses entries must be unique")
        prohibited = {DataUse.TRAINING, DataUse.REDISTRIBUTION}
        if self.rights is RightsStatus.UNKNOWN and prohibited.intersection(self.allowed_uses):
            raise ValueError(
                "sources with unknown rights cannot authorize training or redistribution"
            )
        return self


class DatasetSpec(StrictModel):
    id: Identifier
    version: NonEmptyText
    sources: list[DatasetSource] = Field(min_length=1)
    transforms: list[Identifier] = Field(default_factory=list)
    splits: dict[str, NonEmptyText] = Field(default_factory=dict)


class ModelSpec(StrictModel):
    id: Identifier
    architecture: NonEmptyText
    source_uri: NonEmptyText | None = Field(default=None, alias="sourceUri")
    source_revision: NonEmptyText | None = Field(default=None, alias="sourceRevision")
    config: JsonObject = Field(default_factory=dict)


class MetricSpec(StrictModel):
    id: Identifier
    description: NonEmptyText | None = None
    direction: Literal["maximize", "minimize", "target", "informational"] = "informational"
    target: float | None = None


class EvaluationSpec(StrictModel):
    id: Identifier
    metrics: list[MetricSpec] = Field(min_length=1)
    dataset_refs: list[Identifier] = Field(default_factory=list, alias="datasetRefs")
    baseline_refs: list[Identifier] = Field(default_factory=list, alias="baselineRefs")
    stop_conditions: list[NonEmptyText] = Field(default_factory=list, alias="stopConditions")


class ResourceSpec(StrictModel):
    id: Identifier
    kind: ResourceKind
    count: PositiveInt = 1
    provider: NonEmptyText | None = None
    model: NonEmptyText | None = None
    paid: bool = False
    max_cost: NonNegativeMoney | None = Field(default=None, alias="maxCost")
    currency: CurrencyCode = "USD"
    max_wall_time_seconds: PositiveInt | None = Field(default=None, alias="maxWallTimeSeconds")

    @model_validator(mode="after")
    def paid_resources_are_bounded(self) -> Self:
        if self.paid and (self.max_cost is None or self.max_wall_time_seconds is None):
            raise ValueError("paid resources require maxCost and maxWallTimeSeconds")
        return self


class ConditionExpression(StrictModel):
    language: Literal["researchos.expr/v0alpha1"] = "researchos.expr/v0alpha1"
    expression: NonEmptyText


class WorkflowEdge(StrictModel):
    source: Identifier
    target: Identifier
    source_port: Identifier | None = Field(default=None, alias="sourcePort")
    target_port: Identifier | None = Field(default=None, alias="targetPort")


class TaskBlock(StrictModel):
    kind: Literal["task"] = "task"
    id: Identifier
    block_type: Identifier = Field(alias="blockType")
    config: JsonObject = Field(default_factory=dict)
    resource_refs: list[Identifier] = Field(default_factory=list, alias="resourceRefs")


class ApprovalBlock(StrictModel):
    kind: Literal["approval"] = "approval"
    id: Identifier
    prompt: NonEmptyText
    required_role: NonEmptyText = Field(default="researcher", alias="requiredRole")


class LoopBlock(StrictModel):
    kind: Literal["loop"] = "loop"
    id: Identifier
    body: WorkflowGraph
    max_iterations: PositiveInt = Field(alias="maxIterations")
    max_wall_time_seconds: PositiveInt | None = Field(default=None, alias="maxWallTimeSeconds")
    max_cost: NonNegativeMoney | None = Field(default=None, alias="maxCost")
    currency: CurrencyCode = "USD"
    may_incur_cost: bool = Field(default=False, alias="mayIncurCost")
    until: ConditionExpression | None = None
    checkpoint: bool = True

    @model_validator(mode="after")
    def declared_cost_is_bounded(self) -> Self:
        if self.may_incur_cost and (self.max_cost is None or self.max_wall_time_seconds is None):
            raise ValueError("a loop that may incur cost requires maxCost and maxWallTimeSeconds")
        return self


WorkflowNode = Annotated[TaskBlock | ApprovalBlock | LoopBlock, Field(discriminator="kind")]


class WorkflowGraph(StrictModel):
    nodes: list[WorkflowNode] = Field(min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow node ids must be unique within a graph")

        known = set(node_ids)
        edge_pairs: set[tuple[str, str, str | None, str | None]] = set()
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        indegree = dict.fromkeys(node_ids, 0)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(
                    f"workflow edge references unknown node: {edge.source!r} -> {edge.target!r}"
                )
            if edge.source == edge.target:
                raise ValueError("self edges are not allowed; use an explicit loop block")
            key = (edge.source, edge.target, edge.source_port, edge.target_port)
            if key in edge_pairs:
                raise ValueError("duplicate workflow edges are not allowed")
            edge_pairs.add(key)
            if edge.target not in adjacency[edge.source]:
                adjacency[edge.source].add(edge.target)
                indegree[edge.target] += 1

        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(node_ids):
            raise ValueError("workflow graph contains a cycle; use an explicit loop block")
        return self


class WorkflowSpec(StrictModel):
    id: Identifier
    graph: WorkflowGraph


class PolicySpec(StrictModel):
    paid_actions_require_approval: bool = Field(default=True, alias="paidActionsRequireApproval")
    destructive_actions_require_approval: bool = Field(
        default=True, alias="destructiveActionsRequireApproval"
    )
    preserve_ai_dissent: Literal[True] = Field(default=True, alias="preserveAiDissent")
    unknown_evidence_may_train: Literal[False] = Field(
        default=False, alias="unknownEvidenceMayTrain"
    )


class ResearchSpec(StrictModel):
    """Root object for the v0alpha1 research protocol."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ResearchProject"]
    metadata: ProjectMetadata
    questions: list[ResearchQuestion] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    datasets: list[DatasetSpec] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
    workflows: list[WorkflowSpec] = Field(default_factory=list)
    evaluations: list[EvaluationSpec] = Field(default_factory=list)
    resources: list[ResourceSpec] = Field(default_factory=list)
    policies: PolicySpec = Field(default_factory=PolicySpec)
    extensions: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references_and_global_ids(self) -> Self:
        ids = [
            *(str(item.id) for item in self.questions),
            *(str(item.id) for item in self.hypotheses),
            *(str(item.id) for item in self.evidence),
            *(str(item.id) for item in self.datasets),
            *(str(item.id) for item in self.models),
            *(str(item.id) for item in self.workflows),
            *(str(item.id) for item in self.evaluations),
            *(str(item.id) for item in self.resources),
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("top-level entity ids must be globally unique")

        question_ids = {str(item.id) for item in self.questions}
        for hypothesis in self.hypotheses:
            unknown = set(hypothesis.question_refs).difference(question_ids)
            if unknown:
                raise ValueError(
                    f"hypothesis {hypothesis.id!r} references unknown questions: {sorted(unknown)}"
                )

        dataset_ids = {str(item.id) for item in self.datasets}
        for evaluation in self.evaluations:
            unknown = set(evaluation.dataset_refs).difference(dataset_ids)
            if unknown:
                raise ValueError(
                    f"evaluation {evaluation.id!r} references unknown datasets: {sorted(unknown)}"
                )

        resources = {str(item.id): item for item in self.resources}
        risky_resources = {
            resource_id
            for resource_id, resource in resources.items()
            if resource.paid
            or resource.kind in {ResourceKind.GPU, ResourceKind.TPU, ResourceKind.ASCEND}
        }
        for workflow in self.workflows:
            self._validate_graph_resources(workflow.graph, resources, risky_resources)
        return self

    @classmethod
    def _validate_graph_resources(
        cls,
        graph: WorkflowGraph,
        resources: dict[str, ResourceSpec],
        risky_resources: set[str],
    ) -> set[str]:
        used: set[str] = set()
        for node in graph.nodes:
            if isinstance(node, TaskBlock):
                unknown = set(node.resource_refs).difference(resources)
                if unknown:
                    raise ValueError(
                        f"task {node.id!r} references unknown resources: {sorted(unknown)}"
                    )
                used.update(node.resource_refs)
            elif isinstance(node, LoopBlock):
                loop_resources = cls._validate_graph_resources(
                    node.body, resources, risky_resources
                )
                if (node.may_incur_cost or loop_resources.intersection(risky_resources)) and (
                    node.max_cost is None or node.max_wall_time_seconds is None
                ):
                    raise ValueError(
                        f"loop {node.id!r} uses paid/accelerated capability and requires "
                        "maxCost and maxWallTimeSeconds"
                    )
                used.update(loop_resources)
        return used


LoopBlock.model_rebuild()
WorkflowGraph.model_rebuild()
ResearchSpec.model_rebuild()
