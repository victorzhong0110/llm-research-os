"""Pure deterministic authorization gate for one exact ready execution plan.

The gate evaluates inert policy input only.  It does not authenticate an actor,
persist a decision, emit an event, invoke a runtime, or grant an operating-system
capability.  A consumer must bind the returned decision to all three plan digests
and must refuse every result except ``authorized`` before execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.execution.errors import PlanAuthorizationError
from llm_research_os.execution.models import (
    DryRunReport,
    DryRunStatus,
    PlannedGraph,
    PlannedLoop,
    PlannedTask,
)

_DIGEST_PATTERN = re.compile(SEMANTIC_DIGEST_PATTERN)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RequirementDecisionValue(StrEnum):
    """Explicit decision for one planner-emitted policy requirement."""

    APPROVED = "approved"
    DENIED = "denied"


class PlanAuthorizationStatus(StrEnum):
    """Outcome of evaluating one policy input against one exact plan."""

    AUTHORIZED = "authorized"
    PENDING = "pending"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class RequirementDecision:
    """Caller-owned decision for one exact planner requirement id."""

    requirement_id: str
    decision: RequirementDecisionValue


@dataclass(frozen=True, slots=True)
class PlanAuthorizationPolicy:
    """Least-privilege policy input bound to an exact dry-run digest triple.

    Capability and permission grants may contain only values required by this
    plan.  Requirement decisions may contain only planner-emitted requirement
    ids.  This rejects stale, misspelled, or accidentally widened inputs instead
    of silently ignoring them.
    """

    spec_digest: str
    registry_digest: str
    plan_digest: str
    granted_capabilities: tuple[str, ...] = ()
    granted_permissions: tuple[str, ...] = ()
    requirement_decisions: tuple[RequirementDecision, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanAuthorizationResult:
    """Immutable, deterministic decision without authority outside this process."""

    status: PlanAuthorizationStatus
    spec_digest: str
    registry_digest: str
    plan_digest: str
    decision_digest: str
    required_capabilities: tuple[str, ...]
    required_permissions: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    missing_permissions: tuple[str, ...]
    approved_requirements: tuple[str, ...]
    pending_requirements: tuple[str, ...]
    denied_requirements: tuple[str, ...]

    @property
    def authorized(self) -> bool:
        """Return true only for the one executable authorization disposition."""

        return self.status is PlanAuthorizationStatus.AUTHORIZED


def authorize_plan(
    report: DryRunReport,
    policy: PlanAuthorizationPolicy,
) -> PlanAuthorizationResult:
    """Evaluate explicit grants and decisions against one defensively revalidated plan.

    Invalid input raises :class:`PlanAuthorizationError`.  Valid but insufficient
    policy returns ``pending`` or ``denied`` and never raises merely because a
    decision was negative.
    """

    snapshot = _validated_ready_report(report)
    plan = snapshot.plan
    if plan is None or snapshot.digests.plan is None:
        raise PlanAuthorizationError("authorization requires a complete ready plan")
    _validate_policy_shape(policy)
    granted_capabilities = _validated_unique_identifiers(
        policy.granted_capabilities,
        label="capability grants",
    )
    granted_permissions = _validated_unique_identifiers(
        policy.granted_permissions,
        label="permission grants",
    )
    granted_capability_set = set(granted_capabilities)
    granted_permission_set = set(granted_permissions)
    decisions = _validated_decisions(policy.requirement_decisions)
    if (
        policy.spec_digest != snapshot.digests.spec
        or policy.registry_digest != snapshot.digests.registry
        or policy.plan_digest != snapshot.digests.plan
    ):
        raise PlanAuthorizationError("authorization policy does not match the plan binding")

    required_capabilities, required_permissions = _declared_access(plan.graph)
    requirement_ids = tuple(item.id for item in plan.policy_requirements)
    if len(requirement_ids) != len(set(requirement_ids)):
        raise PlanAuthorizationError("authorization plan contains duplicate requirements")

    if not granted_capability_set.issubset(required_capabilities):
        raise PlanAuthorizationError("authorization policy contains an unknown capability grant")
    if not granted_permission_set.issubset(required_permissions):
        raise PlanAuthorizationError("authorization policy contains an unknown permission grant")

    if not set(decisions).issubset(requirement_ids):
        raise PlanAuthorizationError(
            "authorization policy contains an unknown requirement decision"
        )

    missing_capabilities = tuple(sorted(required_capabilities.difference(granted_capability_set)))
    missing_permissions = tuple(sorted(required_permissions.difference(granted_permission_set)))
    approved_requirements = tuple(
        requirement_id
        for requirement_id in sorted(requirement_ids)
        if decisions.get(requirement_id) is RequirementDecisionValue.APPROVED
    )
    denied_requirements = tuple(
        requirement_id
        for requirement_id in sorted(requirement_ids)
        if decisions.get(requirement_id) is RequirementDecisionValue.DENIED
    )
    pending_requirements = tuple(
        requirement_id
        for requirement_id in sorted(requirement_ids)
        if requirement_id not in decisions
    )

    if missing_capabilities or missing_permissions or denied_requirements:
        status = PlanAuthorizationStatus.DENIED
    elif pending_requirements:
        status = PlanAuthorizationStatus.PENDING
    else:
        status = PlanAuthorizationStatus.AUTHORIZED

    decision_payload: dict[str, Any] = {
        "status": status.value,
        "digests": {
            "spec": snapshot.digests.spec,
            "registry": snapshot.digests.registry,
            "plan": snapshot.digests.plan,
        },
        "capabilities": [
            {
                "id": value,
                "decision": "granted" if value in granted_capability_set else "missing",
            }
            for value in sorted(required_capabilities)
        ],
        "permissions": [
            {
                "id": value,
                "decision": "granted" if value in granted_permission_set else "missing",
            }
            for value in sorted(required_permissions)
        ],
        "requirements": [
            {
                "id": requirement_id,
                "decision": (
                    decisions[requirement_id].value if requirement_id in decisions else "pending"
                ),
            }
            for requirement_id in sorted(requirement_ids)
        ],
    }
    return PlanAuthorizationResult(
        status=status,
        spec_digest=snapshot.digests.spec,
        registry_digest=snapshot.digests.registry,
        plan_digest=snapshot.digests.plan,
        decision_digest=content_digest(decision_payload),
        required_capabilities=tuple(sorted(required_capabilities)),
        required_permissions=tuple(sorted(required_permissions)),
        missing_capabilities=missing_capabilities,
        missing_permissions=missing_permissions,
        approved_requirements=approved_requirements,
        pending_requirements=pending_requirements,
        denied_requirements=denied_requirements,
    )


def _validated_ready_report(report: DryRunReport) -> DryRunReport:
    if type(report) is not DryRunReport:
        raise PlanAuthorizationError("authorization requires a validated dry-run report")
    try:
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        snapshot = DryRunReport.model_validate(payload)
    except (TypeError, ValueError):
        raise PlanAuthorizationError("authorization dry-run report failed validation") from None
    if snapshot.status is not DryRunStatus.READY:
        raise PlanAuthorizationError("authorization requires a complete ready plan")
    return snapshot


def _validate_policy_shape(policy: PlanAuthorizationPolicy) -> None:
    if type(policy) is not PlanAuthorizationPolicy:
        raise PlanAuthorizationError("authorization policy has an invalid shape")
    for digest in (policy.spec_digest, policy.registry_digest, policy.plan_digest):
        if type(digest) is not str or _DIGEST_PATTERN.fullmatch(digest) is None:
            raise PlanAuthorizationError("authorization policy contains an invalid digest")
    if (
        type(policy.granted_capabilities) is not tuple
        or type(policy.granted_permissions) is not tuple
        or type(policy.requirement_decisions) is not tuple
    ):
        raise PlanAuthorizationError("authorization policy has an invalid shape")


def _validated_unique_identifiers(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    for value in values:
        if type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise PlanAuthorizationError(f"authorization {label} are invalid")
    if len(values) != len(set(values)):
        raise PlanAuthorizationError(f"authorization {label} contain duplicates")
    return values


def _validated_decisions(
    values: tuple[RequirementDecision, ...],
) -> dict[str, RequirementDecisionValue]:
    decisions: dict[str, RequirementDecisionValue] = {}
    for value in values:
        if (
            type(value) is not RequirementDecision
            or type(value.requirement_id) is not str
            or not value.requirement_id
            or type(value.decision) is not RequirementDecisionValue
        ):
            raise PlanAuthorizationError("authorization requirement decisions are invalid")
        if value.requirement_id in decisions:
            raise PlanAuthorizationError("authorization requirement decisions contain duplicates")
        decisions[value.requirement_id] = value.decision
    return decisions


def _declared_access(graph: PlannedGraph) -> tuple[set[str], set[str]]:
    capabilities: set[str] = set()
    permissions: set[str] = set()
    pending = [graph]
    while pending:
        current = pending.pop()
        for stage in current.stages:
            for node in stage.nodes:
                if isinstance(node, PlannedTask):
                    capabilities.update(node.declared_capabilities)
                    permissions.update(node.declared_permissions)
                elif isinstance(node, PlannedLoop):
                    pending.append(node.body)
    return capabilities, permissions
