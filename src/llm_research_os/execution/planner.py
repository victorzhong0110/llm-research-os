"""Pure deterministic compiler from ResearchSpec to an inert execution plan."""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_research_os.blocks.registry import (
    BlockConfigError,
    BlockRegistry,
    RegisteredBlock,
    UnknownBlockError,
)
from llm_research_os.canonical import content_digest
from llm_research_os.execution.models import (
    ExecutionPlan,
    PlannedApproval,
    PlannedCondition,
    PlannedEdge,
    PlannedGraph,
    PlannedLoop,
    PlannedResource,
    PlannedTask,
    PlanStage,
    PolicyRequirement,
    ProjectRef,
    ResolvedBlock,
)
from llm_research_os.spec.models import (
    ApprovalBlock,
    ResearchSpec,
    ResourceSpec,
    TaskBlock,
    WorkflowGraph,
    WorkflowNode,
    WorkflowSpec,
)

type NodePath = tuple[str, ...]
HARD_MAX_NODES = 10_000
HARD_MAX_LOOP_DEPTH = 16


class PlanningError(ValueError):
    """Base class for stable, user-facing planning diagnostics."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class PlanningInputError(PlanningError):
    """Raised when a planning request cannot select a valid input."""


class PlanningBlocked(PlanningError):
    """Raised when a valid ResearchSpec cannot produce a complete static plan."""


@dataclass(frozen=True, slots=True)
class PlannerLimits:
    max_nodes: int = HARD_MAX_NODES
    max_loop_depth: int = HARD_MAX_LOOP_DEPTH

    def __post_init__(self) -> None:
        if type(self.max_nodes) is not int or not 1 <= self.max_nodes <= HARD_MAX_NODES:
            raise ValueError(f"max_nodes must be an integer from 1 to {HARD_MAX_NODES}")
        if (
            type(self.max_loop_depth) is not int
            or not 0 <= self.max_loop_depth <= HARD_MAX_LOOP_DEPTH
        ):
            raise ValueError(f"max_loop_depth must be an integer from 0 to {HARD_MAX_LOOP_DEPTH}")


@dataclass(slots=True)
class _PlannerState:
    limits: PlannerLimits
    paid_actions_require_approval: bool
    node_count: int = 0
    task_count: int = 0
    approval_count: int = 0
    loop_count: int = 0
    stage_count: int = 0
    used_resource_ids: set[str] = field(default_factory=set)
    requirements: dict[str, PolicyRequirement] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompiledPlan:
    plan: ExecutionPlan
    task_count: int
    approval_count: int
    loop_count: int
    stage_count: int


def compile_plan(
    spec: ResearchSpec,
    registry: BlockRegistry,
    *,
    workflow_id: str | None = None,
    limits: PlannerLimits | None = None,
) -> CompiledPlan:
    """Compile a complete plan without invoking any runtime capability."""

    if not registry.sealed:
        raise PlanningInputError(
            "registry-not-sealed",
            "/registry",
            "planning requires a sealed registry snapshot",
        )

    workflow = _select_workflow(spec, workflow_id)
    selected_limits = limits or PlannerLimits()
    if selected_limits.max_nodes < 1 or selected_limits.max_loop_depth < 0:
        raise PlanningInputError(
            "invalid-planner-limits",
            "/limits",
            "planner limits must allow at least one node and a non-negative loop depth",
        )

    state = _PlannerState(
        selected_limits,
        paid_actions_require_approval=spec.policies.paid_actions_require_approval,
    )
    resource_by_id = {str(resource.id): resource for resource in spec.resources}
    graph = _plan_graph(
        workflow.graph,
        base_path=("workflow", str(workflow.id)),
        depth=0,
        registry=registry,
        resources=resource_by_id,
        state=state,
    )

    for resource_id in sorted(state.used_resource_ids):
        resource = resource_by_id[resource_id]
        if resource.paid and spec.policies.paid_actions_require_approval:
            requirement_id = f"paid-resource:{resource_id}"
            state.requirements[requirement_id] = PolicyRequirement(
                id=requirement_id,
                kind="paid-resource-approval",
                subject=resource_id,
            )

    resources = tuple(
        _planned_resource(resource_by_id[resource_id])
        for resource_id in sorted(state.used_resource_ids)
    )
    payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    plan = ExecutionPlan(
        plannerVersion="researchos.planner/v0alpha1",
        project=ProjectRef(id=spec.metadata.id, revision=spec.metadata.revision),
        workflowId=workflow.id,
        specDigest=content_digest(payload),
        registryDigest=registry.digest(),
        resources=resources,
        policyRequirements=tuple(state.requirements[key] for key in sorted(state.requirements)),
        graph=graph,
    )
    return CompiledPlan(
        plan=plan,
        task_count=state.task_count,
        approval_count=state.approval_count,
        loop_count=state.loop_count,
        stage_count=state.stage_count,
    )


def _select_workflow(spec: ResearchSpec, workflow_id: str | None) -> WorkflowSpec:
    if workflow_id is not None:
        for workflow in spec.workflows:
            if workflow.id == workflow_id:
                return workflow
        raise PlanningInputError(
            "unknown-workflow",
            "/workflowId",
            f"workflow {workflow_id!r} does not exist",
        )
    if not spec.workflows:
        raise PlanningInputError(
            "missing-workflow",
            "/workflows",
            "ResearchSpec contains no workflow to plan",
        )
    if len(spec.workflows) > 1:
        candidates = ", ".join(sorted(str(workflow.id) for workflow in spec.workflows))
        raise PlanningInputError(
            "workflow-selection-required",
            "/workflows",
            f"select one workflow explicitly: {candidates}",
        )
    return spec.workflows[0]


def _plan_graph(
    graph: WorkflowGraph,
    *,
    base_path: NodePath,
    depth: int,
    registry: BlockRegistry,
    resources: dict[str, ResourceSpec],
    state: _PlannerState,
) -> PlannedGraph:
    if depth > state.limits.max_loop_depth:
        raise PlanningBlocked(
            "loop-depth-limit",
            _pointer(base_path),
            f"workflow exceeds the M0 loop-depth limit of {state.limits.max_loop_depth}",
        )
    state.node_count += len(graph.nodes)
    if state.node_count > state.limits.max_nodes:
        raise PlanningBlocked(
            "node-limit",
            _pointer(base_path),
            f"workflow exceeds the M0 node limit of {state.limits.max_nodes}",
        )

    nodes = {str(node.id): node for node in graph.nodes}
    resolved: dict[str, RegisteredBlock] = {}
    for node_id in sorted(nodes):
        node = nodes[node_id]
        if not isinstance(node, TaskBlock):
            continue
        node_path = (*base_path, node_id)
        try:
            block = registry.resolve(str(node.block_type), str(node.block_version))
            registry.validate_config(block, node.config)
        except UnknownBlockError as exc:
            raise PlanningBlocked(
                "unknown-block",
                _pointer((*node_path, "blockType")),
                str(exc),
            ) from exc
        except BlockConfigError as exc:
            raise PlanningBlocked(
                "invalid-block-config",
                _pointer((*node_path, "config")),
                str(exc),
            ) from exc
        resolved[node_id] = block

    planned_edges = _validate_data_edges(graph, nodes, resolved, base_path)
    stages, dependencies = _topological_stages(graph)
    planned_stages: list[PlanStage] = []
    for index, stage_ids in enumerate(stages):
        planned_nodes = tuple(
            _plan_node(
                nodes[node_id],
                dependencies=dependencies[node_id],
                base_path=base_path,
                depth=depth,
                registry=registry,
                resources=resources,
                resolved=resolved,
                state=state,
            )
            for node_id in stage_ids
        )
        planned_stages.append(PlanStage(index=index, nodes=planned_nodes))
    state.stage_count += len(planned_stages)
    return PlannedGraph(stages=tuple(planned_stages), edges=planned_edges)


def _plan_node(
    node: WorkflowNode,
    *,
    dependencies: tuple[str, ...],
    base_path: NodePath,
    depth: int,
    registry: BlockRegistry,
    resources: dict[str, ResourceSpec],
    resolved: dict[str, RegisteredBlock],
    state: _PlannerState,
) -> PlannedTask | PlannedApproval | PlannedLoop:
    node_path = (*base_path, str(node.id))
    dependency_paths = tuple(_pointer((*base_path, dependency)) for dependency in dependencies)
    if isinstance(node, TaskBlock):
        state.task_count += 1
        state.used_resource_ids.update(str(item) for item in node.resource_refs)
        block = resolved[str(node.id)]
        return PlannedTask(
            nodePath=node_path,
            dependsOn=dependency_paths,
            block=ResolvedBlock(
                id=block.manifest.metadata.id,
                version=block.manifest.metadata.version,
                manifestDigest=block.digest,
                runtimeType=block.manifest.runtime.type,
            ),
            configDigest=content_digest(node.config),
            resourceRefs=tuple(sorted(str(item) for item in node.resource_refs)),
            declaredCapabilities=tuple(sorted(block.manifest.capabilities)),
            declaredPermissions=tuple(sorted(block.manifest.permissions)),
        )
    if isinstance(node, ApprovalBlock):
        state.approval_count += 1
        requirement_id = f"approval:{_pointer(node_path)}"
        state.requirements[requirement_id] = PolicyRequirement(
            id=requirement_id,
            kind="human-approval",
            subject=_pointer(node_path),
        )
        return PlannedApproval(
            nodePath=node_path,
            dependsOn=dependency_paths,
            requiredRole=node.required_role,
            promptDigest=content_digest(node.prompt),
        )

    state.loop_count += 1
    if node.may_incur_cost and state.paid_actions_require_approval:
        requirement_id = f"paid-loop:{_pointer(node_path)}"
        state.requirements[requirement_id] = PolicyRequirement(
            id=requirement_id,
            kind="paid-loop-approval",
            subject=_pointer(node_path),
        )
    condition = (
        PlannedCondition(
            language=node.until.language,
            expressionDigest=content_digest(node.until.expression),
        )
        if node.until is not None
        else None
    )
    body = _plan_graph(
        node.body,
        base_path=(*node_path, "body"),
        depth=depth + 1,
        registry=registry,
        resources=resources,
        state=state,
    )
    return PlannedLoop(
        nodePath=node_path,
        dependsOn=dependency_paths,
        maxIterations=node.max_iterations,
        maxWallTimeSeconds=node.max_wall_time_seconds,
        maxCost=node.max_cost,
        currency=node.currency,
        mayIncurCost=node.may_incur_cost,
        checkpoint=node.checkpoint,
        until=condition,
        body=body,
    )


def _validate_data_edges(
    graph: WorkflowGraph,
    nodes: dict[str, WorkflowNode],
    resolved: dict[str, RegisteredBlock],
    base_path: NodePath,
) -> tuple[PlannedEdge, ...]:
    connected_inputs: set[tuple[str, str]] = set()
    planned_edges: list[PlannedEdge] = []
    for index, edge in enumerate(graph.edges):
        if edge.source_port is None:
            planned_edges.append(
                PlannedEdge(
                    kind="control",
                    sourcePath=(*base_path, str(edge.source)),
                    targetPath=(*base_path, str(edge.target)),
                )
            )
            continue
        edge_path = (*base_path, "edges", str(index))
        source = nodes[str(edge.source)]
        target = nodes[str(edge.target)]
        if not isinstance(source, TaskBlock) or not isinstance(target, TaskBlock):
            raise PlanningBlocked(
                "data-edge-requires-tasks",
                _pointer(edge_path),
                "data ports may only connect task blocks in M0",
            )
        source_block = resolved[str(source.id)].manifest
        target_block = resolved[str(target.id)].manifest
        outputs = {str(port.id): port for port in source_block.outputs}
        inputs = {str(port.id): port for port in target_block.inputs}
        source_port = str(edge.source_port)
        target_port = str(edge.target_port)
        if source_port not in outputs:
            raise PlanningBlocked(
                "unknown-source-port",
                _pointer((*edge_path, "sourcePort")),
                f"block {source.block_type}@{source.block_version} has no output {source_port!r}",
            )
        if target_port not in inputs:
            raise PlanningBlocked(
                "unknown-target-port",
                _pointer((*edge_path, "targetPort")),
                f"block {target.block_type}@{target.block_version} has no input {target_port!r}",
            )
        target_key = (str(target.id), target_port)
        if target_key in connected_inputs:
            raise PlanningBlocked(
                "multiple-input-bindings",
                _pointer((*edge_path, "targetPort")),
                f"input {target_port!r} on task {target.id!r} has multiple bindings",
            )
        connected_inputs.add(target_key)
        source_type = str(outputs[source_port].value_type)
        target_type = str(inputs[target_port].value_type)
        compatible = (
            source_type == target_type
            or source_type == "researchos.any"
            or target_type == "researchos.any"
        )
        if not compatible:
            raise PlanningBlocked(
                "incompatible-port-types",
                _pointer(edge_path),
                f"port types are incompatible: {source_type!r} -> {target_type!r}",
            )
        planned_edges.append(
            PlannedEdge(
                kind="data",
                sourcePath=(*base_path, str(edge.source)),
                targetPath=(*base_path, str(edge.target)),
                sourcePort=source_port,
                targetPort=target_port,
                sourceValueType=source_type,
                targetValueType=target_type,
            )
        )

    for node_id in sorted(resolved):
        for port in resolved[node_id].manifest.inputs:
            if port.required and (node_id, str(port.id)) not in connected_inputs:
                raise PlanningBlocked(
                    "missing-required-input",
                    _pointer((*base_path, node_id)),
                    f"required input {port.id!r} is not connected",
                )
    return tuple(
        sorted(
            planned_edges,
            key=lambda item: (
                item.source_path,
                item.target_path,
                item.source_port or "",
                item.target_port or "",
            ),
        )
    )


def _topological_stages(
    graph: WorkflowGraph,
) -> tuple[tuple[tuple[str, ...], ...], dict[str, tuple[str, ...]]]:
    node_ids = sorted(str(node.id) for node in graph.nodes)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = dict.fromkeys(node_ids, 0)
    for edge in graph.edges:
        source = str(edge.source)
        target = str(edge.target)
        if target not in adjacency[source]:
            adjacency[source].add(target)
            dependencies[target].add(source)
            indegree[target] += 1

    ready = tuple(node_id for node_id in node_ids if indegree[node_id] == 0)
    stages: list[tuple[str, ...]] = []
    while ready:
        stages.append(ready)
        next_ready: set[str] = set()
        for node_id in ready:
            for target in sorted(adjacency[node_id]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    next_ready.add(target)
        ready = tuple(sorted(next_ready))
    return tuple(stages), {
        node_id: tuple(sorted(values)) for node_id, values in dependencies.items()
    }


def _planned_resource(resource: ResourceSpec) -> PlannedResource:
    return PlannedResource(
        id=resource.id,
        kind=resource.kind,
        count=resource.count,
        provider=resource.provider,
        model=resource.model,
        paid=resource.paid,
        maxCost=resource.max_cost,
        currency=resource.currency,
        maxWallTimeSeconds=resource.max_wall_time_seconds,
    )


def _pointer(parts: NodePath) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)
