"""Strict request and append boundary for plan-authorization evaluation facts.

The existing authorization evaluator remains pure.  This module can persist one
caller-identified ``plan.authorization.evaluated`` audit fact after recomputing
the exact decision and verifying the complete EventStore.  The fact is explicitly
unauthenticated and audit-only; it is not a runtime launch credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from llm_research_os.events.models import (
    RESEARCH_EVENT_SCHEMA_ID,
    CloudEventsString,
    CloudEventsUriReference,
    EventDocumentModel,
    EventIdentifier,
    ExperimentRevision,
    ResearchEvent,
    Rfc3339Timestamp,
)
from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    authorize_plan,
)
from llm_research_os.execution.authorization_documents import (
    MAX_AUTHORIZATION_ENTRIES,
    PLAN_AUTHORIZATION_API_VERSION,
    AuthorizationDigest,
    AuthorizationIdentifier,
    AuthorizationRequirementId,
    PlanAuthorizationReport,
)
from llm_research_os.execution.errors import PlanAuthorizationRecordError
from llm_research_os.execution.models import DryRunReport
from llm_research_os.spec.io import load_document
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

PLAN_AUTHORIZATION_EVENT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/plan-authorization-event-request/v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_EVENT_API_VERSION: Literal["researchos.dev/v0alpha1"] = "researchos.dev/v0alpha1"
PLAN_AUTHORIZATION_EVALUATED_TYPE: Literal["plan.authorization.evaluated"] = (
    "plan.authorization.evaluated"
)


class PlanAuthorizationEventDocumentModel(EventDocumentModel):
    """Frozen alias-only event input with no coercion or repair."""

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


class PlanAuthorizationEventActor(PlanAuthorizationEventDocumentModel):
    """Caller-asserted actor identity; this is not authentication."""

    id: EventIdentifier


class PlanAuthorizationEventIdentity(PlanAuthorizationEventDocumentModel):
    """Caller-owned CloudEvents identity for the one appended fact."""

    id: CloudEventsString
    time: Rfc3339Timestamp


class PlanAuthorizationEventBinding(PlanAuthorizationEventDocumentModel):
    """Exact plan and recomputed decision identity."""

    spec_digest: AuthorizationDigest = Field(alias="specDigest")
    registry_digest: AuthorizationDigest = Field(alias="registryDigest")
    plan_digest: AuthorizationDigest = Field(alias="planDigest")
    decision_digest: AuthorizationDigest = Field(alias="decisionDigest")


class PlanAuthorizationEvaluatedPayload(PlanAuthorizationEventDocumentModel):
    """Closed domain payload for ``plan.authorization.evaluated``."""

    workflow_id: EventIdentifier = Field(alias="workflowId")
    binding: PlanAuthorizationEventBinding
    status: PlanAuthorizationStatus = Field(strict=False)
    authorized: bool
    required_capabilities: tuple[AuthorizationIdentifier, ...] = Field(
        alias="requiredCapabilities",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    required_permissions: tuple[AuthorizationIdentifier, ...] = Field(
        alias="requiredPermissions",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    missing_capabilities: tuple[AuthorizationIdentifier, ...] = Field(
        alias="missingCapabilities",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    missing_permissions: tuple[AuthorizationIdentifier, ...] = Field(
        alias="missingPermissions",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    approved_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="approvedRequirements",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    pending_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="pendingRequirements",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    denied_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="deniedRequirements",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    approval_authentication: Literal["not-authenticated"] = Field(alias="approvalAuthentication")
    authority: Literal["audit-only"]
    execution: Literal["not-executed"]

    @field_validator(
        "required_capabilities",
        "required_permissions",
        "missing_capabilities",
        "missing_permissions",
        "approved_requirements",
        "pending_requirements",
        "denied_requirements",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("authorization event collections must be arrays")

    @field_serializer(
        "required_capabilities",
        "required_permissions",
        "missing_capabilities",
        "missing_permissions",
        "approved_requirements",
        "pending_requirements",
        "denied_requirements",
    )
    def serialize_collections(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @model_validator(mode="after")
    def decision_is_self_consistent(self) -> Self:
        PlanAuthorizationReport.model_validate(
            {
                "apiVersion": PLAN_AUTHORIZATION_API_VERSION,
                "kind": "PlanAuthorizationReport",
                "status": self.status,
                "authorized": self.authorized,
                "binding": {
                    "specDigest": self.binding.spec_digest,
                    "registryDigest": self.binding.registry_digest,
                    "planDigest": self.binding.plan_digest,
                },
                "decisionDigest": self.binding.decision_digest,
                "requiredCapabilities": list(self.required_capabilities),
                "requiredPermissions": list(self.required_permissions),
                "missingCapabilities": list(self.missing_capabilities),
                "missingPermissions": list(self.missing_permissions),
                "approvedRequirements": list(self.approved_requirements),
                "pendingRequirements": list(self.pending_requirements),
                "deniedRequirements": list(self.denied_requirements),
                "approvalAuthentication": "not-authenticated",
                "persistence": "not-persisted",
                "execution": "not-executed",
                "sideEffects": {
                    "blocksExecuted": 0,
                    "networkRequests": 0,
                    "persistentWrites": 0,
                    "paidActions": 0,
                },
            }
        )
        return self

    @classmethod
    def from_result(
        cls,
        result: PlanAuthorizationResult,
        *,
        workflow_id: str,
    ) -> PlanAuthorizationEvaluatedPayload:
        return cls(
            workflowId=workflow_id,
            binding=PlanAuthorizationEventBinding(
                specDigest=result.spec_digest,
                registryDigest=result.registry_digest,
                planDigest=result.plan_digest,
                decisionDigest=result.decision_digest,
            ),
            status=result.status,
            authorized=result.authorized,
            requiredCapabilities=result.required_capabilities,
            requiredPermissions=result.required_permissions,
            missingCapabilities=result.missing_capabilities,
            missingPermissions=result.missing_permissions,
            approvedRequirements=result.approved_requirements,
            pendingRequirements=result.pending_requirements,
            deniedRequirements=result.denied_requirements,
            approvalAuthentication="not-authenticated",
            authority="audit-only",
            execution="not-executed",
        )


class PlanAuthorizationEventRequestDocument(PlanAuthorizationEventDocumentModel):
    """Caller-owned identity and exact binding for one evaluation audit fact."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["PlanAuthorizationEventRequest"]
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    workflow_id: EventIdentifier = Field(alias="workflowId")
    binding: PlanAuthorizationEventBinding
    source: CloudEventsUriReference
    subject: CloudEventsString
    stream_id: EventIdentifier = Field(alias="streamid")
    actor: PlanAuthorizationEventActor
    event: PlanAuthorizationEventIdentity
    evidence_refs: tuple[EventIdentifier, ...] = Field(
        alias="evidenceRefs",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def freeze_evidence_refs(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("evidenceRefs must be a JSON array")
        return tuple(value)

    @field_serializer("evidence_refs")
    def serialize_evidence_refs(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self

    def event_draft(self, result: PlanAuthorizationResult) -> dict[str, Any]:
        """Build an isolated ResearchEvent draft from the recomputed result."""

        payload = PlanAuthorizationEvaluatedPayload.from_result(
            result,
            workflow_id=self.workflow_id,
        )
        return {
            "specversion": "1.0",
            "id": self.event.id,
            "source": self.source,
            "type": PLAN_AUTHORIZATION_EVALUATED_TYPE,
            "time": self.event.time,
            "subject": self.subject,
            "dataschema": RESEARCH_EVENT_SCHEMA_ID,
            "datacontenttype": "application/json",
            "streamid": self.stream_id,
            "data": {
                "schemaVersion": "v0alpha1",
                "actor": {"id": self.actor.id, "kind": "human"},  # asserted, not authenticated
                "projectId": self.project_id,
                "experimentRevision": self.experiment_revision,
                "payload": payload.model_dump(mode="json", by_alias=True),
                "evidenceRefs": list(self.evidence_refs),
            },
        }


@dataclass(frozen=True, slots=True)
class PlanAuthorizationEventRecordResult:
    """One recomputed decision and its committed audit fact."""

    authorization: PlanAuthorizationResult
    stored: StoredEvent


def validate_plan_authorization_event_request_document(
    document: object,
) -> PlanAuthorizationEventRequestDocument:
    return PlanAuthorizationEventRequestDocument.model_validate(document)


def load_plan_authorization_event_request(
    path: str | Path,
) -> PlanAuthorizationEventRequestDocument:
    return validate_plan_authorization_event_request_document(
        load_document(path, reject_symlinks=True)
    )


def validate_plan_authorization_evaluated_event(
    event: ResearchEvent,
) -> PlanAuthorizationEvaluatedPayload:
    """Validate the domain semantics of one stored evaluation event."""

    if type(event) is not ResearchEvent:
        raise PlanAuthorizationRecordError("authorization event is invalid")
    if event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE:
        raise PlanAuthorizationRecordError("authorization event type is invalid")
    if (
        event.data.run_id is not None
        or event.data.attempt_id is not None
        or event.data.block_id is not None
    ):
        raise PlanAuthorizationRecordError("authorization event aggregate scope is invalid")
    try:
        return PlanAuthorizationEvaluatedPayload.model_validate(event.data.payload)
    except ValueError:
        raise PlanAuthorizationRecordError("authorization event payload is invalid") from None


def _validated_event_request(
    request: PlanAuthorizationEventRequestDocument,
) -> PlanAuthorizationEventRequestDocument:
    """Return a detached strict snapshot, including for direct Python callers."""

    if type(request) is not PlanAuthorizationEventRequestDocument:
        raise PlanAuthorizationRecordError("authorization event request is invalid")
    try:
        document = request.model_dump(
            mode="json",
            by_alias=True,
            warnings="error",
        )
        return PlanAuthorizationEventRequestDocument.model_validate(document)
    except (TypeError, ValueError):
        raise PlanAuthorizationRecordError("authorization event request is invalid") from None


def record_plan_authorization_event(
    store: EventStore,
    report: DryRunReport,
    policy: PlanAuthorizationPolicy,
    request: PlanAuthorizationEventRequestDocument,
) -> PlanAuthorizationEventRecordResult:
    """Recompute and CAS-append one audit-only authorization evaluation fact."""

    snapshot = _validated_event_request(request)
    result = authorize_plan(report, policy)
    binding = snapshot.binding
    if (
        binding.spec_digest != result.spec_digest
        or binding.registry_digest != result.registry_digest
        or binding.plan_digest != result.plan_digest
        or binding.decision_digest != result.decision_digest
    ):
        raise PlanAuthorizationRecordError(
            "authorization event request does not match the recomputed decision"
        )
    if (
        snapshot.project_id != report.project.id
        or snapshot.experiment_revision != report.project.revision
        or snapshot.workflow_id != report.workflow_id
    ):
        raise PlanAuthorizationRecordError(
            "authorization event request does not match the planned revision"
        )

    draft = snapshot.event_draft(result)
    preflight_document = dict(draft)
    preflight_document.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
    try:
        preflight_event = ResearchEvent.model_validate(preflight_document)
    except ValueError:
        raise PlanAuthorizationRecordError("authorization event draft is invalid") from None
    validate_plan_authorization_evaluated_event(preflight_event)
    frozen_head = store.freeze_high_water()
    stored = store.append(draft, expected_last_sequence=frozen_head)
    validate_plan_authorization_evaluated_event(stored.event)
    return PlanAuthorizationEventRecordResult(authorization=result, stored=stored)
