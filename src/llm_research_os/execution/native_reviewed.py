"""Non-launching validator for native-reviewed-python/v0alpha1.

This module parses a bounded request, compares it with a caller-supplied
verified-prefix citation, and returns a report whose ``launchAllowed`` value
is false. It does not import an entrypoint, spawn a process, open a grant
session, or append a Run/Attempt fact. Grant fields are contract checks for
a later package; they are not consumed here.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from llm_research_os.canonical import content_digest
from llm_research_os.execution.errors import NativeReviewedExecutionError
from llm_research_os.execution.native_reviewed_documents import (
    EXECUTE_NATIVE_CAPABILITY,
    MAX_REVIEWED_REQUEST_BYTES,
    NATIVE_REVIEWED_API_VERSION,
    NATIVE_REVIEWED_MEDIA_TYPE,
    NATIVE_REVIEWED_PROFILE,
    SUPPORTED_REVIEWED_PLATFORMS,
    NativeReviewedExecutionReport,
    NativeReviewedExecutionRequest,
    ReviewedReasonCode,
)

DecisionKind = Literal["authorization-decision", "application-receipt", "ai-proposal"]
GrantClaimState = Literal["unclaimed", "consumed", "resumed"]


@dataclass(frozen=True, slots=True)
class ReviewedPrefixCitation:
    """Facts already checked against one verified EventStore prefix.

    The validator does not open the store. An adapter that has not verified
    the prefix must set ``prefix_verified`` false so the request fails closed.
    """

    prefix_verified: bool
    decision_kind: DecisionKind
    project_id: str
    revision_id: str
    workflow_id: str
    task_id: str
    run_id: str
    attempt_id: str
    worker_id: str
    authorization_event_id: str
    authorization_sequence: str
    actor_id: str
    actor_kind: str
    authorized: bool
    capabilities: frozenset[str]
    spec_digest: str
    registry_digest: str
    plan_digest: str
    decision_digest: str
    review_citation_digest: str
    bundle_digest: str
    media_type: str
    entrypoint: str
    input_digests: tuple[tuple[str, str], ...]
    config_digest: str
    interpreter_digest: str
    python_version: str
    abi: str
    dependency_lock_digest: str
    inventory_digest: str
    platform_os: str
    platform_architecture: str


@dataclass(frozen=True, slots=True)
class PreparedMaterialCitation:
    """Point-of-use bytes. A difference from the request invalidates the binding."""

    bundle_digest: str
    media_type: str
    entrypoint: str
    input_digests: tuple[tuple[str, str], ...]
    config_digest: str
    interpreter_digest: str
    python_version: str
    abi: str
    dependency_lock_digest: str
    inventory_digest: str
    platform_os: str
    platform_architecture: str


@dataclass(frozen=True, slots=True)
class GrantContractCheck:
    """Contract-check view of a Worker grant. Not a session and not consumed."""

    capability: str
    hmac_valid: bool
    expired: bool
    revoked: bool
    nonce_consumed: bool
    claim_state: GrantClaimState
    image_digest: str
    image_media_type: str
    config_digest: str
    project_id: str
    run_id: str
    task_id: str
    worker_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class ReviewedValidationContext:
    """Adapter input for one contract check. R05 alone may launch."""

    citation: ReviewedPrefixCitation
    prepared: PreparedMaterialCitation
    grant: GrantContractCheck | None = None


@dataclass(frozen=True, slots=True)
class HostFeasibility:
    """What this host actually enforces for the reviewed profile.

    Every isolation flag is false: R03 has no runner, and the profile has no
    network, filesystem, or memory enforcement to claim.
    """

    system: str
    architecture: str
    supported: bool
    network_enforced: bool
    filesystem_enforced: bool
    memory_enforced: bool
    process_group_enforced: bool
    wall_clock_enforced: bool
    output_bounds_enforced: bool
    launch_implemented: bool
    profile: str


def observe_host_feasibility() -> HostFeasibility:
    """Read this process's platform identity. Does not start a child process."""

    system = platform.system().lower()
    architecture = platform.machine()
    return HostFeasibility(
        system=system,
        architecture=architecture,
        supported=(system, architecture) in SUPPORTED_REVIEWED_PLATFORMS,
        network_enforced=False,
        filesystem_enforced=False,
        memory_enforced=False,
        process_group_enforced=False,
        wall_clock_enforced=False,
        output_bounds_enforced=False,
        launch_implemented=False,
        profile=NATIVE_REVIEWED_PROFILE,
    )


def execution_object(request: NativeReviewedExecutionRequest) -> dict[str, object]:
    """Canonical planned execution object covered by ``configDigest``.

    Identity fields (project, Run, Attempt, grant) stay outside this object.
    Input order is significant. Optional ceilings are omitted when absent.
    """

    limits: dict[str, object] = {
        "artifactBytes": request.limits.artifact_bytes,
        "stderrBytes": request.limits.stderr_bytes,
        "stdoutBytes": request.limits.stdout_bytes,
        "wallTimeSeconds": request.limits.wall_time_seconds,
    }
    if request.limits.memory_bytes is not None:
        limits["memoryBytes"] = {
            "ceiling": request.limits.memory_bytes.ceiling,
            "required": request.limits.memory_bytes.required,
        }
    if request.limits.process_count is not None:
        limits["processCount"] = {
            "ceiling": request.limits.process_count.ceiling,
            "required": request.limits.process_count.required,
        }
    return {
        "code": {
            "bundleDigest": request.code.bundle_digest,
            "entrypoint": request.code.entrypoint,
            "mediaType": request.code.media_type,
            "review": {
                "bundleDigest": request.code.review.bundle_digest,
                "citationDigest": request.code.review.citation_digest,
            },
        },
        "environment": {
            "abi": request.environment.abi,
            "dependencyLockDigest": request.environment.dependency_lock_digest,
            "interpreterDigest": request.environment.interpreter_digest,
            "inventoryDigest": request.environment.inventory_digest,
            "platform": {
                "architecture": request.environment.platform.architecture,
                "os": request.environment.platform.os,
            },
            "pythonVersion": request.environment.python_version,
        },
        "inputs": [
            {
                "digest": item.digest,
                "name": item.name,
                "purpose": item.purpose,
                "sizeBytes": item.size_bytes,
            }
            for item in request.inputs
        ],
        "limits": limits,
        "platform": {
            "architecture": request.platform.architecture,
            "os": request.platform.os,
        },
        "profile": request.profile,
        "restrictions": {
            "filesystem": {
                "requested": request.restrictions.filesystem.requested,
                "required": request.restrictions.filesystem.required,
            },
            "memory": {
                "requested": request.restrictions.memory.requested,
                "required": request.restrictions.memory.required,
            },
            "network": {
                "requested": request.restrictions.network.requested,
                "required": request.restrictions.network.required,
            },
        },
    }


def request_digest(request: NativeReviewedExecutionRequest) -> str:
    """JCS digest of the closed request. Omitted optional ceilings stay omitted."""

    payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    return content_digest(payload)


def parse_native_reviewed_request(payload: bytes | str) -> NativeReviewedExecutionRequest:
    """Parse one bounded JSON request. Invalid documents raise and do not launch."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > MAX_REVIEWED_REQUEST_BYTES:
        raise NativeReviewedExecutionError(
            "request exceeds the byte limit",
            code="request-too-large",
        )

    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError(f"duplicate JSON field: {key}")
            fields[key] = value
        return fields

    try:
        document = json.loads(raw, object_pairs_hook=unique_fields)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise NativeReviewedExecutionError(
            "request is not JSON",
            code="request-invalid",
        ) from exc
    if type(document) is not dict:
        raise NativeReviewedExecutionError(
            "request must be a JSON object",
            code="request-invalid",
        )
    try:
        return NativeReviewedExecutionRequest.model_validate(document)
    except ValidationError as exc:
        raise NativeReviewedExecutionError(
            "request is not a valid reviewed execution document",
            code="request-invalid",
        ) from exc


def validate_native_reviewed_execution(
    request: NativeReviewedExecutionRequest,
    context: ReviewedValidationContext,
) -> NativeReviewedExecutionReport:
    """Return a validation report. This function never starts user code."""

    reason = _refusal_reason(request, context)
    if reason is None:
        return _report(request, accepted=True, reason="launch-not-implemented")
    return _report(request, accepted=False, reason=reason)


def _refusal_reason(
    request: NativeReviewedExecutionRequest,
    context: ReviewedValidationContext,
) -> ReviewedReasonCode | None:
    citation = context.citation
    if not citation.prefix_verified:
        return "prefix-unverified"
    if citation.decision_kind != "authorization-decision":
        return "decision-not-authorization"
    identity = _identity_reason(request, citation)
    if identity is not None:
        return identity
    if content_digest(execution_object(request)) != request.config_digest:
        return "config-digest-mismatch"
    material = _material_reason(request, citation)
    if material is not None:
        return material
    prepared = _prepared_reason(request, context.prepared)
    if prepared is not None:
        return prepared
    ceilings = _ceiling_reason(request)
    if ceilings is not None:
        return ceilings
    if context.grant is not None:
        return _grant_reason(request, context.grant)
    return None


def _identity_reason(
    request: NativeReviewedExecutionRequest,
    citation: ReviewedPrefixCitation,
) -> ReviewedReasonCode | None:
    checks: tuple[tuple[object, object, ReviewedReasonCode], ...] = (
        (request.project_id, citation.project_id, "foreign-project"),
        (request.revision_id, citation.revision_id, "stale-revision"),
        (request.workflow_id, citation.workflow_id, "foreign-workflow"),
        (request.task_id, citation.task_id, "foreign-task"),
        (request.run_id, citation.run_id, "foreign-run"),
        (request.attempt_id, citation.attempt_id, "foreign-attempt"),
        (request.worker_id, citation.worker_id, "foreign-worker"),
        (
            request.authorization_event_id,
            citation.authorization_event_id,
            "authorization-event-mismatch",
        ),
        (
            request.authorization_sequence,
            citation.authorization_sequence,
            "authorization-sequence-mismatch",
        ),
        (request.actor_id, citation.actor_id, "authorization-actor-mismatch"),
    )
    for actual, expected, code in checks:
        if actual != expected:
            return code
    if citation.actor_kind != "human":
        return "authorization-actor-not-human"
    if citation.authorized is not True:
        return "authorization-not-authorized"
    if EXECUTE_NATIVE_CAPABILITY not in citation.capabilities:
        return "authorization-capability-mismatch"
    digest_checks: tuple[tuple[str, str, ReviewedReasonCode], ...] = (
        (request.spec_digest, citation.spec_digest, "spec-digest-mismatch"),
        (request.registry_digest, citation.registry_digest, "registry-digest-mismatch"),
        (request.plan_digest, citation.plan_digest, "plan-digest-mismatch"),
        (request.decision_digest, citation.decision_digest, "decision-digest-mismatch"),
        (
            request.code.review.citation_digest,
            citation.review_citation_digest,
            "review-digest-mismatch",
        ),
    )
    for actual, expected, code in digest_checks:
        if actual != expected:
            return code
    return None


def _material_reason(
    request: NativeReviewedExecutionRequest,
    citation: ReviewedPrefixCitation,
) -> ReviewedReasonCode | None:
    return _same_material(
        request,
        bundle_digest=citation.bundle_digest,
        media_type=citation.media_type,
        entrypoint=citation.entrypoint,
        input_digests=citation.input_digests,
        config_digest=citation.config_digest,
        interpreter_digest=citation.interpreter_digest,
        python_version=citation.python_version,
        abi=citation.abi,
        dependency_lock_digest=citation.dependency_lock_digest,
        inventory_digest=citation.inventory_digest,
        platform_os=citation.platform_os,
        platform_architecture=citation.platform_architecture,
    )


def _prepared_reason(
    request: NativeReviewedExecutionRequest,
    prepared: PreparedMaterialCitation,
) -> ReviewedReasonCode | None:
    return _same_material(
        request,
        bundle_digest=prepared.bundle_digest,
        media_type=prepared.media_type,
        entrypoint=prepared.entrypoint,
        input_digests=prepared.input_digests,
        config_digest=prepared.config_digest,
        interpreter_digest=prepared.interpreter_digest,
        python_version=prepared.python_version,
        abi=prepared.abi,
        dependency_lock_digest=prepared.dependency_lock_digest,
        inventory_digest=prepared.inventory_digest,
        platform_os=prepared.platform_os,
        platform_architecture=prepared.platform_architecture,
    )


def _same_material(
    request: NativeReviewedExecutionRequest,
    *,
    bundle_digest: str,
    media_type: str,
    entrypoint: str,
    input_digests: tuple[tuple[str, str], ...],
    config_digest: str,
    interpreter_digest: str,
    python_version: str,
    abi: str,
    dependency_lock_digest: str,
    inventory_digest: str,
    platform_os: str,
    platform_architecture: str,
) -> ReviewedReasonCode | None:
    presented_inputs = tuple((item.name, item.digest) for item in request.inputs)
    checks: tuple[tuple[object, object, ReviewedReasonCode], ...] = (
        (request.code.bundle_digest, bundle_digest, "code-digest-mismatch"),
        (request.code.media_type, media_type, "media-type-mismatch"),
        (request.code.entrypoint, entrypoint, "entrypoint-mismatch"),
        (presented_inputs, input_digests, "input-digest-mismatch"),
        (request.environment.interpreter_digest, interpreter_digest, "interpreter-digest-mismatch"),
        (
            request.environment.dependency_lock_digest,
            dependency_lock_digest,
            "dependency-lock-mismatch",
        ),
        (request.environment.inventory_digest, inventory_digest, "inventory-digest-mismatch"),
        (request.environment.python_version, python_version, "environment-identity-mismatch"),
        (request.environment.abi, abi, "environment-identity-mismatch"),
        (request.platform.os, platform_os, "environment-identity-mismatch"),
        (request.platform.architecture, platform_architecture, "environment-identity-mismatch"),
        (request.config_digest, config_digest, "config-digest-mismatch"),
    )
    for actual, expected, code in checks:
        if actual != expected:
            return code
    return None


def _ceiling_reason(request: NativeReviewedExecutionRequest) -> ReviewedReasonCode | None:
    memory = request.limits.memory_bytes
    if request.restrictions.memory.requested == "bounded" and memory is None:
        return "missing-resource-ceiling"
    process = request.limits.process_count
    if process is not None and process.required:
        return "required-process-unenforced"
    if request.restrictions.network.required:
        return "required-network-unenforced"
    if request.restrictions.filesystem.required:
        return "required-filesystem-unenforced"
    if request.restrictions.memory.required or (memory is not None and memory.required):
        return "required-memory-unenforced"
    return None


def _grant_reason(
    request: NativeReviewedExecutionRequest,
    grant: GrantContractCheck,
) -> ReviewedReasonCode | None:
    if grant.capability != EXECUTE_NATIVE_CAPABILITY:
        return "grant-capability-mismatch"
    if grant.image_media_type != NATIVE_REVIEWED_MEDIA_TYPE:
        return "grant-media-mismatch"
    if grant.hmac_valid is not True:
        return "grant-hmac-invalid"
    if grant.expired:
        return "grant-expired"
    if grant.revoked:
        return "grant-revoked"
    if grant.nonce_consumed:
        return "grant-nonce-replay"
    if grant.claim_state == "resumed":
        return "grant-resumed-claim"
    if grant.claim_state == "consumed":
        return "grant-already-consumed"
    if (
        grant.image_digest != request.code.bundle_digest
        or grant.config_digest != request.config_digest
        or grant.project_id != request.project_id
        or grant.run_id != request.run_id
        or grant.task_id != request.task_id
        or grant.worker_id != request.worker_id
        or grant.attempt_id != request.attempt_id
    ):
        return "grant-binding-mismatch"
    return None


def _report(
    request: NativeReviewedExecutionRequest,
    *,
    accepted: bool,
    reason: ReviewedReasonCode,
) -> NativeReviewedExecutionReport:
    memory = request.limits.memory_bytes
    process = request.limits.process_count
    document = {
        "apiVersion": NATIVE_REVIEWED_API_VERSION,
        "kind": "NativeReviewedExecutionReport",
        "profile": request.profile,
        "evidenceClass": "contract-check",
        "requestDigest": request_digest(request),
        "projectId": request.project_id,
        "runId": request.run_id,
        "attemptId": request.attempt_id,
        "taskId": request.task_id,
        "authorizationEventId": request.authorization_event_id,
        "authorizationSequence": request.authorization_sequence,
        "platform": {
            "os": request.platform.os,
            "architecture": request.platform.architecture,
        },
        "acceptedForPreparation": accepted,
        "launchAllowed": False,
        "outcome": "accepted-for-preparation" if accepted else "refused",
        "reasonCode": reason,
        "restrictions": {
            "network": _network_evidence(request),
            "filesystem": _filesystem_evidence(request),
            "memory": _memory_evidence(request),
        },
        "limits": {
            "wallTimeSeconds": _declared_limit(request.limits.wall_time_seconds),
            "stdoutBytes": _declared_limit(request.limits.stdout_bytes),
            "stderrBytes": _declared_limit(request.limits.stderr_bytes),
            "artifactBytes": _declared_limit(request.limits.artifact_bytes),
            "processCount": _optional_limit(None if process is None else process.ceiling),
            "memoryBytes": _optional_limit(None if memory is None else memory.ceiling),
        },
        "codeDigest": request.code.bundle_digest,
        "inputDigests": [{"name": item.name, "digest": item.digest} for item in request.inputs],
        "interpreterDigest": request.environment.interpreter_digest,
        "dependencyLockDigest": request.environment.dependency_lock_digest,
        "inventoryDigest": request.environment.inventory_digest,
        "sideEffects": {
            "entrypointsImported": 0,
            "processesSpawned": 0,
            "lifecycleFactsAppended": 0,
        },
    }
    return NativeReviewedExecutionReport.model_validate(document)


def _declared_limit(value: int) -> dict[str, object]:
    return {"enforced": "not-enforced", "evidence": "declared", "requested": value}


def _optional_limit(value: int | None) -> dict[str, object]:
    if value is None:
        return {"enforced": "not-enforced", "evidence": "missing"}
    return _declared_limit(value)


def _network_evidence(request: NativeReviewedExecutionRequest) -> dict[str, str]:
    requested = request.restrictions.network.requested
    unsupported = "none" if requested == "none" else "network-isolation"
    return {"requested": requested, "enforced": "not-enforced", "unsupported": unsupported}


def _filesystem_evidence(request: NativeReviewedExecutionRequest) -> dict[str, str]:
    requested = request.restrictions.filesystem.requested
    unsupported = "none" if requested == "host" else "filesystem-confinement"
    return {"requested": requested, "enforced": "not-enforced", "unsupported": unsupported}


def _memory_evidence(request: NativeReviewedExecutionRequest) -> dict[str, str]:
    requested = request.restrictions.memory.requested
    unsupported = "none" if requested == "unbounded" else "memory-limit"
    return {"requested": requested, "enforced": "not-enforced", "unsupported": unsupported}
