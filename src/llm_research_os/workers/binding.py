"""Authorized host-python execution objects. Not kernel isolation (TM-043)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from llm_research_os.blocks.registry import BlockRegistry, RegistryError
from llm_research_os.canonical import content_digest
from llm_research_os.events.models import ActorKind
from llm_research_os.execution.authorization import PlanAuthorizationPolicy, authorize_plan
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    PlanAuthorizationEvaluatedPayload,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import PlanAuthorizationError, PlanAuthorizationRecordError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.models import DryRunReport, DryRunStatus, PlannedLoop, PlannedTask
from llm_research_os.execution.planner import PlanningError
from llm_research_os.spec.models import LoopBlock, ResearchSpec, TaskBlock
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_PYTHON_BRICK,
    WORKER_RUNTIME_PYTHON_SANDBOX,
)

PYTHON_BRICK_CAPABILITY = "execute.local"
MAX_BRICK_REQUEST_JSON_BYTES = 16_384


def brick_execution_document(
    *,
    image_digest: str,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "config": dict(config or {}),
        "imageDigest": image_digest,
        "imageMediaType": IMAGE_MEDIA_PYTHON_BRICK,
        "inputs": dict(inputs or {}),
        "runtime": WORKER_RUNTIME_PYTHON_SANDBOX,
    }


def brick_execution_digest(
    *,
    image_digest: str,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> str:
    return content_digest(
        brick_execution_document(image_digest=image_digest, config=config, inputs=inputs)
    )


def brick_stdin_document(
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "PythonBrickRequest",
        "config": dict(config or {}),
        "inputs": dict(inputs or {}),
    }


def require_execution_digest(
    *,
    image_digest: str,
    config: Mapping[str, object],
    inputs: Mapping[str, object],
    config_digest: str,
) -> None:
    actual = brick_execution_digest(image_digest=image_digest, config=config, inputs=inputs)
    if actual != config_digest:
        raise WorkerCallError(
            "execution object digest does not match the authorized binding",
            code="execution-binding-mismatch",
        )


def require_authorized_execution_citation(
    store: EventStore,
    *,
    project_id: str,
    event_id: str,
    sequence: str,
) -> tuple[PlanAuthorizationEvaluatedPayload, StoredEvent]:
    """Load one authorized execute.local evaluation on this store."""

    stored = store.get_event(event_id)
    if stored is None:
        raise WorkerCallError(
            "authorization event was not found",
            code="authorization-event-not-found",
        )
    if stored.event.sequence != sequence:
        raise WorkerCallError(
            "authorization event sequence does not match",
            code="authorization-sequence-mismatch",
        )
    if stored.event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE:
        raise WorkerCallError(
            "authorization event type is invalid",
            code="authorization-type-mismatch",
        )
    try:
        payload = validate_plan_authorization_evaluated_event(stored.event)
    except PlanAuthorizationRecordError:
        raise WorkerCallError(
            "authorization event is invalid",
            code="authorization-event-invalid",
        ) from None
    if stored.event.data.actor.kind is not ActorKind.HUMAN:
        raise WorkerCallError(
            "authorization actor is not a local human operator",
            code="authorization-actor-not-human",
        )
    if payload.authorized is not True:
        raise WorkerCallError(
            "authorization event is not an authorized decision",
            code="authorization-not-authorized",
        )
    if stored.event.data.project_id != project_id:
        raise WorkerCallError(
            "authorization event does not match this project",
            code="authorization-project-mismatch",
        )
    if PYTHON_BRICK_CAPABILITY not in payload.required_capabilities:
        raise WorkerCallError(
            "authorization event does not grant execute.local",
            code="authorization-capability-mismatch",
        )
    return payload, stored


def require_authorized_execution_binding(
    store: EventStore,
    spec: ResearchSpec,
    registry: BlockRegistry,
    *,
    project_id: str,
    experiment_revision: int,
    planned_task_id: str,
    event_id: str,
    sequence: str,
    image_digest: str,
    config_digest: str,
    workflow_id: str | None = None,
) -> PlanAuthorizationEvaluatedPayload:
    """Rebuild the cited plan and bind the grant to that planned execution object.

    ``planned_task_id`` is the graph node id. Runtime attempt identity is
    ``runId`` / ``attemptId`` on the grant, not this lookup.
    """

    payload, stored = require_authorized_execution_citation(
        store,
        project_id=project_id,
        event_id=event_id,
        sequence=sequence,
    )
    if workflow_id is not None and workflow_id != payload.workflow_id:
        raise WorkerCallError(
            "authorization event does not match this project revision",
            code="authorization-project-mismatch",
        )
    if (
        stored.event.data.experiment_revision != experiment_revision
        or spec.metadata.id != project_id
        or spec.metadata.revision != experiment_revision
    ):
        raise WorkerCallError(
            "authorization event does not match this project revision",
            code="authorization-project-mismatch",
        )
    try:
        report = TrustedKernel(registry).dry_run(spec, workflow_id=payload.workflow_id)
    except (PlanningError, RegistryError):
        raise WorkerCallError(
            "authorized plan could not be rebuilt",
            code="authorization-plan-not-ready",
        ) from None
    if report.status is not DryRunStatus.READY or report.digests.plan is None:
        raise WorkerCallError(
            "authorized plan could not be rebuilt",
            code="authorization-plan-not-ready",
        )
    try:
        authorization = authorize_plan(
            report,
            PlanAuthorizationPolicy(
                spec_digest=report.digests.spec,
                registry_digest=report.digests.registry,
                plan_digest=report.digests.plan,
                granted_capabilities=payload.required_capabilities,
            ),
        )
    except PlanAuthorizationError:
        raise WorkerCallError(
            "authorized plan could not be rebuilt",
            code="authorization-plan-not-ready",
        ) from None
    binding = payload.binding
    if (
        binding.spec_digest != report.digests.spec
        or binding.registry_digest != report.digests.registry
        or binding.plan_digest != report.digests.plan
        or binding.decision_digest != authorization.decision_digest
        or report.project.id != project_id
        or report.project.revision != experiment_revision
        or report.workflow_id != payload.workflow_id
    ):
        raise WorkerCallError(
            "authorization event does not match the rebuilt plan",
            code="authorization-binding-mismatch",
        )
    spec_task = _spec_task(spec, payload.workflow_id, planned_task_id)
    planned = _planned_task(report, planned_task_id)
    planned_image, planned_digest = _planned_execution_object(spec_task)
    if (
        planned.config_digest != planned_digest
        or planned_image != image_digest
        or planned_digest != config_digest
    ):
        raise WorkerCallError(
            "execution object is not the authorized planned task",
            code="execution-binding-mismatch",
        )
    return payload


def json_object(value: object, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{field} must be a JSON object")
    return dict(value)


def _spec_task(spec: ResearchSpec, workflow_id: str, planned_task_id: str) -> TaskBlock:
    workflow = next((item for item in spec.workflows if item.id == workflow_id), None)
    if workflow is None:
        raise WorkerCallError(
            "authorization event does not match this project revision",
            code="authorization-project-mismatch",
        )
    found: list[TaskBlock] = []
    pending = [workflow.graph.nodes]
    while pending:
        nodes = pending.pop()
        for node in nodes:
            if type(node) is TaskBlock and node.id == planned_task_id:
                found.append(node)
            elif type(node) is LoopBlock:
                pending.append(node.body.nodes)
    if len(found) != 1:
        raise WorkerCallError(
            "planned task is not in the authorized plan",
            code="planned-task-mismatch",
        )
    return found[0]


def _planned_task(report: DryRunReport, planned_task_id: str) -> PlannedTask:
    if report.plan is None:
        raise WorkerCallError(
            "authorized plan could not be rebuilt",
            code="authorization-plan-not-ready",
        )
    found: list[PlannedTask] = []
    pending = [report.plan.graph]
    while pending:
        graph = pending.pop()
        for stage in graph.stages:
            for node in stage.nodes:
                if type(node) is PlannedTask and node.node_path[-1] == planned_task_id:
                    found.append(node)
                elif type(node) is PlannedLoop:
                    pending.append(node.body)
    if len(found) != 1:
        raise WorkerCallError(
            "planned task is not in the authorized plan",
            code="planned-task-mismatch",
        )
    return found[0]


def _planned_execution_object(task: TaskBlock) -> tuple[str, str]:
    try:
        inner = json_object(task.config.get("config", {}), field="config")
        inputs = json_object(task.config.get("inputs", {}), field="inputs")
    except ValueError:
        raise WorkerCallError(
            "execution object is not the authorized planned task",
            code="execution-binding-mismatch",
        ) from None
    image = task.config.get("imageDigest")
    media = task.config.get("imageMediaType")
    runtime = task.config.get("runtime")
    if (
        type(image) is not str
        or media != IMAGE_MEDIA_PYTHON_BRICK
        or runtime != WORKER_RUNTIME_PYTHON_SANDBOX
    ):
        raise WorkerCallError(
            "execution object is not the authorized planned task",
            code="execution-binding-mismatch",
        )
    return image, brick_execution_digest(image_digest=image, config=inner, inputs=inputs)
