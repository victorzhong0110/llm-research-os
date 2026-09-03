"""Read-only reconstruction of audit-only plan-authorization facts.

This projection locates recorded ``plan.authorization.evaluated`` events for one
exact plan identity.  It does not authenticate an actor, choose a single fact as
the authorization a Run used, or grant a runtime any launch authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    CloudEventsString,
    EventDocumentModel,
    EventIdentifier,
    ExperimentRevision,
    ResearchEvent,
    Rfc3339Timestamp,
)
from llm_research_os.execution.authorization import PlanAuthorizationStatus
from llm_research_os.execution.authorization_documents import (
    MAX_AUTHORIZATION_ENTRIES,
    AuthorizationDigest,
    PlanAuthorizationSideEffects,
)
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    PlanAuthorizationEvaluatedPayload,
    PlanAuthorizationEventBinding,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import (
    PlanAuthorizationLineageError,
    PlanAuthorizationRecordError,
)
from llm_research_os.projections.fold import fold_events
from llm_research_os.projections.replay import replay_events
from llm_research_os.spec.io import load_document
from llm_research_os.storage.store import EventStore


def forbid_null_optional_digest(schema: dict[str, Any], definition: str, field: str) -> None:
    """Replace Pydantic's ``anyOf: [string, null]`` with a tagged string.

    Optional digests may be omitted, but JSON ``null`` is not a legal value.
    The generator shape is fail-closed: a missing definition, field, or string
    alternative raises so a Pydantic change cannot republish a nullable contract.
    """

    location = f"$defs.{definition}.properties.{field}"
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError(f"schema is missing $defs while forbidding null on {location}")
    binding = definitions.get(definition)
    if type(binding) is not dict:
        raise ValueError(f"schema is missing {location} definition")
    properties = binding.get("properties")
    if type(properties) is not dict:
        raise ValueError(f"schema is missing {location} properties")
    digest = properties.get(field)
    if type(digest) is not dict:
        raise ValueError(f"schema is missing {location}")
    alternatives = digest.get("anyOf")
    if type(alternatives) is not list:
        raise ValueError(f"schema {location} is not an anyOf union")
    typed = next(
        (item for item in alternatives if type(item) is dict and item.get("type") == "string"),
        None,
    )
    if typed is None:
        raise ValueError(f"schema {location} anyOf has no string alternative")
    properties[field] = typed


PLAN_AUTHORIZATION_LINEAGE_QUERY_SCHEMA_ID = (
    "https://researchos.dev/schemas/plan-authorization-lineage-query/v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_LINEAGE_REPORT_SCHEMA_ID = (
    "https://researchos.dev/schemas/plan-authorization-lineage-report/v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_LINEAGE_API_VERSION: Literal["researchos.dev/v0alpha1"] = (
    "researchos.dev/v0alpha1"
)


class PlanAuthorizationLineageDocumentModel(EventDocumentModel):
    """Frozen alias-only lineage document with no coercion or repair."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=False,
        str_strip_whitespace=False,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
    )


class PlanAuthorizationLineageBinding(PlanAuthorizationLineageDocumentModel):
    """Plan identity used to locate recorded evaluation facts.

    ``specDigest``, ``registryDigest`` and ``planDigest`` are required. They are
    the fields every RunSnapshot carries. Optional ``decisionDigest`` on a
    RunSnapshot is an in-process gate identity, not an audit-event citation.
    On this query, ``decisionDigest`` is optional: omit it to return every
    recorded evaluation of that plan identity; supply it to restrict the
    candidate set to one exact decision.
    """

    spec_digest: AuthorizationDigest = Field(alias="specDigest")
    registry_digest: AuthorizationDigest = Field(alias="registryDigest")
    plan_digest: AuthorizationDigest = Field(alias="planDigest")
    decision_digest: AuthorizationDigest | None = Field(default=None, alias="decisionDigest")

    @model_validator(mode="before")
    @classmethod
    def reject_null_decision_digest(cls, value: object) -> object:
        if type(value) is dict and value.get("decisionDigest", "omitted") is None:
            raise ValueError("decisionDigest must be omitted or a semantic digest")
        return value


class PlanAuthorizationLineageQueryDocument(PlanAuthorizationLineageDocumentModel):
    """Caller-owned identity used to reconstruct authorization audit facts."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["PlanAuthorizationLineageQuery"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    workflow_id: EventIdentifier = Field(alias="workflowId")
    binding: PlanAuthorizationLineageBinding


class PlanAuthorizationLineageMatch(PlanAuthorizationLineageDocumentModel):
    """One recorded evaluation fact located by the lineage query.

    This is a citation into the event log.  It is not a launch credential.
    """

    event_id: CloudEventsString = Field(alias="eventId")
    sequence: int = Field(ge=1, le=CLOUD_EVENTS_INTEGER_MAX)
    time: Rfc3339Timestamp
    stream_id: EventIdentifier = Field(alias="streamid")
    actor_id: EventIdentifier = Field(alias="actorId")
    workflow_id: EventIdentifier = Field(alias="workflowId")
    # Unique Field(strict=False) on this strict model: dumped report-document JSON
    # replays `status` as a plain string, not a StrEnum member.
    status: PlanAuthorizationStatus = Field(strict=False)
    authorized: bool
    binding: PlanAuthorizationEventBinding
    approval_authentication: Literal["not-authenticated"] = Field(alias="approvalAuthentication")
    authority: Literal["audit-only"]
    execution: Literal["not-executed"]

    @classmethod
    def from_event(
        cls,
        event: ResearchEvent,
        payload: PlanAuthorizationEvaluatedPayload,
    ) -> Self:
        return cls(
            eventId=event.id,
            sequence=int(event.sequence),
            time=event.time,
            streamid=event.streamid,
            actorId=event.data.actor.id,
            workflowId=payload.workflow_id,
            status=payload.status,
            authorized=payload.authorized,
            binding=payload.binding,
            approvalAuthentication="not-authenticated",
            authority="audit-only",
            execution="not-executed",
        )


class PlanAuthorizationLineageReport(PlanAuthorizationLineageDocumentModel):
    """Read-only reconstruction of matching audit-only authorization facts."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["PlanAuthorizationLineageReport"]
    query: PlanAuthorizationLineageQueryDocument
    match_count: int = Field(alias="matchCount", ge=0, le=CLOUD_EVENTS_INTEGER_MAX)
    matches: tuple[PlanAuthorizationLineageMatch, ...] = Field(
        max_length=MAX_AUTHORIZATION_ENTRIES,
    )
    high_water_sequence: int = Field(
        alias="highWaterSequence",
        ge=0,
        le=CLOUD_EVENTS_INTEGER_MAX,
    )
    approval_authentication: Literal["not-authenticated"] = Field(alias="approvalAuthentication")
    authority: Literal["audit-only"]
    execution: Literal["not-executed"]
    runtime_consumption: Literal["not-consumed"] = Field(alias="runtimeConsumption")
    persistence: Literal["read-only"]
    side_effects: PlanAuthorizationSideEffects = Field(alias="sideEffects")

    @field_validator("matches", mode="before")
    @classmethod
    def freeze_matches(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("lineage matches must be a JSON array")

    @field_serializer("matches")
    def serialize_matches(
        self,
        values: tuple[PlanAuthorizationLineageMatch, ...],
    ) -> list[PlanAuthorizationLineageMatch]:
        return list(values)

    @model_validator(mode="after")
    def reconstruction_is_self_consistent(self) -> Self:
        if self.match_count != len(self.matches):
            raise ValueError("matchCount does not match matches")
        sequences = tuple(item.sequence for item in self.matches)
        if sequences != tuple(sorted(sequences)):
            raise ValueError("matches must be ordered by sequence")
        if len(sequences) != len(set(sequences)):
            raise ValueError("match sequences must be unique")
        event_ids = tuple(item.event_id for item in self.matches)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("match event IDs must be unique")
        if self.matches and self.matches[-1].sequence > self.high_water_sequence:
            raise ValueError("matches must not exceed the frozen high-water sequence")
        return self

    @classmethod
    def from_reconstruction(
        cls,
        query: PlanAuthorizationLineageQueryDocument,
        matches: tuple[PlanAuthorizationLineageMatch, ...],
        *,
        high_water_sequence: int,
    ) -> Self:
        return cls(
            apiVersion=PLAN_AUTHORIZATION_LINEAGE_API_VERSION,
            kind="PlanAuthorizationLineageReport",
            query=query,
            matchCount=len(matches),
            matches=matches,
            highWaterSequence=high_water_sequence,
            approvalAuthentication="not-authenticated",
            authority="audit-only",
            execution="not-executed",
            runtimeConsumption="not-consumed",
            persistence="read-only",
            sideEffects=PlanAuthorizationSideEffects(
                blocksExecuted=0,
                networkRequests=0,
                persistentWrites=0,
                paidActions=0,
            ),
        )


class PlanAuthorizationLineageProjection:
    """Pure fold that collects matching authorization evaluation facts."""

    def __init__(self, query: PlanAuthorizationLineageQueryDocument) -> None:
        self._query = query

    def initial_state(self) -> tuple[PlanAuthorizationLineageMatch, ...]:
        return ()

    def apply(
        self,
        state: tuple[PlanAuthorizationLineageMatch, ...],
        event: ResearchEvent,
    ) -> tuple[PlanAuthorizationLineageMatch, ...]:
        if event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE:
            return state
        try:
            payload = validate_plan_authorization_evaluated_event(event)
        except PlanAuthorizationRecordError:
            raise PlanAuthorizationLineageError("authorization event is invalid") from None
        if not _matches_lineage_query(event, payload, self._query):
            return state
        return (*state, PlanAuthorizationLineageMatch.from_event(event, payload))


def validate_plan_authorization_lineage_query_document(
    document: object,
) -> PlanAuthorizationLineageQueryDocument:
    return PlanAuthorizationLineageQueryDocument.model_validate(document)


def load_plan_authorization_lineage_query(
    path: str | Path,
) -> PlanAuthorizationLineageQueryDocument:
    return validate_plan_authorization_lineage_query_document(
        load_document(path, reject_symlinks=True)
    )


def validate_plan_authorization_lineage_report_document(
    document: object,
) -> PlanAuthorizationLineageReport:
    return PlanAuthorizationLineageReport.model_validate(document)


def query_plan_authorization_lineage(
    store: EventStore,
    query: PlanAuthorizationLineageQueryDocument,
) -> PlanAuthorizationLineageReport:
    """Rebuild matching audit-only authorization facts from a frozen store prefix."""

    snapshot = _validated_lineage_query(query)
    stored = tuple(replay_events(store, freeze_high_water=True))
    matches = fold_events(
        (item.event for item in stored),
        PlanAuthorizationLineageProjection(snapshot),
    )
    high_water = stored[-1].sequence if stored else 0
    return PlanAuthorizationLineageReport.from_reconstruction(
        snapshot,
        matches,
        high_water_sequence=high_water,
    )


def _validated_lineage_query(
    query: PlanAuthorizationLineageQueryDocument,
) -> PlanAuthorizationLineageQueryDocument:
    """Return a detached strict snapshot, including for direct Python callers."""

    if type(query) is not PlanAuthorizationLineageQueryDocument:
        raise PlanAuthorizationLineageError("authorization lineage query is invalid")
    try:
        document = query.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            warnings="error",
        )
        return PlanAuthorizationLineageQueryDocument.model_validate(document)
    except (TypeError, ValueError):
        raise PlanAuthorizationLineageError("authorization lineage query is invalid") from None


def _matches_lineage_query(
    event: ResearchEvent,
    payload: PlanAuthorizationEvaluatedPayload,
    query: PlanAuthorizationLineageQueryDocument,
) -> bool:
    if event.data.project_id != query.project_id:
        return False
    if event.data.experiment_revision != query.experiment_revision:
        return False
    if payload.workflow_id != query.workflow_id:
        return False
    binding = query.binding
    recorded = payload.binding
    if (
        recorded.spec_digest != binding.spec_digest
        or recorded.registry_digest != binding.registry_digest
        or recorded.plan_digest != binding.plan_digest
    ):
        return False
    return binding.decision_digest is None or recorded.decision_digest == binding.decision_digest
