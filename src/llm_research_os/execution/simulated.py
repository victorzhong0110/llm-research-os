"""Deterministic SimulatedRuntime over a ready single-task plan and RunControl.

This slice binds a defensive ResearchSpec snapshot to TrustedKernel dry-run,
then emits a frozen Run/Attempt lifecycle through RunControl. It does not
import block entrypoints, mint identity, retry CAS, or execute a real runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.models import BlockManifest, RuntimeType
from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.canonical import content_digest
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    RESEARCH_EVENT_SCHEMA_ID,
    validate_event_document,
)
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.models import DryRunReport, DryRunStatus, ExecutionPlan, PlannedTask
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.runs import RunControl, RunSnapshot, RunStateProjection, RunStatus
from llm_research_os.runs.control import _snapshot_json_document
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import AttemptStatus
from llm_research_os.spec.models import ResearchSpec, TaskBlock
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

_MAX_ATTEMPTS = 1
_SUPPORTED_BLOCK_ID = "simulated.experiment"
_SUPPORTED_BLOCK_VERSION = "0.1.0"
_OUTCOME_SUCCESS = "success"
_OUTCOME_FAILURE = "failure"
_OUTCOME_UNKNOWN = "unknown"
_SUPPORTED_OUTCOMES = frozenset({_OUTCOME_SUCCESS, _OUTCOME_FAILURE, _OUTCOME_UNKNOWN})
_REASON_FAILURE = "simulation.outcome.failure"
_REASON_UNKNOWN = "simulation.outcome.unknown"
_RETRY_NOT_RETRYABLE = "not-retryable"

TYPE_RUN_QUEUED = "run.queued"
TYPE_RUN_STARTED = "run.started"
TYPE_RUN_COMPLETED = "run.completed"
TYPE_RUN_FAILED = "run.failed"
TYPE_ATTEMPT_QUEUED = "attempt.queued"
TYPE_ATTEMPT_STARTED = "attempt.started"
TYPE_ATTEMPT_SUCCEEDED = "attempt.succeeded"
TYPE_ATTEMPT_FAILED = "attempt.failed"
TYPE_ATTEMPT_UNKNOWN = "attempt.unknown"

SUCCESS_PATH = (
    TYPE_RUN_QUEUED,
    TYPE_RUN_STARTED,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_STARTED,
    TYPE_ATTEMPT_SUCCEEDED,
    TYPE_RUN_COMPLETED,
)
FAILURE_PATH = (
    TYPE_RUN_QUEUED,
    TYPE_RUN_STARTED,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_STARTED,
    TYPE_ATTEMPT_FAILED,
    TYPE_RUN_FAILED,
)
UNKNOWN_PATH = (
    TYPE_RUN_QUEUED,
    TYPE_RUN_STARTED,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_STARTED,
    TYPE_ATTEMPT_UNKNOWN,
)
_ATTEMPT_TYPES = frozenset(
    {
        TYPE_ATTEMPT_QUEUED,
        TYPE_ATTEMPT_STARTED,
        TYPE_ATTEMPT_SUCCEEDED,
        TYPE_ATTEMPT_FAILED,
        TYPE_ATTEMPT_UNKNOWN,
    }
)


class SimulationDisposition(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SimulationEventIdentity:
    """Caller-owned identity for one lifecycle event that may be appended."""

    id: str
    time: str


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Explicit simulation inputs. Runtime does not mint id, time, or streamid."""

    workflow_id: str
    attempt_id: str
    source: str
    subject: str
    stream_id: str
    actor_id: str
    events: dict[str, SimulationEventIdentity]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """One simulated lifecycle fold bound to a ready dry-run report."""

    report: DryRunReport
    snapshot: RunSnapshot
    stored: tuple[StoredEvent, ...]
    disposition: SimulationDisposition


class SimulatedRuntime:
    """Replay, preflight, and CAS-append a single simulated.experiment task."""

    def __init__(
        self,
        store: EventStore,
        registry: BlockRegistry,
        *,
        project_id: str,
        run_id: str,
    ) -> None:
        self._store = store
        self._registry = registry
        self._project_id = project_id
        self._run_id = run_id
        self._control = RunControl(store, project_id=project_id, run_id=run_id)
        self._projection = RunStateProjection(project_id=project_id, run_id=run_id)

    def run(
        self,
        spec: ResearchSpec | dict[str, Any],
        request: SimulationRequest,
    ) -> SimulationResult:
        """Dry-run a frozen spec snapshot, then append the remaining lifecycle prefix."""

        frozen_spec = _freeze_spec(spec)
        request_fields = _freeze_request(request)
        if not self._registry.sealed:
            raise SimulationError("simulation requires a sealed registry")
        if str(frozen_spec.metadata.id) != self._project_id:
            raise SimulationError("simulation project does not match this runtime")
        report = _ready_report(frozen_spec, self._registry, request_fields.workflow_id)
        plan = report.plan
        if plan is None or report.digests.plan is None:
            raise SimulationError("dry-run did not produce a ready plan")
        task = _require_supported_plan(
            frozen_spec,
            plan,
            report,
            self._registry,
            workflow_id=request_fields.workflow_id,
            project_id=self._project_id,
        )
        outcome = _require_outcome(task)
        head = self._control.rebuild()
        snapshot = head.snapshot
        if snapshot is not None:
            _require_matching_run(snapshot, report, self._run_id, request_fields.attempt_id)
        remaining, stop_disposition = _continuation(snapshot, outcome)
        if stop_disposition is not None:
            return SimulationResult(
                report=report,
                snapshot=_require_snapshot(snapshot),
                stored=(),
                disposition=stop_disposition,
            )
        drafts = _remaining_drafts(
            remaining,
            request_fields,
            report=report,
            project_id=self._project_id,
            run_id=self._run_id,
            revision=frozen_spec.metadata.revision,
            attempt_id=request_fields.attempt_id,
        )
        _preflight_remaining(self._store, self._projection, snapshot, drafts, head.last_sequence)
        stored: list[StoredEvent] = []
        committed = snapshot
        for draft in drafts:
            result = self._control.append(draft)
            stored.append(result.stored)
            committed = result.snapshot
        if committed is None:
            raise SimulationError("simulation produced no snapshot")
        return SimulationResult(
            report=report,
            snapshot=committed,
            stored=tuple(stored),
            disposition=_disposition_for_snapshot(committed),
        )


@dataclass(frozen=True, slots=True)
class _FrozenRequest:
    workflow_id: str
    attempt_id: str
    source: str
    subject: str
    stream_id: str
    actor_id: str
    events: dict[str, tuple[str, str]]


def _freeze_spec(spec: object) -> ResearchSpec:
    if isinstance(spec, ResearchSpec):
        payload: object = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        payload = spec
    try:
        isolated = _snapshot_json_document(payload)
    except RunControlError:
        snapshot_error = SimulationError("simulation spec must contain only JSON values")
    else:
        try:
            return ResearchSpec.model_validate(isolated)
        except ValidationError:
            spec_error = SimulationError("simulation spec failed ResearchSpec validation")
        raise spec_error
    raise snapshot_error


def _freeze_request(request: SimulationRequest) -> _FrozenRequest:
    if type(request.workflow_id) is not str or type(request.attempt_id) is not str:
        raise SimulationError("simulation request identity is invalid")
    if (
        type(request.source) is not str
        or type(request.subject) is not str
        or type(request.stream_id) is not str
        or type(request.actor_id) is not str
    ):
        raise SimulationError("simulation request identity is invalid")
    if type(request.events) is not dict:
        raise SimulationError("simulation event identities are invalid")
    events: dict[str, tuple[str, str]] = {}
    for key, identity in request.events.items():
        if type(key) is not str or type(identity) is not SimulationEventIdentity:
            raise SimulationError("simulation event identities are invalid")
        if type(identity.id) is not str or type(identity.time) is not str:
            raise SimulationError("simulation event identities are invalid")
        events[key] = (identity.id, identity.time)
    return _FrozenRequest(
        workflow_id=request.workflow_id,
        attempt_id=request.attempt_id,
        source=request.source,
        subject=request.subject,
        stream_id=request.stream_id,
        actor_id=request.actor_id,
        events=events,
    )


def _ready_report(spec: ResearchSpec, registry: BlockRegistry, workflow_id: str) -> DryRunReport:
    kernel = TrustedKernel(registry)
    try:
        report = kernel.dry_run(spec, workflow_id=workflow_id)
    except PlanningInputError:
        input_error = SimulationError("simulation workflow is not available")
    else:
        if report.status is DryRunStatus.READY and report.plan is not None:
            return report
        blocked_error = SimulationError("dry-run did not produce a ready plan")
        raise blocked_error
    raise input_error


def _require_supported_plan(
    spec: ResearchSpec,
    plan: ExecutionPlan,
    report: DryRunReport,
    registry: BlockRegistry,
    *,
    workflow_id: str,
    project_id: str,
) -> TaskBlock:
    if (
        str(report.project.id) != project_id
        or str(plan.project.id) != project_id
        or report.project.revision != spec.metadata.revision
        or plan.project.revision != spec.metadata.revision
        or str(report.workflow_id) != workflow_id
        or str(plan.workflow_id) != workflow_id
        or report.digests.spec != plan.spec_digest
        or report.digests.registry != plan.registry_digest
        or report.digests.registry != registry.digest()
    ):
        raise SimulationError("simulation plan is not bound to this spec and registry")
    workflow = next((item for item in spec.workflows if str(item.id) == workflow_id), None)
    if workflow is None:
        raise SimulationError("simulation workflow is not available")
    if workflow.graph.edges or len(workflow.graph.nodes) != 1:
        raise SimulationError("simulation only supports one simulated.experiment@0.1.0 task")
    spec_node = workflow.graph.nodes[0]
    if (
        not isinstance(spec_node, TaskBlock)
        or spec_node.resource_refs
        or str(spec_node.block_type) != _SUPPORTED_BLOCK_ID
        or str(spec_node.block_version) != _SUPPORTED_BLOCK_VERSION
    ):
        raise SimulationError("simulation only supports one simulated.experiment@0.1.0 task")
    if (
        spec.resources
        or plan.resources
        or plan.policy_requirements
        or plan.graph.edges
        or len(plan.graph.stages) != 1
        or len(plan.graph.stages[0].nodes) != 1
        or report.summary.task_count != 1
        or report.summary.approval_count != 0
        or report.summary.loop_count != 0
    ):
        raise SimulationError("simulation only supports one simulated.experiment@0.1.0 task")
    planned = plan.graph.stages[0].nodes[0]
    if not isinstance(planned, PlannedTask):
        raise SimulationError("simulation only supports one simulated.experiment@0.1.0 task")
    if (
        planned.resource_refs
        or str(planned.block.id) != _SUPPORTED_BLOCK_ID
        or str(planned.block.version) != _SUPPORTED_BLOCK_VERSION
        or planned.block.runtime_type is not RuntimeType.SIMULATED
    ):
        raise SimulationError("simulation only supports one simulated.experiment@0.1.0 task")
    registered = registry.resolve(_SUPPORTED_BLOCK_ID, _SUPPORTED_BLOCK_VERSION)
    canonical_digest = _canonical_simulated_digest()
    if (
        planned.block.manifest_digest != canonical_digest
        or registered.digest != canonical_digest
        or registered.manifest.permissions
        or planned.block.manifest_digest != registered.digest
        or registered.manifest.runtime.type is not RuntimeType.SIMULATED
    ):
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest"
        )
    return spec_node


def _canonical_simulated_digest() -> str:
    matches = [
        manifest
        for manifest in builtin_manifests()
        if str(manifest.metadata.id) == _SUPPORTED_BLOCK_ID
        and str(manifest.metadata.version) == _SUPPORTED_BLOCK_VERSION
    ]
    if len(matches) != 1:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest"
        )
    payload = matches[0].model_dump(mode="json", by_alias=True, exclude_none=True)
    snapshot = BlockManifest.model_validate(payload)
    return content_digest(snapshot.model_dump(mode="json", by_alias=True, exclude_none=True))


def _require_outcome(task: TaskBlock) -> str:
    if "outcome" not in task.config:
        raise SimulationError("task config is missing outcome")
    outcome = task.config["outcome"]
    if type(outcome) is not str or outcome not in _SUPPORTED_OUTCOMES:
        raise SimulationError("task outcome is not a supported simulation outcome")
    return outcome


def _require_matching_run(
    snapshot: RunSnapshot,
    report: DryRunReport,
    run_id: str,
    attempt_id: str,
) -> None:
    if (
        snapshot.project_id != report.project.id
        or snapshot.experiment_revision != report.project.revision
        or snapshot.run_id != run_id
        or snapshot.workflow_id != report.workflow_id
        or snapshot.digests.spec != report.digests.spec
        or snapshot.digests.registry != report.digests.registry
        or snapshot.digests.plan != report.digests.plan
        or snapshot.max_attempts != _MAX_ATTEMPTS
    ):
        raise SimulationError("existing run does not match this simulation request")
    if snapshot.attempts and snapshot.attempts[0].attempt_id != attempt_id:
        raise SimulationError("existing run does not match this simulation request")


def _path_for_outcome(outcome: str) -> tuple[str, ...]:
    if outcome == _OUTCOME_SUCCESS:
        return SUCCESS_PATH
    if outcome == _OUTCOME_FAILURE:
        return FAILURE_PATH
    return UNKNOWN_PATH


def _emitted_types(snapshot: RunSnapshot) -> tuple[str, ...]:
    emitted = [TYPE_RUN_QUEUED]
    if snapshot.status is RunStatus.QUEUED:
        return tuple(emitted)
    emitted.append(TYPE_RUN_STARTED)
    if not snapshot.attempts:
        return tuple(emitted)
    emitted.append(TYPE_ATTEMPT_QUEUED)
    attempt = snapshot.attempts[0]
    if attempt.status is AttemptStatus.QUEUED:
        return tuple(emitted)
    emitted.append(TYPE_ATTEMPT_STARTED)
    if attempt.status is AttemptStatus.RUNNING:
        return tuple(emitted)
    if attempt.status is AttemptStatus.SUCCEEDED:
        emitted.append(TYPE_ATTEMPT_SUCCEEDED)
        if snapshot.status is RunStatus.COMPLETED:
            emitted.append(TYPE_RUN_COMPLETED)
        return tuple(emitted)
    if attempt.status is AttemptStatus.FAILED:
        emitted.append(TYPE_ATTEMPT_FAILED)
        if snapshot.status is RunStatus.FAILED:
            emitted.append(TYPE_RUN_FAILED)
        return tuple(emitted)
    if attempt.status is AttemptStatus.UNKNOWN:
        emitted.append(TYPE_ATTEMPT_UNKNOWN)
        return tuple(emitted)
    raise SimulationError("existing run does not match this simulation request")


def _continuation(
    snapshot: RunSnapshot | None,
    outcome: str,
) -> tuple[tuple[str, ...], SimulationDisposition | None]:
    full = _path_for_outcome(outcome)
    if snapshot is None:
        return full, None
    if snapshot.status is RunStatus.COMPLETED:
        return (), SimulationDisposition.COMPLETED
    if snapshot.status is RunStatus.FAILED:
        return (), SimulationDisposition.FAILED
    if snapshot.status in {RunStatus.UNKNOWN, RunStatus.LOST, RunStatus.CANCELLED}:
        return (), SimulationDisposition.UNRESOLVED
    if _unresolved_cancellation(snapshot):
        return (), SimulationDisposition.UNRESOLVED
    emitted = _emitted_types(snapshot)
    if emitted != full[: len(emitted)]:
        raise SimulationError("existing run does not match this simulation request")
    remaining = full[len(emitted) :]
    if not remaining:
        return (), _disposition_for_snapshot(snapshot)
    return remaining, None


def _unresolved_cancellation(snapshot: RunSnapshot) -> bool:
    if snapshot.cancellation_requested:
        return True
    active_id = snapshot.active_attempt_id
    if active_id is not None:
        active = next(
            (item for item in snapshot.attempts if item.attempt_id == active_id),
            None,
        )
        if active is not None and active.cancellation_requested:
            return True
    return bool(snapshot.attempts and snapshot.attempts[-1].status is AttemptStatus.CANCELLED)


def _disposition_for_snapshot(snapshot: RunSnapshot) -> SimulationDisposition:
    if snapshot.status is RunStatus.COMPLETED:
        return SimulationDisposition.COMPLETED
    if snapshot.status is RunStatus.FAILED:
        return SimulationDisposition.FAILED
    if snapshot.status is RunStatus.UNKNOWN:
        return SimulationDisposition.UNKNOWN
    return SimulationDisposition.UNRESOLVED


def _require_snapshot(snapshot: RunSnapshot | None) -> RunSnapshot:
    if snapshot is None:
        raise SimulationError("simulation produced no snapshot")
    return snapshot


def _remaining_drafts(
    remaining: tuple[str, ...],
    request: _FrozenRequest,
    *,
    report: DryRunReport,
    project_id: str,
    run_id: str,
    revision: int,
    attempt_id: str,
) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    for event_id, _time in request.events.values():
        if event_id in seen_ids:
            raise SimulationError("simulation event identities are not unique")
        seen_ids.add(event_id)
    drafts: list[dict[str, Any]] = []
    for event_type in remaining:
        identity = request.events.get(event_type)
        if identity is None:
            raise SimulationError("simulation event identities are incomplete")
        event_id, event_time = identity
        payload = _payload_for(event_type, report)
        data: dict[str, Any] = {
            "schemaVersion": "v0alpha1",
            "actor": {"id": request.actor_id},
            "projectId": project_id,
            "experimentRevision": revision,
            "payload": payload,
            "evidenceRefs": [],
            "runId": run_id,
        }
        if event_type in _ATTEMPT_TYPES:
            data["attemptId"] = attempt_id
        drafts.append(
            {
                "specversion": "1.0",
                "id": event_id,
                "source": request.source,
                "type": event_type,
                "time": event_time,
                "subject": request.subject,
                "dataschema": RESEARCH_EVENT_SCHEMA_ID,
                "datacontenttype": "application/json",
                "streamid": request.stream_id,
                "data": data,
            }
        )
    return drafts


def _payload_for(event_type: str, report: DryRunReport) -> dict[str, Any]:
    if event_type == TYPE_RUN_QUEUED:
        return {
            "workflowId": report.workflow_id,
            "specDigest": report.digests.spec,
            "registryDigest": report.digests.registry,
            "planDigest": report.digests.plan,
            "maxAttempts": _MAX_ATTEMPTS,
        }
    if event_type == TYPE_ATTEMPT_QUEUED:
        return {"ordinal": 1, "retryOf": None, "retryDecisionId": None}
    if event_type == TYPE_ATTEMPT_FAILED:
        return {"reasonCode": _REASON_FAILURE, "retryHint": _RETRY_NOT_RETRYABLE}
    if event_type == TYPE_RUN_FAILED:
        return {"reasonCode": _REASON_FAILURE}
    if event_type == TYPE_ATTEMPT_UNKNOWN:
        return {"reasonCode": _REASON_UNKNOWN}
    return {}


def _preflight_remaining(
    store: EventStore,
    projection: RunStateProjection,
    snapshot: RunSnapshot | None,
    drafts: list[dict[str, Any]],
    frozen_head: int,
) -> None:
    if frozen_head + len(drafts) > CLOUD_EVENTS_INTEGER_MAX:
        raise SimulationError("global event sequence is exhausted")
    probe = snapshot
    for offset, draft in enumerate(drafts, start=1):
        if store.get_event(draft["id"]) is not None:
            raise SimulationError("simulation event id already exists")
        preflight = dict(draft)
        preflight.update(
            {
                "sequence": str(frozen_head + offset),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        try:
            event = validate_event_document(preflight)
        except ValidationError:
            validation_error = SimulationError("event draft failed ResearchEvent validation")
        else:
            probe = projection.apply(probe, event)
            continue
        raise validation_error
    if probe is None:
        raise SimulationError("simulation produced no snapshot")
