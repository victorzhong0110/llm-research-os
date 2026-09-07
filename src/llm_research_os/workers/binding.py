"""Authorized host-python execution objects. Not kernel isolation (TM-043)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from llm_research_os.canonical import content_digest
from llm_research_os.events.models import ActorKind
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import PlanAuthorizationRecordError
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
) -> None:
    """Grant recording may cite only an authorized execute.local evaluation on this store."""

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


def json_object(value: object, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{field} must be a JSON object")
    return dict(value)
