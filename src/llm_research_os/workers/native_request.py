"""Rebuild a closed native request from recorded authorization and queued execution."""

from __future__ import annotations

from pydantic import ValidationError

from llm_research_os.canonical import content_digest
from llm_research_os.events.models import ActorKind
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import PlanAuthorizationRecordError
from llm_research_os.execution.native_reviewed import execution_object
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.control import GrantRecord, QueuedWork
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_NATIVE_REVIEWED,
    WORKER_RUNTIME_NATIVE_REVIEWED,
)


def native_request_from_binding(
    store: EventStore,
    *,
    project_id: str,
    grant: GrantRecord,
    queued: QueuedWork,
    expected_revision: int | None = None,
) -> NativeReviewedExecutionRequest:
    """The returned audit context is not permission to launch or replay a process."""

    stored = store.get_event(grant.authorization_event_id)
    if (
        stored is None
        or stored.event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE
        or str(stored.sequence) != grant.authorization_sequence
        or stored.event.data.project_id != project_id
        or (
            expected_revision is not None
            and stored.event.data.experiment_revision != expected_revision
        )
        or stored.event.data.actor.kind != ActorKind.HUMAN
        or queued.runtime != WORKER_RUNTIME_NATIVE_REVIEWED
        or queued.image_media_type != IMAGE_MEDIA_NATIVE_REVIEWED
        or (queued.task_id, queued.run_id, queued.attempt_id)
        != (grant.task_id, grant.run_id, grant.attempt_id)
        or queued.image_digest != grant.image_digest
        or queued.config_digest != grant.config_digest
        or queued.inputs != {}
    ):
        raise WorkerCallError("native request binding differs", code="execution-binding-mismatch")
    try:
        authorization = validate_plan_authorization_evaluated_event(stored.event)
        if (
            not authorization.authorized
            or "execute.native" not in authorization.required_capabilities
        ):
            raise ValueError("native capability is not authorized")
        request = NativeReviewedExecutionRequest.model_validate(
            {
                **queued.config,
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeReviewedExecutionRequest",
                "projectId": project_id,
                "revisionId": str(stored.event.data.experiment_revision),
                "workflowId": authorization.workflow_id,
                "taskId": grant.task_id,
                "runId": grant.run_id,
                "attemptId": grant.attempt_id,
                "workerId": grant.worker_id,
                "actorId": stored.event.data.actor.id,
                "authorizationEventId": grant.authorization_event_id,
                "authorizationSequence": grant.authorization_sequence,
                "specDigest": authorization.binding.spec_digest,
                "registryDigest": authorization.binding.registry_digest,
                "planDigest": authorization.binding.plan_digest,
                "decisionDigest": authorization.binding.decision_digest,
                "configDigest": queued.config_digest,
            }
        )
    except (ValidationError, PlanAuthorizationRecordError, ValueError):
        raise WorkerCallError(
            "native request is invalid", code="execution-binding-mismatch"
        ) from None
    if (
        execution_object(request) != queued.config
        or content_digest(execution_object(request)) != request.config_digest
        or request.code.bundle_digest != grant.image_digest
    ):
        raise WorkerCallError("native request execution differs", code="execution-binding-mismatch")
    return request
