"""Seeded synthetic ``training.step`` / ``evaluation.metric`` facts.

SimulatedRuntime does not call a clock or CSPRNG. Numeric values are derived
from a JCS digest of caller-owned ``runId`` / ``attemptId`` / type. Metric
events are not Run/Attempt lifecycle types; RunControl rejects them, so they
are appended through EventStore after ``attempt.started``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from llm_research_os.canonical import JCS_SHA256_PREFIX, content_digest
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    RESEARCH_EVENT_SCHEMA_ID,
    EventDocumentModel,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.execution.errors import SimulationError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

TYPE_TRAINING_STEP = "training.step"
TYPE_EVALUATION_METRIC = "evaluation.metric"
METRIC_TYPES = (TYPE_TRAINING_STEP, TYPE_EVALUATION_METRIC)
SYNTHETIC_KIND: Literal["synthetic"] = "synthetic"
RATIO_PATTERN = r"^0\.[0-9]{2}$"
_SEED_DIGEST_LENGTH = len(JCS_SHA256_PREFIX) + 64
_SEED_DIGEST_PATTERN = rf"^{JCS_SHA256_PREFIX}[0-9a-f]{{64}}$"


class MetricDocumentModel(EventDocumentModel):
    """Frozen metric payloads: aliases only, strict, no trimming."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


class TrainingStepPayload(MetricDocumentModel):
    kind: Literal["synthetic"]
    step: Literal[1]
    loss: str = Field(pattern=RATIO_PATTERN, min_length=4, max_length=4)
    seed_digest: str = Field(
        alias="seedDigest",
        min_length=_SEED_DIGEST_LENGTH,
        max_length=_SEED_DIGEST_LENGTH,
        pattern=_SEED_DIGEST_PATTERN,
    )


class EvaluationMetricPayload(MetricDocumentModel):
    kind: Literal["synthetic"]
    name: Literal["accuracy"]
    value: str = Field(pattern=RATIO_PATTERN, min_length=4, max_length=4)
    split: Literal["synthetic"]
    seed_digest: str = Field(
        alias="seedDigest",
        min_length=_SEED_DIGEST_LENGTH,
        max_length=_SEED_DIGEST_LENGTH,
        pattern=_SEED_DIGEST_PATTERN,
    )


def metric_seed_digest(run_id: str, attempt_id: str, event_type: str) -> str:
    """Return a JCS digest that uniquely seeds one synthetic metric type."""

    return content_digest({"attemptId": attempt_id, "runId": run_id, "type": event_type})


def synthetic_training_payload(run_id: str, attempt_id: str) -> dict[str, Any]:
    seed = metric_seed_digest(run_id, attempt_id, TYPE_TRAINING_STEP)
    return {
        "kind": SYNTHETIC_KIND,
        "step": 1,
        "loss": _ratio_from_digest(seed, 0),
        "seedDigest": seed,
    }


def synthetic_evaluation_payload(run_id: str, attempt_id: str) -> dict[str, Any]:
    seed = metric_seed_digest(run_id, attempt_id, TYPE_EVALUATION_METRIC)
    return {
        "kind": SYNTHETIC_KIND,
        "name": "accuracy",
        "value": _ratio_from_digest(seed, 2),
        "split": "synthetic",
        "seedDigest": seed,
    }


def parse_training_step_payload(event: ResearchEvent) -> TrainingStepPayload:
    if event.type != TYPE_TRAINING_STEP:
        raise SimulationError("event type is not training.step", code="metric-type-mismatch")
    try:
        return TrainingStepPayload.model_validate(event.data.payload)
    except ValidationError:
        raise SimulationError(
            "training.step payload is invalid",
            code="invalid-metric-payload",
        ) from None


def parse_evaluation_metric_payload(event: ResearchEvent) -> EvaluationMetricPayload:
    if event.type != TYPE_EVALUATION_METRIC:
        raise SimulationError("event type is not evaluation.metric", code="metric-type-mismatch")
    try:
        return EvaluationMetricPayload.model_validate(event.data.payload)
    except ValidationError:
        raise SimulationError(
            "evaluation.metric payload is invalid",
            code="invalid-metric-payload",
        ) from None


def metric_types_in_request(events: dict[str, tuple[str, str]]) -> tuple[str, ...]:
    return tuple(event_type for event_type in METRIC_TYPES if event_type in events)


def preflight_synthetic_metrics(
    store: EventStore,
    events: dict[str, tuple[str, str]],
    *,
    source: str,
    subject: str,
    stream_id: str,
    actor_id: str,
    project_id: str,
    run_id: str,
    revision: int,
    attempt_id: str,
    lifecycle_draft_count: int,
    frozen_head: int,
) -> None:
    """Validate metric drafts and ids before the first EventStore write of this call."""

    wanted = metric_types_in_request(events)
    if not wanted:
        return
    extra = 0
    for event_type in wanted:
        event_id, _time = events[event_type]
        existing = store.get_event(event_id)
        if existing is None:
            extra += 1
            continue
        if existing.event.type != event_type:
            raise SimulationError("simulation event id already exists", code="event-id-exists")
    if frozen_head + lifecycle_draft_count + extra > CLOUD_EVENTS_INTEGER_MAX:
        raise SimulationError("global event sequence is exhausted", code="sequence-exhausted")
    for event_type in wanted:
        event_id, event_time = events[event_type]
        if store.get_event(event_id) is not None:
            continue
        draft = metric_event_draft(
            event_type,
            events,
            source=source,
            subject=subject,
            stream_id=stream_id,
            actor_id=actor_id,
            project_id=project_id,
            run_id=run_id,
            revision=revision,
            attempt_id=attempt_id,
        )
        probe = dict(draft)
        probe.update(
            {
                "sequence": "1",
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        try:
            event = validate_event_document(probe)
        except ValidationError:
            raise SimulationError(
                "event draft failed ResearchEvent validation",
                code="invalid-event-draft",
            ) from None
        if event.id != event_id or event.time != event_time:
            raise SimulationError(
                "simulation event identities are invalid",
                code="invalid-identity",
            )


def append_synthetic_metrics(
    store: EventStore,
    events: dict[str, tuple[str, str]],
    *,
    source: str,
    subject: str,
    stream_id: str,
    actor_id: str,
    project_id: str,
    run_id: str,
    revision: int,
    attempt_id: str,
) -> list[StoredEvent]:
    """Append missing synthetic metric facts. Existing matching ids are skipped."""

    stored: list[StoredEvent] = []
    for event_type in metric_types_in_request(events):
        event_id, _time = events[event_type]
        existing = store.get_event(event_id)
        if existing is not None:
            if existing.event.type != event_type:
                raise SimulationError("simulation event id already exists", code="event-id-exists")
            continue
        draft = metric_event_draft(
            event_type,
            events,
            source=source,
            subject=subject,
            stream_id=stream_id,
            actor_id=actor_id,
            project_id=project_id,
            run_id=run_id,
            revision=revision,
            attempt_id=attempt_id,
        )
        head = store.freeze_high_water()
        stored.append(store.append(draft, expected_last_sequence=head))
    return stored


def metric_event_draft(
    event_type: str,
    events: dict[str, tuple[str, str]],
    *,
    source: str,
    subject: str,
    stream_id: str,
    actor_id: str,
    project_id: str,
    run_id: str,
    revision: int,
    attempt_id: str,
) -> dict[str, Any]:
    identity = events.get(event_type)
    if identity is None:
        raise SimulationError(
            "simulation event identities are incomplete",
            code="incomplete-events",
        )
    event_id, event_time = identity
    if event_type == TYPE_TRAINING_STEP:
        payload: dict[str, Any] = synthetic_training_payload(run_id, attempt_id)
    elif event_type == TYPE_EVALUATION_METRIC:
        payload = synthetic_evaluation_payload(run_id, attempt_id)
    else:
        raise SimulationError("metric event type is not supported", code="unsupported-metric-type")
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": event_type,
        "time": event_time,
        "subject": subject,
        "dataschema": RESEARCH_EVENT_SCHEMA_ID,
        "datacontenttype": "application/json",
        "streamid": stream_id,
        "data": {
            "schemaVersion": "v0alpha1",
            "actor": {"id": actor_id, "kind": "system"},
            "projectId": project_id,
            "experimentRevision": revision,
            "payload": payload,
            "evidenceRefs": [],
            "runId": run_id,
            "attemptId": attempt_id,
        },
    }


def _ratio_from_digest(digest: str, offset: int) -> str:
    hex_part = digest.rsplit(":", 1)[-1]
    raw = int(hex_part[offset : offset + 2], 16) % 100
    return f"0.{raw:02d}"
