from __future__ import annotations

import builtins
import importlib
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, NoReturn

import pytest

from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution import (
    PlanAuthorizationError,
    PlanAuthorizationPolicy,
    PlanAuthorizationStatus,
    RequirementDecision,
    RequirementDecisionValue,
    TrustedKernel,
    authorize_plan,
)
from llm_research_os.execution.models import DryRunReport, DryRunStatus
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"


def _minimal_report(document: dict[str, Any] | None = None) -> DryRunReport:
    spec = (
        load_spec(EXAMPLES / "valid/minimal.yaml")
        if document is None
        else ResearchSpec.model_validate(document)
    )
    return TrustedKernel(build_registry()).dry_run(spec)


def _bounded_report() -> DryRunReport:
    spec = load_spec(EXAMPLES / "valid/bounded-loop.yaml")
    registry = build_registry([EXAMPLES / "manifests/example-train.yaml"])
    return TrustedKernel(registry).dry_run(spec)


def _policy(
    report: DryRunReport,
    *,
    capabilities: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    decisions: tuple[RequirementDecision, ...] = (),
) -> PlanAuthorizationPolicy:
    assert report.digests.plan is not None
    return PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=capabilities,
        granted_permissions=permissions,
        requirement_decisions=decisions,
    )


def _approval_report(secret_prompt: str = "review this plan") -> DryRunReport:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]
    graph["nodes"] = [
        {
            "kind": "approval",
            "id": "review",
            "requiredRole": "researcher",
            "prompt": secret_prompt,
        }
    ]
    graph["edges"] = []
    return _minimal_report(document)


def _manifest_with_permissions() -> BlockManifest:
    return BlockManifest.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "Block",
            "metadata": {"id": "example.access", "version": "0.1.0"},
            "runtime": {"type": "simulated"},
            "configSchema": {"type": "object", "additionalProperties": False},
            "capabilities": ["z.capability", "a.capability"],
            "permissions": ["write.local", "read.private"],
        }
    )


def _access_report() -> DryRunReport:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    task = document["workflows"][0]["graph"]["nodes"][0]
    task["blockType"] = "example.access"
    task["config"] = {}
    registry = BlockRegistry()
    registry.register(_manifest_with_permissions())
    registry.seal()
    return TrustedKernel(registry).dry_run(ResearchSpec.model_validate(document))


def test_exact_no_requirement_policy_authorizes_ready_plan() -> None:
    report = _minimal_report()
    result = authorize_plan(report, _policy(report, capabilities=("simulate",)))
    assert result.status is PlanAuthorizationStatus.AUTHORIZED
    assert result.authorized is True
    assert result.required_capabilities == ("simulate",)
    assert result.required_permissions == ()
    assert result.missing_capabilities == ()
    assert result.pending_requirements == ()
    assert result.decision_digest.startswith("sha256:")


def test_missing_capability_denies_without_throwing() -> None:
    report = _minimal_report()
    result = authorize_plan(report, _policy(report))
    assert result.status is PlanAuthorizationStatus.DENIED
    assert result.authorized is False
    assert result.missing_capabilities == ("simulate",)


def test_missing_permission_denies_and_access_is_sorted() -> None:
    report = _access_report()
    policy = _policy(
        report,
        capabilities=("z.capability", "a.capability"),
        permissions=("write.local",),
    )
    result = authorize_plan(report, policy)
    assert result.status is PlanAuthorizationStatus.DENIED
    assert result.required_capabilities == ("a.capability", "z.capability")
    assert result.required_permissions == ("read.private", "write.local")
    assert result.missing_permissions == ("read.private",)


def test_missing_requirement_is_pending() -> None:
    report = _approval_report()
    result = authorize_plan(report, _policy(report))
    assert result.status is PlanAuthorizationStatus.PENDING
    assert result.pending_requirements == ("approval:/workflow/workflow.simulation/review",)


def test_explicit_requirement_approval_authorizes() -> None:
    report = _approval_report()
    requirement_id = report.plan.policy_requirements[0].id if report.plan else ""
    result = authorize_plan(
        report,
        _policy(
            report,
            decisions=(RequirementDecision(requirement_id, RequirementDecisionValue.APPROVED),),
        ),
    )
    assert result.status is PlanAuthorizationStatus.AUTHORIZED
    assert result.approved_requirements == (requirement_id,)


def test_explicit_requirement_denial_denies() -> None:
    report = _approval_report()
    requirement_id = report.plan.policy_requirements[0].id if report.plan else ""
    result = authorize_plan(
        report,
        _policy(
            report,
            decisions=(RequirementDecision(requirement_id, RequirementDecisionValue.DENIED),),
        ),
    )
    assert result.status is PlanAuthorizationStatus.DENIED
    assert result.denied_requirements == (requirement_id,)


def test_denial_precedes_other_pending_requirements() -> None:
    report = _bounded_report()
    assert report.plan is not None
    first = report.plan.policy_requirements[0].id
    result = authorize_plan(
        report,
        _policy(
            report,
            capabilities=("train.simulated",),
            decisions=(RequirementDecision(first, RequirementDecisionValue.DENIED),),
        ),
    )
    assert result.status is PlanAuthorizationStatus.DENIED
    assert result.denied_requirements == (first,)
    assert len(result.pending_requirements) == 1


@pytest.mark.parametrize("field", ["spec_digest", "registry_digest", "plan_digest"])
def test_every_digest_must_match(field: str) -> None:
    report = _minimal_report()
    policy = _policy(report, capabilities=("simulate",))
    values = {
        "spec_digest": policy.spec_digest,
        "registry_digest": policy.registry_digest,
        "plan_digest": policy.plan_digest,
        "granted_capabilities": policy.granted_capabilities,
        "granted_permissions": policy.granted_permissions,
        "requirement_decisions": policy.requirement_decisions,
    }
    values[field] = "sha256:" + "0" * 64
    with pytest.raises(PlanAuthorizationError, match="does not match"):
        authorize_plan(report, PlanAuthorizationPolicy(**values))


def test_blocked_report_is_rejected() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    document["workflows"][0]["graph"]["nodes"][0]["blockType"] = "unknown.block"
    report = _minimal_report(document)
    assert report.status is DryRunStatus.BLOCKED
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(PlanAuthorizationError, match="ready plan"):
        authorize_plan(report, policy)


def test_unknown_capability_grant_is_rejected() -> None:
    report = _minimal_report()
    with pytest.raises(PlanAuthorizationError, match="unknown capability"):
        authorize_plan(
            report,
            _policy(report, capabilities=("simulate", "execute.remote")),
        )


def test_unknown_permission_grant_is_rejected() -> None:
    report = _minimal_report()
    with pytest.raises(PlanAuthorizationError, match="unknown permission"):
        authorize_plan(
            report,
            _policy(report, capabilities=("simulate",), permissions=("secret.read",)),
        )


def test_unknown_requirement_decision_is_rejected_without_echo() -> None:
    report = _approval_report()
    secret = "untrusted-secret-requirement"
    policy = _policy(
        report,
        decisions=(RequirementDecision(secret, RequirementDecisionValue.APPROVED),),
    )
    with pytest.raises(PlanAuthorizationError) as captured:
        authorize_plan(report, policy)
    assert "unknown requirement" in str(captured.value)
    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    ("capabilities", "permissions"),
    [
        (("simulate", "simulate"), ()),
        (("simulate",), ("read.private", "read.private")),
    ],
)
def test_duplicate_access_grants_are_rejected(
    capabilities: tuple[str, ...],
    permissions: tuple[str, ...],
) -> None:
    report = _access_report() if permissions else _minimal_report()
    with pytest.raises(PlanAuthorizationError, match="duplicates"):
        authorize_plan(
            report,
            _policy(report, capabilities=capabilities, permissions=permissions),
        )


def test_duplicate_requirement_decisions_are_rejected() -> None:
    report = _approval_report()
    requirement_id = report.plan.policy_requirements[0].id if report.plan else ""
    decision = RequirementDecision(requirement_id, RequirementDecisionValue.APPROVED)
    with pytest.raises(PlanAuthorizationError, match="duplicates"):
        authorize_plan(report, _policy(report, decisions=(decision, decision)))


@pytest.mark.parametrize(
    "policy",
    [
        PlanAuthorizationPolicy("not-a-digest", "sha256:" + "0" * 64, "sha256:" + "0" * 64),
        PlanAuthorizationPolicy(
            "sha256:" + "0" * 64,
            "sha256:" + "0" * 64,
            "sha256:" + "0" * 64,
            granted_capabilities=["simulate"],  # type: ignore[arg-type]
        ),
        PlanAuthorizationPolicy(
            "sha256:" + "0" * 64,
            "sha256:" + "0" * 64,
            "sha256:" + "0" * 64,
            requirement_decisions=(
                RequirementDecision("requirement", "approved"),  # type: ignore[arg-type]
            ),
        ),
    ],
)
def test_malformed_policy_is_rejected(policy: PlanAuthorizationPolicy) -> None:
    with pytest.raises(PlanAuthorizationError, match="invalid"):
        authorize_plan(_minimal_report(), policy)


def test_tampered_report_is_revalidated_before_authorization() -> None:
    report = _minimal_report()
    tampered = report.model_copy(update={"plan": None})
    with pytest.raises(PlanAuthorizationError, match="failed validation"):
        authorize_plan(tampered, _policy(report, capabilities=("simulate",)))


def test_duplicate_plan_requirements_are_rejected_after_valid_digest() -> None:
    report = _approval_report()
    assert report.plan is not None
    requirement = report.plan.policy_requirements[0]
    plan = report.plan.model_copy(update={"policy_requirements": (requirement, requirement)})
    plan_payload = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    plan_payload.pop("specDigest")
    digests = report.digests.model_copy(update={"plan": content_digest(plan_payload)})
    duplicate = report.model_copy(update={"plan": plan, "digests": digests})
    policy = PlanAuthorizationPolicy(
        spec_digest=duplicate.digests.spec,
        registry_digest=duplicate.digests.registry,
        plan_digest=duplicate.digests.plan or "",
    )
    with pytest.raises(PlanAuthorizationError, match="duplicate requirements"):
        authorize_plan(duplicate, policy)


def test_policy_order_does_not_change_result_or_decision_digest() -> None:
    report = _bounded_report()
    assert report.plan is not None
    decisions = tuple(
        RequirementDecision(item.id, RequirementDecisionValue.APPROVED)
        for item in report.plan.policy_requirements
    )
    first = authorize_plan(
        report,
        _policy(report, capabilities=("train.simulated",), decisions=decisions),
    )
    second = authorize_plan(
        report,
        _policy(report, capabilities=("train.simulated",), decisions=tuple(reversed(decisions))),
    )
    assert first == second
    assert first.status is PlanAuthorizationStatus.AUTHORIZED


def test_semantic_plan_change_invalidates_prior_policy_binding() -> None:
    first_report = _minimal_report()
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    document["workflows"][0]["graph"]["nodes"][0]["config"]["seed"] = 1
    second_report = _minimal_report(document)
    assert first_report.digests.plan != second_report.digests.plan
    first_policy = _policy(first_report, capabilities=("simulate",))
    with pytest.raises(PlanAuthorizationError, match="does not match"):
        authorize_plan(second_report, first_policy)
    second = authorize_plan(
        second_report,
        _policy(second_report, capabilities=("simulate",)),
    )
    first = authorize_plan(first_report, first_policy)
    assert first.decision_digest != second.decision_digest


def test_result_is_frozen() -> None:
    report = _minimal_report()
    result = authorize_plan(report, _policy(report, capabilities=("simulate",)))
    with pytest.raises(FrozenInstanceError):
        result.status = PlanAuthorizationStatus.DENIED  # type: ignore[misc]


def test_authorization_never_calls_runtime_or_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _minimal_report()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(os, "system", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(Path, "write_text", tripwire)

    result = authorize_plan(report, _policy(report, capabilities=("simulate",)))
    assert result.status is PlanAuthorizationStatus.AUTHORIZED


def test_prompt_and_config_values_never_enter_authorization_result() -> None:
    secret_prompt = "secret-approval-prompt-value"
    report = _approval_report(secret_prompt)
    result = authorize_plan(report, _policy(report))
    rendered = repr(result)
    assert secret_prompt not in rendered
    assert "review this plan" not in rendered
