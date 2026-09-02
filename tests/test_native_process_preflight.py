from __future__ import annotations

import builtins
import importlib
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, NoReturn

import pytest

from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.execution import (
    MAX_NATIVE_TASK_PATH_ITEMS,
    NativeProcessLimits,
    NativeProcessPreflightError,
    NativeProcessPreflightPolicy,
    PlanAuthorizationPolicy,
    TrustedKernel,
    authorize_plan,
    preflight_native_process,
)
from llm_research_os.execution.models import DryRunReport, DryRunStatus
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "native-process-preflight" / "spec.yaml"
MANIFEST = ROOT / "examples" / "native-process-preflight" / "manifest.yaml"
ZERO_DIGEST = "sha256:" + "0" * 64


def _case(
    *,
    manifest_document: dict[str, Any] | None = None,
    spec_document: dict[str, Any] | None = None,
) -> tuple[
    BlockRegistry,
    DryRunReport,
    PlanAuthorizationPolicy,
    NativeProcessPreflightPolicy,
]:
    manifest = BlockManifest.model_validate(manifest_document or load_document(MANIFEST))
    registry = BlockRegistry()
    for builtin in builtin_manifests():
        registry.register(builtin, source="builtin")
    registry.register(manifest)
    registry.seal()
    spec = ResearchSpec.model_validate(spec_document or load_document(SPEC))
    report = TrustedKernel(registry).dry_run(spec)
    assert report.status is DryRunStatus.READY
    assert report.digests.plan is not None
    authorization_policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=tuple(sorted(manifest.capabilities)),
        granted_permissions=tuple(sorted(manifest.permissions)),
    )
    authorization = authorize_plan(report, authorization_policy)
    policy = NativeProcessPreflightPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        authorization_decision_digest=authorization.decision_digest,
        task_path=("workflow", "workflow.native", "invoke"),
        runner="researchos.python-worker/v0alpha1",
        shell=False,
        network="denied",
        workspace="isolated-temporary",
        environment_allowlist=(),
        limits=NativeProcessLimits(
            wall_time_seconds=30,
            stdout_bytes=1_048_576,
            stderr_bytes=1_048_576,
            termination_grace_seconds=5,
        ),
    )
    return registry, report, authorization_policy, policy


def test_exact_authorized_python_task_produces_deterministic_nonlaunchable_review() -> None:
    registry, report, authorization, policy = _case()
    first = preflight_native_process(report, registry, authorization, policy)
    second = preflight_native_process(report, registry, authorization, policy)
    assert first == second
    assert first.preflight_digest == (
        "jcs-sha256:040f5679d7ac79cf47c805f960e0d5a568812ef6cf5d2e3465314be138f708e5"
    )
    assert first.authorization_decision_digest == (
        "jcs-sha256:c2300636d18d76bd04f65ad9ef77584357bf841a90cfb50beb18c11af64283d9"
    )
    assert first.entrypoint_digest == (
        "jcs-sha256:8f822a565015929babf03c87864bb35df11ebe6206567211c15967673efa7501"
    )
    assert "example_native_worker:run" not in repr(first)


def test_result_is_frozen() -> None:
    registry, report, authorization, policy = _case()
    result = preflight_native_process(report, registry, authorization, policy)
    with pytest.raises(FrozenInstanceError):
        result.preflight_digest = ZERO_DIGEST  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    (
        "spec_digest",
        "registry_digest",
        "plan_digest",
        "authorization_decision_digest",
    ),
)
def test_every_preflight_binding_digest_must_match(field: str) -> None:
    registry, report, authorization, policy = _case()
    with pytest.raises(NativeProcessPreflightError, match="authorization binding"):
        preflight_native_process(
            report,
            registry,
            authorization,
            replace(policy, **{field: ZERO_DIGEST}),
        )


def test_missing_capability_and_stale_authorization_fail_closed() -> None:
    registry, report, authorization, policy = _case()
    denied = replace(authorization, granted_capabilities=())
    with pytest.raises(NativeProcessPreflightError, match="authorized exact plan"):
        preflight_native_process(report, registry, denied, policy)

    stale = replace(authorization, plan_digest=ZERO_DIGEST)
    with pytest.raises(NativeProcessPreflightError, match="authorization failed"):
        preflight_native_process(report, registry, stale, policy)


def test_registry_must_be_exact_and_sealed() -> None:
    registry, report, authorization, policy = _case()
    unsealed = BlockRegistry()
    for builtin in builtin_manifests():
        unsealed.register(builtin, source="builtin")
    unsealed.register(BlockManifest.model_validate(load_document(MANIFEST)))
    with pytest.raises(NativeProcessPreflightError, match="sealed registry"):
        preflight_native_process(report, unsealed, authorization, policy)

    with pytest.raises(NativeProcessPreflightError, match="registry does not match"):
        preflight_native_process(report, build_registry(), authorization, policy)
    assert registry.sealed


def test_task_selection_and_single_task_shape_are_exact() -> None:
    registry, report, authorization, policy = _case()
    with pytest.raises(NativeProcessPreflightError, match="task selection"):
        preflight_native_process(
            report,
            registry,
            authorization,
            replace(policy, task_path=("workflow", "workflow.native", "other")),
        )

    document = load_document(SPEC)
    second = dict(document["workflows"][0]["graph"]["nodes"][0])
    second["id"] = "invoke.second"
    document["workflows"][0]["graph"]["nodes"].append(second)
    registry, report, authorization, policy = _case(spec_document=document)
    with pytest.raises(NativeProcessPreflightError, match="isolated single-task plan"):
        preflight_native_process(report, registry, authorization, policy)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda value: value.__setitem__("runtime", {"type": "simulated"}),
            "exact Python manifest",
        ),
        (
            lambda value: value.__setitem__(
                "capabilities", ["process.native", "process.unrestricted"]
            ),
            "restricted M0 capability profile",
        ),
        (
            lambda value: value.__setitem__("permissions", ["secret.read"]),
            "restricted M0 capability profile",
        ),
        (
            lambda value: value.__setitem__("inputs", [{"id": "source"}]),
            "ports or host resources",
        ),
        (
            lambda value: value.__setitem__("resources", {"host": True}),
            "ports or host resources",
        ),
        (
            lambda value: value["runtime"].__setitem__("config", {"protocol": "other"}),
            "fixed JSON stdio protocol",
        ),
        (
            lambda value: value["runtime"].__setitem__(
                "entrypoint", "private shell command; do not echo"
            ),
            "entrypoint is invalid",
        ),
    ),
)
def test_manifest_profile_rejects_every_unimplemented_surface(
    mutate: Any,
    message: str,
) -> None:
    document = load_document(MANIFEST)
    mutate(document)
    registry, report, authorization, policy = _case(manifest_document=document)
    with pytest.raises(NativeProcessPreflightError, match=message) as captured:
        preflight_native_process(report, registry, authorization, policy)
    assert "private shell command" not in str(captured.value)
    assert "secret.read" not in str(captured.value)


@pytest.mark.parametrize(
    "policy",
    (
        "not-a-policy",
        None,
    ),
)
def test_malformed_policy_type_is_rejected(policy: object) -> None:
    registry, report, authorization, _ = _case()
    with pytest.raises(NativeProcessPreflightError, match="policy is invalid"):
        preflight_native_process(
            report,
            registry,
            authorization,
            policy,  # type: ignore[arg-type]
        )


def test_policy_shape_and_all_limit_bounds_fail_closed() -> None:
    registry, report, authorization, policy = _case()
    malformed = (
        replace(policy, task_path=("task",) * (MAX_NATIVE_TASK_PATH_ITEMS + 1)),
        replace(policy, environment_allowlist=("PATH",)),
        replace(policy, shell=True),
        replace(policy, limits=replace(policy.limits, wall_time_seconds=0)),
        replace(policy, limits=replace(policy.limits, wall_time_seconds=True)),
        replace(policy, limits=replace(policy.limits, stdout_bytes=16_777_217)),
        replace(policy, limits=replace(policy.limits, stderr_bytes=-1)),
        replace(policy, limits=replace(policy.limits, termination_grace_seconds=61)),
    )
    for item in malformed:
        with pytest.raises(NativeProcessPreflightError, match="invalid"):
            preflight_native_process(report, registry, authorization, item)


def test_tampered_or_blocked_dry_run_report_is_revalidated() -> None:
    registry, report, authorization, policy = _case()
    tampered = report.model_copy(update={"plan": None})
    with pytest.raises(NativeProcessPreflightError, match="failed validation"):
        preflight_native_process(tampered, registry, authorization, policy)

    blocked = report.model_copy(update={"status": DryRunStatus.BLOCKED})
    with pytest.raises(NativeProcessPreflightError, match=r"failed validation|ready plan"):
        preflight_native_process(blocked, registry, authorization, policy)


def test_config_and_entrypoint_values_never_enter_result_or_error() -> None:
    secret_config = "private-config-value"
    secret_entrypoint = "private_package.private_module:private_callable"
    manifest = load_document(MANIFEST)
    manifest["runtime"]["entrypoint"] = secret_entrypoint
    spec = load_document(SPEC)
    spec["workflows"][0]["graph"]["nodes"][0]["config"]["operation"] = secret_config
    manifest["configSchema"]["properties"]["operation"] = {"const": secret_config}
    registry, report, authorization, policy = _case(
        manifest_document=manifest,
        spec_document=spec,
    )
    result = preflight_native_process(report, registry, authorization, policy)
    assert secret_config not in repr(result)
    assert secret_entrypoint not in repr(result)


def test_preflight_never_imports_executes_or_performs_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, report, authorization, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(os, "system", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(Path, "write_text", tripwire)

    result = preflight_native_process(report, registry, authorization, policy)
    assert result.preflight_digest.startswith("jcs-sha256:")
