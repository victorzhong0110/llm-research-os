"""Pure, non-executing preflight for one exact native Python task.

This module freezes a reviewable launch contract.  It never resolves an
interpreter, imports an entrypoint, opens an artifact, creates a workspace,
spawns a process, sends a signal, persists a receipt, or treats caller-asserted
authorization as authenticated authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from llm_research_os.blocks.models import RuntimeType
from llm_research_os.blocks.registry import BlockRegistry, RegistryError
from llm_research_os.canonical import content_digest
from llm_research_os.execution.authorization import PlanAuthorizationPolicy, authorize_plan
from llm_research_os.execution.errors import (
    NativeProcessPreflightError,
    PlanAuthorizationError,
)
from llm_research_os.execution.models import DryRunReport, DryRunStatus, PlannedTask

NATIVE_PROCESS_RUNNER: Literal["researchos.python-worker/v0alpha1"] = (
    "researchos.python-worker/v0alpha1"
)
NATIVE_PROCESS_PROTOCOL: Literal["researchos.python-json-stdio/v0alpha1"] = (
    "researchos.python-json-stdio/v0alpha1"
)
NATIVE_PROCESS_CAPABILITY = "process.native"
NATIVE_PROCESS_NETWORK: Literal["denied"] = "denied"
NATIVE_PROCESS_WORKSPACE: Literal["isolated-temporary"] = "isolated-temporary"
NATIVE_PROCESS_TERMINATION: Literal["terminate-then-kill"] = "terminate-then-kill"
NATIVE_PROCESS_INTERPRETER_IDENTITY: Literal["not-bound"] = "not-bound"
MAX_NATIVE_WALL_TIME_SECONDS = 3_600
MAX_NATIVE_OUTPUT_BYTES = 16_777_216
MAX_NATIVE_TERMINATION_GRACE_SECONDS = 60
MAX_NATIVE_TASK_PATH_ITEMS = 128

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENTRYPOINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r":[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


@dataclass(frozen=True, slots=True)
class NativeProcessLimits:
    """Caller-selected hard ceilings for a future isolated invocation."""

    wall_time_seconds: int
    stdout_bytes: int
    stderr_bytes: int
    termination_grace_seconds: int


@dataclass(frozen=True, slots=True)
class NativeProcessPreflightPolicy:
    """Exact caller-owned launch-review input without execution authority."""

    spec_digest: str
    registry_digest: str
    plan_digest: str
    authorization_decision_digest: str
    task_path: tuple[str, ...]
    runner: str
    shell: bool
    network: str
    workspace: str
    environment_allowlist: tuple[str, ...]
    limits: NativeProcessLimits


@dataclass(frozen=True, slots=True)
class NativeProcessPreflightResult:
    """Deterministic review result that is deliberately not launchable."""

    spec_digest: str
    registry_digest: str
    plan_digest: str
    authorization_decision_digest: str
    preflight_digest: str
    task_path: tuple[str, ...]
    block_id: str
    block_version: str
    manifest_digest: str
    config_digest: str
    entrypoint_digest: str
    limits: NativeProcessLimits


def preflight_native_process(
    report: DryRunReport,
    registry: BlockRegistry,
    authorization_policy: PlanAuthorizationPolicy,
    policy: NativeProcessPreflightPolicy,
) -> NativeProcessPreflightResult:
    """Freeze one exact native Python launch review without performing it."""

    snapshot = _validated_ready_report(report)
    _validate_policy(policy)
    try:
        authorization = authorize_plan(snapshot, authorization_policy)
    except PlanAuthorizationError:
        raise NativeProcessPreflightError("native process preflight authorization failed") from None
    if not authorization.authorized:
        raise NativeProcessPreflightError(
            "native process preflight requires an authorized exact plan"
        )
    if (
        policy.spec_digest != authorization.spec_digest
        or policy.registry_digest != authorization.registry_digest
        or policy.plan_digest != authorization.plan_digest
        or policy.authorization_decision_digest != authorization.decision_digest
    ):
        raise NativeProcessPreflightError(
            "native process preflight does not match the authorization binding"
        )

    if type(registry) is not BlockRegistry or not registry.sealed:
        raise NativeProcessPreflightError("native process preflight requires a sealed registry")
    if registry.digest() != snapshot.digests.registry:
        raise NativeProcessPreflightError(
            "native process preflight registry does not match the plan"
        )

    plan = snapshot.plan
    if plan is None or snapshot.digests.plan is None:
        raise NativeProcessPreflightError("native process preflight requires a complete ready plan")
    if plan.resources or plan.graph.edges:
        raise NativeProcessPreflightError(
            "native process preflight requires an isolated single-task plan"
        )
    nodes = tuple(node for stage in plan.graph.stages for node in stage.nodes)
    if len(nodes) != 1 or not isinstance(nodes[0], PlannedTask):
        raise NativeProcessPreflightError(
            "native process preflight requires an isolated single-task plan"
        )
    task = nodes[0]
    if task.node_path != policy.task_path or task.depends_on or task.resource_refs:
        raise NativeProcessPreflightError(
            "native process preflight task selection does not match the plan"
        )

    try:
        registered = registry.resolve(str(task.block.id), str(task.block.version))
    except RegistryError:
        raise NativeProcessPreflightError(
            "native process preflight could not resolve the planned block"
        ) from None
    manifest = registered.manifest
    if (
        registered.digest != task.block.manifest_digest
        or manifest.runtime.type is not RuntimeType.PYTHON
        or task.block.runtime_type is not RuntimeType.PYTHON
    ):
        raise NativeProcessPreflightError(
            "native process preflight requires an exact Python manifest"
        )
    if (
        tuple(sorted(manifest.capabilities)) != (NATIVE_PROCESS_CAPABILITY,)
        or tuple(sorted(task.declared_capabilities)) != (NATIVE_PROCESS_CAPABILITY,)
        or manifest.permissions
        or task.declared_permissions
    ):
        raise NativeProcessPreflightError(
            "native process preflight requires the restricted M0 capability profile"
        )
    if manifest.inputs or manifest.outputs or manifest.resources:
        raise NativeProcessPreflightError(
            "native process preflight does not support ports or host resources"
        )
    if manifest.runtime.config != {"protocol": NATIVE_PROCESS_PROTOCOL}:
        raise NativeProcessPreflightError(
            "native process preflight requires the fixed JSON stdio protocol"
        )
    entrypoint = manifest.runtime.entrypoint
    if type(entrypoint) is not str or _ENTRYPOINT_PATTERN.fullmatch(entrypoint) is None:
        raise NativeProcessPreflightError("native process preflight manifest entrypoint is invalid")

    entrypoint_digest = content_digest(
        {
            "runtimeType": RuntimeType.PYTHON,
            "runner": NATIVE_PROCESS_RUNNER,
            "protocol": NATIVE_PROCESS_PROTOCOL,
            "entrypoint": entrypoint,
        }
    )
    payload = _preflight_payload(
        spec_digest=authorization.spec_digest,
        registry_digest=authorization.registry_digest,
        plan_digest=authorization.plan_digest,
        authorization_decision_digest=authorization.decision_digest,
        task_path=task.node_path,
        block_id=str(task.block.id),
        block_version=str(task.block.version),
        manifest_digest=registered.digest,
        config_digest=task.config_digest,
        entrypoint_digest=entrypoint_digest,
        limits=policy.limits,
    )
    return NativeProcessPreflightResult(
        spec_digest=authorization.spec_digest,
        registry_digest=authorization.registry_digest,
        plan_digest=authorization.plan_digest,
        authorization_decision_digest=authorization.decision_digest,
        preflight_digest=content_digest(payload),
        task_path=task.node_path,
        block_id=str(task.block.id),
        block_version=str(task.block.version),
        manifest_digest=registered.digest,
        config_digest=task.config_digest,
        entrypoint_digest=entrypoint_digest,
        limits=policy.limits,
    )


def native_process_preflight_payload(result: NativeProcessPreflightResult) -> dict[str, Any]:
    """Return the normative digest payload for an immutable preflight result."""

    return _preflight_payload(
        spec_digest=result.spec_digest,
        registry_digest=result.registry_digest,
        plan_digest=result.plan_digest,
        authorization_decision_digest=result.authorization_decision_digest,
        task_path=result.task_path,
        block_id=result.block_id,
        block_version=result.block_version,
        manifest_digest=result.manifest_digest,
        config_digest=result.config_digest,
        entrypoint_digest=result.entrypoint_digest,
        limits=result.limits,
    )


def _preflight_payload(
    *,
    spec_digest: str,
    registry_digest: str,
    plan_digest: str,
    authorization_decision_digest: str,
    task_path: tuple[str, ...],
    block_id: str,
    block_version: str,
    manifest_digest: str,
    config_digest: str,
    entrypoint_digest: str,
    limits: NativeProcessLimits,
) -> dict[str, Any]:
    return {
        "binding": {
            "specDigest": spec_digest,
            "registryDigest": registry_digest,
            "planDigest": plan_digest,
            "authorizationDecisionDigest": authorization_decision_digest,
        },
        "task": {
            "taskPath": list(task_path),
            "blockId": block_id,
            "blockVersion": block_version,
            "manifestDigest": manifest_digest,
            "configDigest": config_digest,
            "entrypointDigest": entrypoint_digest,
            "runtimeType": RuntimeType.PYTHON,
            "runner": NATIVE_PROCESS_RUNNER,
            "protocol": NATIVE_PROCESS_PROTOCOL,
        },
        "constraints": {
            "shell": False,
            "network": NATIVE_PROCESS_NETWORK,
            "workspace": NATIVE_PROCESS_WORKSPACE,
            "environmentAllowlist": [],
            "argvMode": "trusted-runner-fixed",
            "stdin": "json-object",
            "stdout": "bounded-capture",
            "stderr": "bounded-capture",
            "termination": NATIVE_PROCESS_TERMINATION,
            "interpreterIdentity": NATIVE_PROCESS_INTERPRETER_IDENTITY,
        },
        "limits": {
            "wallTimeSeconds": limits.wall_time_seconds,
            "stdoutBytes": limits.stdout_bytes,
            "stderrBytes": limits.stderr_bytes,
            "terminationGraceSeconds": limits.termination_grace_seconds,
        },
        "authority": {
            "authentication": "not-authenticated",
            "persistence": "not-persisted",
            "isolation": "not-enforced",
            "launchAllowed": False,
        },
    }


def _validated_ready_report(report: DryRunReport) -> DryRunReport:
    if type(report) is not DryRunReport:
        raise NativeProcessPreflightError(
            "native process preflight requires a validated dry-run report"
        )
    try:
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        snapshot = DryRunReport.model_validate(payload)
    except (TypeError, ValueError):
        raise NativeProcessPreflightError(
            "native process preflight dry-run report failed validation"
        ) from None
    if snapshot.status is not DryRunStatus.READY:
        raise NativeProcessPreflightError("native process preflight requires a complete ready plan")
    return snapshot


def _validate_policy(policy: NativeProcessPreflightPolicy) -> None:
    if type(policy) is not NativeProcessPreflightPolicy:
        raise NativeProcessPreflightError("native process preflight policy is invalid")
    for digest in (
        policy.spec_digest,
        policy.registry_digest,
        policy.plan_digest,
        policy.authorization_decision_digest,
    ):
        if type(digest) is not str or _DIGEST_PATTERN.fullmatch(digest) is None:
            raise NativeProcessPreflightError("native process preflight policy is invalid")
    if (
        type(policy.task_path) is not tuple
        or not policy.task_path
        or len(policy.task_path) > MAX_NATIVE_TASK_PATH_ITEMS
        or any(
            type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None
            for value in policy.task_path
        )
        or policy.runner != NATIVE_PROCESS_RUNNER
        or policy.shell is not False
        or policy.network != NATIVE_PROCESS_NETWORK
        or policy.workspace != NATIVE_PROCESS_WORKSPACE
        or type(policy.environment_allowlist) is not tuple
        or policy.environment_allowlist
    ):
        raise NativeProcessPreflightError("native process preflight policy is invalid")
    limits = policy.limits
    if type(limits) is not NativeProcessLimits:
        raise NativeProcessPreflightError("native process preflight limits are invalid")
    values = (
        limits.wall_time_seconds,
        limits.stdout_bytes,
        limits.stderr_bytes,
        limits.termination_grace_seconds,
    )
    if any(type(value) is not int for value in values):
        raise NativeProcessPreflightError("native process preflight limits are invalid")
    if not 1 <= limits.wall_time_seconds <= MAX_NATIVE_WALL_TIME_SECONDS:
        raise NativeProcessPreflightError("native process preflight limits are invalid")
    if not 0 <= limits.stdout_bytes <= MAX_NATIVE_OUTPUT_BYTES:
        raise NativeProcessPreflightError("native process preflight limits are invalid")
    if not 0 <= limits.stderr_bytes <= MAX_NATIVE_OUTPUT_BYTES:
        raise NativeProcessPreflightError("native process preflight limits are invalid")
    if not 0 <= limits.termination_grace_seconds <= MAX_NATIVE_TERMINATION_GRACE_SECONDS:
        raise NativeProcessPreflightError("native process preflight limits are invalid")
