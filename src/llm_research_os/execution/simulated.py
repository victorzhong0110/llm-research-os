"""Deterministic SimulatedRuntime over a ready single-task plan and RunControl.

This slice binds a defensive ResearchSpec snapshot to TrustedKernel dry-run,
then emits a frozen Run/Attempt lifecycle through RunControl. It does not
import block entrypoints, mint identity, retry CAS, or execute a real runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

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
from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    authorize_plan,
)
from llm_research_os.execution.consume import consume_local_authorization
from llm_research_os.execution.errors import PlanAuthorizationError, SimulationError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.models import DryRunReport, DryRunStatus, ExecutionPlan, PlannedTask
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.execution.synthetic import (
    append_synthetic_metrics,
    metric_types_in_request,
    preflight_synthetic_metrics,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.runs import RunControl, RunSnapshot, RunStateProjection, RunStatus
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
_UNSUPPORTED_PLAN = "simulation only supports one simulated.experiment@0.1.0 task"
_RUN_MISMATCH = "existing run does not match this simulation request"

TYPE_RUN_QUEUED = "run.queued"
TYPE_RUN_STARTED = "run.started"
TYPE_RUN_COMPLETED = "run.completed"
TYPE_RUN_FAILED = "run.failed"
TYPE_RUN_CANCELLED = "run.cancelled"
TYPE_ATTEMPT_QUEUED = "attempt.queued"
TYPE_ATTEMPT_STARTED = "attempt.started"
TYPE_ATTEMPT_SUCCEEDED = "attempt.succeeded"
TYPE_ATTEMPT_FAILED = "attempt.failed"
TYPE_ATTEMPT_UNKNOWN = "attempt.unknown"
TYPE_ATTEMPT_CANCELLED = "attempt.cancelled"

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
        TYPE_ATTEMPT_CANCELLED,
    }
)


class SimulationDisposition(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
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
    authorization_event_id: str
    authorization_sequence: str
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
        authorization = _authorize_simulated_plan(report)
        outcome = _require_outcome(task)
        consumed = consume_local_authorization(
            self._store,
            event_id=request_fields.authorization_event_id,
            sequence=request_fields.authorization_sequence,
            report=report,
            authorization=authorization,
            project_id=self._project_id,
        )
        head = self._control.rebuild()
        snapshot = head.snapshot
        if snapshot is not None:
            _require_matching_run(
                snapshot,
                report,
                self._run_id,
                request_fields.attempt_id,
                authorization.decision_digest,
                consumed,
            )
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
            decision_digest=authorization.decision_digest,
            consumed=consumed,
            project_id=self._project_id,
            run_id=self._run_id,
            revision=frozen_spec.metadata.revision,
            attempt_id=request_fields.attempt_id,
        )
        _preflight_remaining(self._store, self._projection, snapshot, drafts, head.last_sequence)
        emit_metrics = _should_emit_synthetic_metrics(outcome, remaining, request_fields.events)
        if emit_metrics:
            preflight_synthetic_metrics(
                self._store,
                request_fields.events,
                source=request_fields.source,
                subject=request_fields.subject,
                stream_id=request_fields.stream_id,
                actor_id=request_fields.actor_id,
                project_id=self._project_id,
                run_id=self._run_id,
                revision=frozen_spec.metadata.revision,
                attempt_id=request_fields.attempt_id,
                lifecycle_draft_count=len(drafts),
                frozen_head=head.last_sequence,
            )
        stored: list[StoredEvent] = []
        committed = snapshot
        if emit_metrics and TYPE_ATTEMPT_STARTED not in remaining:
            stored.extend(
                _append_request_metrics(
                    self._store,
                    request_fields,
                    project_id=self._project_id,
                    run_id=self._run_id,
                    revision=frozen_spec.metadata.revision,
                )
            )
            committed = self._control.rebuild().snapshot
        for draft in drafts:
            result = self._control.append(draft)
            stored.append(result.stored)
            committed = result.snapshot
            if emit_metrics and result.stored.event.type == TYPE_ATTEMPT_STARTED:
                stored.extend(
                    _append_request_metrics(
                        self._store,
                        request_fields,
                        project_id=self._project_id,
                        run_id=self._run_id,
                        revision=frozen_spec.metadata.revision,
                    )
                )
                committed = self._control.rebuild().snapshot
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
    authorization_event_id: str
    authorization_sequence: str
    events: dict[str, tuple[str, str]]


def _authorize_simulated_plan(report: DryRunReport) -> PlanAuthorizationResult:
    """Apply the fixed zero-side-effect T0 policy before simulated execution."""

    if report.digests.plan is None:
        raise SimulationError("simulation plan authorization failed")
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("simulate",),
    )
    try:
        authorization = authorize_plan(report, policy)
    except PlanAuthorizationError:
        raise SimulationError("simulation plan authorization failed") from None
    if not authorization.authorized:
        raise SimulationError("simulation plan was not authorized")
    return authorization


def _freeze_spec(spec: object) -> ResearchSpec:
    if isinstance(spec, ResearchSpec):
        payload: object = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        payload = spec
    try:
        isolated = snapshot_json_document(payload)
    except JsonCloneError:
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
        or type(request.authorization_event_id) is not str
        or type(request.authorization_sequence) is not str
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
        authorization_event_id=request.authorization_event_id,
        authorization_sequence=request.authorization_sequence,
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


def _reject_unsupported_plan(code: str) -> NoReturn:
    raise SimulationError(_UNSUPPORTED_PLAN, code=code)


def _reject_run_mismatch(code: str) -> NoReturn:
    raise SimulationError(_RUN_MISMATCH, code=code)


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
        raise SimulationError(
            "simulation plan is not bound to this spec and registry",
            code="plan-binding-mismatch",
        )
    workflow = next((item for item in spec.workflows if str(item.id) == workflow_id), None)
    if workflow is None:
        raise SimulationError("simulation workflow is not available", code="workflow-not-available")
    if workflow.graph.edges:
        _reject_unsupported_plan("edges-not-empty")
    if len(workflow.graph.nodes) != 1:
        _reject_unsupported_plan("nodes-not-single")
    spec_node = workflow.graph.nodes[0]
    if not isinstance(spec_node, TaskBlock):
        _reject_unsupported_plan("node-not-task")
    if spec_node.resource_refs:
        _reject_unsupported_plan("task-resource-refs-not-empty")
    if str(spec_node.block_type) != _SUPPORTED_BLOCK_ID:
        _reject_unsupported_plan("unsupported-block-type")
    if str(spec_node.block_version) != _SUPPORTED_BLOCK_VERSION:
        _reject_unsupported_plan("unsupported-block-version")
    if spec.resources:
        _reject_unsupported_plan("spec-resources-not-empty")
    if plan.resources:
        _reject_unsupported_plan("plan-resources-not-empty")
    if plan.policy_requirements:
        _reject_unsupported_plan("policy-requirements-not-empty")
    if plan.graph.edges:
        _reject_unsupported_plan("plan-edges-not-empty")
    if len(plan.graph.stages) != 1:
        _reject_unsupported_plan("stages-not-single")
    if len(plan.graph.stages[0].nodes) != 1:
        _reject_unsupported_plan("stage-nodes-not-single")
    if report.summary.task_count != 1:
        _reject_unsupported_plan("task-count-not-one")
    if report.summary.approval_count != 0:
        _reject_unsupported_plan("approval-count-not-zero")
    if report.summary.loop_count != 0:
        _reject_unsupported_plan("loop-count-not-zero")
    planned = plan.graph.stages[0].nodes[0]
    if not isinstance(planned, PlannedTask):
        _reject_unsupported_plan("planned-node-not-task")
    if planned.resource_refs:
        _reject_unsupported_plan("planned-resource-refs-not-empty")
    if str(planned.block.id) != _SUPPORTED_BLOCK_ID:
        _reject_unsupported_plan("planned-block-id-mismatch")
    if str(planned.block.version) != _SUPPORTED_BLOCK_VERSION:
        _reject_unsupported_plan("planned-block-version-mismatch")
    if planned.block.runtime_type is not RuntimeType.SIMULATED:
        _reject_unsupported_plan("planned-runtime-not-simulated")
    registered = registry.resolve(_SUPPORTED_BLOCK_ID, _SUPPORTED_BLOCK_VERSION)
    canonical_digest = _canonical_simulated_digest()
    if planned.block.manifest_digest != canonical_digest:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="manifest-digest-mismatch",
        )
    if registered.digest != canonical_digest:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="registry-manifest-digest-mismatch",
        )
    if registered.manifest.permissions:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="manifest-permissions-not-empty",
        )
    if planned.block.manifest_digest != registered.digest:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="planned-registry-digest-mismatch",
        )
    if registered.manifest.runtime.type is not RuntimeType.SIMULATED:
        raise SimulationError(
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="registered-runtime-not-simulated",
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
            "simulation requires the canonical simulated.experiment@0.1.0 manifest",
            code="canonical-manifest-missing",
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
    decision_digest: str,
    consumed: StoredEvent,
) -> None:
    if snapshot.project_id != report.project.id:
        _reject_run_mismatch("project-id-mismatch")
    if snapshot.experiment_revision != report.project.revision:
        _reject_run_mismatch("experiment-revision-mismatch")
    if snapshot.run_id != run_id:
        _reject_run_mismatch("run-id-mismatch")
    if snapshot.workflow_id != report.workflow_id:
        _reject_run_mismatch("workflow-id-mismatch")
    if snapshot.digests.spec != report.digests.spec:
        _reject_run_mismatch("spec-digest-mismatch")
    if snapshot.digests.registry != report.digests.registry:
        _reject_run_mismatch("registry-digest-mismatch")
    if snapshot.digests.plan != report.digests.plan:
        _reject_run_mismatch("plan-digest-mismatch")
    if snapshot.digests.decision_digest != decision_digest:
        _reject_run_mismatch("decision-digest-mismatch")
    if snapshot.consumed_authorization is None:
        _reject_run_mismatch("authorization-citation-missing")
    elif snapshot.consumed_authorization.event_id != consumed.event.id:
        _reject_run_mismatch("authorization-event-id-mismatch")
    elif snapshot.consumed_authorization.sequence != consumed.sequence:
        _reject_run_mismatch("authorization-sequence-mismatch")
    if snapshot.max_attempts != _MAX_ATTEMPTS:
        _reject_run_mismatch("max-attempts-mismatch")
    if snapshot.attempts and snapshot.attempts[0].attempt_id != attempt_id:
        _reject_run_mismatch("attempt-id-mismatch")


def _path_for_outcome(outcome: str) -> tuple[str, ...]:
    if outcome == _OUTCOME_SUCCESS:
        return SUCCESS_PATH
    if outcome == _OUTCOME_FAILURE:
        return FAILURE_PATH
    return UNKNOWN_PATH


def _should_emit_synthetic_metrics(
    outcome: str,
    remaining: tuple[str, ...],
    events: dict[str, tuple[str, str]],
) -> bool:
    if outcome != _OUTCOME_SUCCESS:
        return False
    if TYPE_ATTEMPT_CANCELLED in remaining or TYPE_RUN_CANCELLED in remaining:
        return False
    return bool(metric_types_in_request(events))


def _append_request_metrics(
    store: EventStore,
    request: _FrozenRequest,
    *,
    project_id: str,
    run_id: str,
    revision: int,
) -> list[StoredEvent]:
    return append_synthetic_metrics(
        store,
        request.events,
        source=request.source,
        subject=request.subject,
        stream_id=request.stream_id,
        actor_id=request.actor_id,
        project_id=project_id,
        run_id=run_id,
        revision=revision,
        attempt_id=request.attempt_id,
    )


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
    if attempt.status is AttemptStatus.CANCELLED:
        emitted.append(TYPE_ATTEMPT_CANCELLED)
        if snapshot.status is RunStatus.CANCELLED:
            emitted.append(TYPE_RUN_CANCELLED)
        return tuple(emitted)
    _reject_run_mismatch("unexpected-attempt-status")


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
    if snapshot.status in {RunStatus.UNKNOWN, RunStatus.LOST}:
        return (), SimulationDisposition.UNRESOLVED
    if snapshot.status is RunStatus.CANCELLED:
        return (), SimulationDisposition.CANCELLED
    if not _outcome_already_observed(snapshot) and _cancellation_actionable(snapshot):
        remaining = _cancel_remaining(snapshot)
        if remaining:
            return remaining, None
        return (), SimulationDisposition.UNRESOLVED
    emitted = _emitted_types(snapshot)
    if emitted != full[: len(emitted)]:
        _reject_run_mismatch("emitted-prefix-mismatch")
    remaining = full[len(emitted) :]
    if not remaining:
        return (), _disposition_for_snapshot(snapshot)
    return remaining, None


def _outcome_already_observed(snapshot: RunSnapshot) -> bool:
    if not snapshot.attempts:
        return False
    latest = snapshot.attempts[-1]
    return latest.status in {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED}


def _cancellation_actionable(snapshot: RunSnapshot) -> bool:
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


def _cancel_remaining(snapshot: RunSnapshot) -> tuple[str, ...]:
    remaining: list[str] = []
    active_id = snapshot.active_attempt_id
    active = None
    if active_id is not None:
        active = next(
            (item for item in snapshot.attempts if item.attempt_id == active_id),
            None,
        )
    if (
        active is not None
        and active.status is not AttemptStatus.CANCELLED
        and (snapshot.cancellation_requested or active.cancellation_requested)
    ):
        remaining.append(TYPE_ATTEMPT_CANCELLED)
    if snapshot.cancellation_requested:
        remaining.append(TYPE_RUN_CANCELLED)
    return tuple(remaining)


def _disposition_for_snapshot(snapshot: RunSnapshot) -> SimulationDisposition:
    if snapshot.status is RunStatus.COMPLETED:
        return SimulationDisposition.COMPLETED
    if snapshot.status is RunStatus.FAILED:
        return SimulationDisposition.FAILED
    if snapshot.status is RunStatus.UNKNOWN:
        return SimulationDisposition.UNKNOWN
    if snapshot.status is RunStatus.CANCELLED:
        return SimulationDisposition.CANCELLED
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
    decision_digest: str,
    consumed: StoredEvent,
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
        payload = _payload_for(event_type, report, decision_digest, consumed)
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


def _payload_for(
    event_type: str,
    report: DryRunReport,
    decision_digest: str,
    consumed: StoredEvent,
) -> dict[str, Any]:
    if event_type == TYPE_RUN_QUEUED:
        return {
            "workflowId": report.workflow_id,
            "specDigest": report.digests.spec,
            "registryDigest": report.digests.registry,
            "planDigest": report.digests.plan,
            "decisionDigest": decision_digest,
            "authorizationEventId": consumed.event.id,
            "authorizationSequence": consumed.event.sequence,
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
