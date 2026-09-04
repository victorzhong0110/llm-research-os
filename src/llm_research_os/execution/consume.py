"""Local EventStore consumption of one plan-authorization evaluation fact.

SimulatedRuntime does not treat the stored event as a signed launch JWT. Local
authentication for this slice is: the cited ``{eventId, sequence}`` exists on
*this* EventStore, the store-assigned sequence matches, the actor kind is
human, and the four-digest binding matches the in-process gate. Payload
literals remain ``not-authenticated`` / ``audit-only`` / ``not-executed``.
"""

from __future__ import annotations

from llm_research_os.events.models import ActorKind, ResearchEvent
from llm_research_os.execution.authorization import PlanAuthorizationResult
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    PlanAuthorizationEvaluatedPayload,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import PlanAuthorizationRecordError, SimulationError
from llm_research_os.execution.models import DryRunReport
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore


def consume_local_authorization(
    store: EventStore,
    *,
    event_id: str,
    sequence: str,
    report: DryRunReport,
    authorization: PlanAuthorizationResult,
    project_id: str,
) -> StoredEvent:
    """Load and bind one local ``plan.authorization.evaluated`` fact.

    Fail closed before the caller appends any Run/Attempt lifecycle event.
    """

    if type(event_id) is not str or type(sequence) is not str:
        raise SimulationError(
            "simulation authorization citation is invalid",
            code="authorization-citation-invalid",
        )
    stored = store.get_event(event_id)
    if stored is None:
        raise SimulationError(
            "authorization event was not found",
            code="authorization-event-not-found",
        )
    if stored.event.sequence != sequence:
        raise SimulationError(
            "authorization event sequence does not match",
            code="authorization-sequence-mismatch",
        )
    event = stored.event
    if type(event) is not ResearchEvent or event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE:
        raise SimulationError(
            "authorization event type is invalid",
            code="authorization-type-mismatch",
        )
    try:
        payload = validate_plan_authorization_evaluated_event(event)
    except PlanAuthorizationRecordError:
        raise SimulationError(
            "authorization event is invalid",
            code="authorization-event-invalid",
        ) from None
    if event.data.actor.kind is not ActorKind.HUMAN:
        # Caller-asserted kind on this store; not cryptographic authentication.
        raise SimulationError(
            "authorization actor is not a local human operator",
            code="authorization-actor-not-human",
        )
    if payload.authorized is not True:
        raise SimulationError(
            "authorization event is not an authorized decision",
            code="authorization-not-authorized",
        )
    _require_binding(payload, report, authorization, project_id, event)
    return stored


def _require_binding(
    payload: PlanAuthorizationEvaluatedPayload,
    report: DryRunReport,
    authorization: PlanAuthorizationResult,
    project_id: str,
    event: ResearchEvent,
) -> None:
    binding = payload.binding
    if (
        binding.spec_digest != report.digests.spec
        or binding.registry_digest != report.digests.registry
        or binding.plan_digest != report.digests.plan
        or binding.decision_digest != authorization.decision_digest
        or binding.spec_digest != authorization.spec_digest
        or binding.registry_digest != authorization.registry_digest
        or binding.plan_digest != authorization.plan_digest
    ):
        raise SimulationError(
            "authorization event does not match the in-process gate",
            code="authorization-binding-mismatch",
        )
    if (
        event.data.project_id != project_id
        or event.data.project_id != report.project.id
        or event.data.experiment_revision != report.project.revision
        or payload.workflow_id != report.workflow_id
    ):
        raise SimulationError(
            "authorization event does not match this project revision",
            code="authorization-project-mismatch",
        )
