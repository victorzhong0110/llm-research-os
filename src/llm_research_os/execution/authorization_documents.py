"""Strict external documents for deterministic plan-authorization evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    RequirementDecision,
    RequirementDecisionValue,
)
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import StrictModel

PLAN_AUTHORIZATION_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/plan-authorization-request/v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_REPORT_SCHEMA_ID = (
    "https://researchos.dev/schemas/plan-authorization-report/v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_API_VERSION: Literal["researchos.dev/v0alpha1"] = "researchos.dev/v0alpha1"
MAX_AUTHORIZATION_ENTRIES = 10_000

AuthorizationDigest = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=SEMANTIC_DIGEST_PATTERN,
    ),
]
AuthorizationIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
AuthorizationRequirementId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        min_length=1,
        max_length=4096,
    ),
]


class PlanAuthorizationDocumentModel(StrictModel):
    """Frozen alias-only external model with no coercion or whitespace repair."""

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


class RequirementDecisionDocument(PlanAuthorizationDocumentModel):
    """One caller-asserted disposition for an exact planner requirement."""

    requirement_id: AuthorizationRequirementId = Field(alias="requirementId")
    decision: RequirementDecisionValue = Field(strict=False)


class PlanAuthorizationRequestDocument(PlanAuthorizationDocumentModel):
    """Versioned, caller-owned policy input for one exact planned graph."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["PlanAuthorizationRequest"]
    spec_digest: AuthorizationDigest = Field(alias="specDigest")
    registry_digest: AuthorizationDigest = Field(alias="registryDigest")
    plan_digest: AuthorizationDigest = Field(alias="planDigest")
    granted_capabilities: tuple[AuthorizationIdentifier, ...] = Field(
        alias="grantedCapabilities",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    granted_permissions: tuple[AuthorizationIdentifier, ...] = Field(
        alias="grantedPermissions",
        max_length=MAX_AUTHORIZATION_ENTRIES,
        json_schema_extra={"uniqueItems": True},
    )
    requirement_decisions: tuple[RequirementDecisionDocument, ...] = Field(
        alias="requirementDecisions",
        max_length=MAX_AUTHORIZATION_ENTRIES,
    )

    @field_validator(
        "granted_capabilities",
        "granted_permissions",
        "requirement_decisions",
        mode="before",
    )
    @classmethod
    def freeze_json_arrays(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("authorization collections must be JSON arrays")
        return tuple(value)

    @model_validator(mode="after")
    def entries_are_unique(self) -> Self:
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise ValueError("grantedCapabilities entries must be unique")
        if len(self.granted_permissions) != len(set(self.granted_permissions)):
            raise ValueError("grantedPermissions entries must be unique")
        requirement_ids = tuple(item.requirement_id for item in self.requirement_decisions)
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirementDecisions requirementId entries must be unique")
        return self

    @field_serializer("granted_capabilities", "granted_permissions")
    def serialize_identifiers(self, values: tuple[str, ...]) -> list[str]:
        return list(values)

    @field_serializer("requirement_decisions")
    def serialize_decisions(
        self,
        values: tuple[RequirementDecisionDocument, ...],
    ) -> list[RequirementDecisionDocument]:
        return list(values)

    def policy(self) -> PlanAuthorizationPolicy:
        """Return an isolated in-process policy without adding authority."""

        return PlanAuthorizationPolicy(
            spec_digest=self.spec_digest,
            registry_digest=self.registry_digest,
            plan_digest=self.plan_digest,
            granted_capabilities=tuple(self.granted_capabilities),
            granted_permissions=tuple(self.granted_permissions),
            requirement_decisions=tuple(
                RequirementDecision(item.requirement_id, item.decision)
                for item in self.requirement_decisions
            ),
        )


class PlanAuthorizationBinding(PlanAuthorizationDocumentModel):
    """Exact immutable identity of the evaluated plan."""

    spec_digest: AuthorizationDigest = Field(alias="specDigest")
    registry_digest: AuthorizationDigest = Field(alias="registryDigest")
    plan_digest: AuthorizationDigest = Field(alias="planDigest")


class PlanAuthorizationSideEffects(PlanAuthorizationDocumentModel):
    """Literal zero-effect declaration for this evaluation command."""

    blocks_executed: Literal[0] = Field(alias="blocksExecuted")
    network_requests: Literal[0] = Field(alias="networkRequests")
    persistent_writes: Literal[0] = Field(alias="persistentWrites")
    paid_actions: Literal[0] = Field(alias="paidActions")


class PlanAuthorizationReport(PlanAuthorizationDocumentModel):
    """Normalized evaluation report that is explicitly not an authority receipt."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["PlanAuthorizationReport"]
    status: PlanAuthorizationStatus = Field(strict=False)
    authorized: bool
    binding: PlanAuthorizationBinding
    decision_digest: AuthorizationDigest = Field(alias="decisionDigest")
    required_capabilities: tuple[AuthorizationIdentifier, ...] = Field(
        alias="requiredCapabilities",
        json_schema_extra={"uniqueItems": True},
    )
    required_permissions: tuple[AuthorizationIdentifier, ...] = Field(
        alias="requiredPermissions",
        json_schema_extra={"uniqueItems": True},
    )
    missing_capabilities: tuple[AuthorizationIdentifier, ...] = Field(
        alias="missingCapabilities",
        json_schema_extra={"uniqueItems": True},
    )
    missing_permissions: tuple[AuthorizationIdentifier, ...] = Field(
        alias="missingPermissions",
        json_schema_extra={"uniqueItems": True},
    )
    approved_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="approvedRequirements",
        json_schema_extra={"uniqueItems": True},
    )
    pending_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="pendingRequirements",
        json_schema_extra={"uniqueItems": True},
    )
    denied_requirements: tuple[AuthorizationRequirementId, ...] = Field(
        alias="deniedRequirements",
        json_schema_extra={"uniqueItems": True},
    )
    approval_authentication: Literal["not-authenticated"] = Field(alias="approvalAuthentication")
    persistence: Literal["not-persisted"]
    execution: Literal["not-executed"]
    side_effects: PlanAuthorizationSideEffects = Field(alias="sideEffects")

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
    def freeze_json_arrays(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("authorization report collections must be arrays")

    @model_validator(mode="after")
    def result_is_normalized_and_self_consistent(self) -> Self:
        collections = (
            self.required_capabilities,
            self.required_permissions,
            self.missing_capabilities,
            self.missing_permissions,
            self.approved_requirements,
            self.pending_requirements,
            self.denied_requirements,
        )
        if any(tuple(sorted(values)) != values for values in collections):
            raise ValueError("authorization report collections must be sorted")
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("authorization report collections must be unique")
        if not set(self.missing_capabilities).issubset(self.required_capabilities):
            raise ValueError("missingCapabilities must be required")
        if not set(self.missing_permissions).issubset(self.required_permissions):
            raise ValueError("missingPermissions must be required")
        approved = set(self.approved_requirements)
        pending = set(self.pending_requirements)
        denied = set(self.denied_requirements)
        if (
            approved.intersection(pending)
            or approved.intersection(denied)
            or pending.intersection(denied)
        ):
            raise ValueError("authorization requirement dispositions must be disjoint")

        expected_authorized = self.status is PlanAuthorizationStatus.AUTHORIZED
        if self.authorized is not expected_authorized:
            raise ValueError("authorized must match status")
        has_denial = bool(
            self.missing_capabilities or self.missing_permissions or self.denied_requirements
        )
        if self.status is PlanAuthorizationStatus.AUTHORIZED and (has_denial or pending):
            raise ValueError("authorized reports cannot contain unresolved requirements")
        if self.status is PlanAuthorizationStatus.PENDING and (has_denial or not pending):
            raise ValueError("pending reports require only unresolved requirements")
        if self.status is PlanAuthorizationStatus.DENIED and not has_denial:
            raise ValueError("denied reports require a denial reason")
        if self.decision_digest != content_digest(self._decision_payload()):
            raise ValueError("decisionDigest does not match the authorization report")
        return self

    def _decision_payload(self) -> dict[str, object]:
        missing_capabilities = set(self.missing_capabilities)
        missing_permissions = set(self.missing_permissions)
        decisions = {
            **{value: "approved" for value in self.approved_requirements},
            **{value: "pending" for value in self.pending_requirements},
            **{value: "denied" for value in self.denied_requirements},
        }
        return {
            "status": self.status.value,
            "digests": {
                "spec": self.binding.spec_digest,
                "registry": self.binding.registry_digest,
                "plan": self.binding.plan_digest,
            },
            "capabilities": [
                {
                    "id": value,
                    "decision": "missing" if value in missing_capabilities else "granted",
                }
                for value in self.required_capabilities
            ],
            "permissions": [
                {
                    "id": value,
                    "decision": "missing" if value in missing_permissions else "granted",
                }
                for value in self.required_permissions
            ],
            "requirements": [
                {"id": requirement_id, "decision": decisions[requirement_id]}
                for requirement_id in sorted(decisions)
            ],
        }

    @classmethod
    def from_result(cls, result: PlanAuthorizationResult) -> PlanAuthorizationReport:
        """Build the external report from one immutable trusted-kernel result."""

        return cls(
            apiVersion=PLAN_AUTHORIZATION_API_VERSION,
            kind="PlanAuthorizationReport",
            status=result.status,
            authorized=result.authorized,
            binding=PlanAuthorizationBinding(
                specDigest=result.spec_digest,
                registryDigest=result.registry_digest,
                planDigest=result.plan_digest,
            ),
            decisionDigest=result.decision_digest,
            requiredCapabilities=result.required_capabilities,
            requiredPermissions=result.required_permissions,
            missingCapabilities=result.missing_capabilities,
            missingPermissions=result.missing_permissions,
            approvedRequirements=result.approved_requirements,
            pendingRequirements=result.pending_requirements,
            deniedRequirements=result.denied_requirements,
            approvalAuthentication="not-authenticated",
            persistence="not-persisted",
            execution="not-executed",
            sideEffects=PlanAuthorizationSideEffects(
                blocksExecuted=0,
                networkRequests=0,
                persistentWrites=0,
                paidActions=0,
            ),
        )


def validate_plan_authorization_request_document(
    document: object,
) -> PlanAuthorizationRequestDocument:
    """Validate an already-decoded external authorization request."""

    return PlanAuthorizationRequestDocument.model_validate(document)


def load_plan_authorization_request(
    path: str | Path,
) -> PlanAuthorizationRequestDocument:
    """Load a local request while rejecting duplicate keys, aliases and symlinks."""

    return validate_plan_authorization_request_document(load_document(path, reject_symlinks=True))
