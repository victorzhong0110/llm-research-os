"""Prepare and diagnose a reviewed native environment without starting user code.

Caller-supplied prefix citations and grant booleans are not accepted. This
module rebuilds the authorization fact, Worker grant, and CAS bytes, copies
those bytes into a private workspace, and re-hashes them before return.
``launchAllowed`` stays false. No entrypoint is imported and no child is spawned.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ValidationError

from llm_research_os.artifacts.errors import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreError,
)
from llm_research_os.artifacts.store import MAX_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.events.models import ActorKind
from llm_research_os.execution.authorization_events import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    PlanAuthorizationEvaluatedPayload,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.execution.errors import (
    NativeReviewedPreparationError,
    PlanAuthorizationRecordError,
)
from llm_research_os.execution.native_reviewed import (
    GrantContractCheck,
    PreparedMaterialCitation,
    ReviewedPrefixCitation,
    ReviewedValidationContext,
    execution_object,
    request_digest,
    validate_native_reviewed_execution,
)
from llm_research_os.execution.native_reviewed_documents import (
    EXECUTE_NATIVE_CAPABILITY,
    NATIVE_REVIEWED_API_VERSION,
    NATIVE_REVIEWED_MEDIA_TYPE,
    NATIVE_REVIEWED_PROFILE,
    NativeReviewedExecutionRequest,
)
from llm_research_os.execution.native_reviewed_material import (
    NativeReviewedCodeReview,
    NativeReviewedDependencyInventory,
    NativeReviewedDependencyLock,
    NativeReviewedInterpreterIdentity,
    NativeReviewedPythonBundle,
    entrypoint_source_path,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NativeReviewedPreparationDiagnosis,
    NativeReviewedPreparationReceipt,
    PreparationCheck,
    PreparationReasonCode,
    PreparedFileRecord,
    diagnosis_outcome,
)
from llm_research_os.storage.errors import EventStoreError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.control import GrantRecord, WorkerControl
from llm_research_os.workers.errors import WorkerError, WorkerGrantError
from llm_research_os.workers.tokens import verify_grant_token

_REASONS = frozenset(get_args(PreparationReasonCode))
_NOFOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
_READ_FLAGS = os.O_RDONLY | _NOFOLLOW
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
_SUBSTITUTION = {
    "bundle": "code-substituted",
    "code": "code-substituted",
    "config": "config-substituted",
    "input": "input-substituted",
    "interpreter": "environment-substituted",
    "dependency-lock": "environment-substituted",
    "inventory": "environment-substituted",
    "review": "review-substituted",
}
_ZERO_EFFECTS = {
    "entrypointsImported": 0,
    "processesSpawned": 0,
    "lifecycleFactsAppended": 0,
    "grantsConsumed": 0,
    "packagesInstalled": 0,
}


@dataclass(frozen=True, slots=True)
class _Verified:
    request: NativeReviewedExecutionRequest
    request_digest_value: str
    grant_id: str
    files: tuple[tuple[str, str, str, bytes], ...]
    receipt: NativeReviewedPreparationReceipt

    def payloads(self) -> dict[str, bytes]:
        return {item[0]: item[3] for item in self.files}


def prepare_reviewed_environment(
    *,
    request: NativeReviewedExecutionRequest,
    store: EventStore,
    artifacts: LocalArtifactStore,
    workspace: Path,
    grant_token: str,
    hmac_key: bytes,
    now: datetime | None = None,
) -> NativeReviewedPreparationReceipt:
    """Materialize verified bytes and bind them to the grant. Does not launch."""

    verified = _verify(
        request=request,
        store=store,
        artifacts=artifacts,
        grant_token=grant_token,
        hmac_key=hmac_key,
        now=_clock(now),
    )
    if _is_fresh(workspace):
        _write_workspace(workspace, verified)
    diagnosis = _inspect(workspace, verified)
    if diagnosis.outcome != "ready":
        raise NativeReviewedPreparationError(
            "prepared environment is not reusable",
            code=diagnosis.reason_code,
        )
    return verified.receipt


def diagnose_reviewed_environment(
    *,
    request: NativeReviewedExecutionRequest,
    store: EventStore,
    artifacts: LocalArtifactStore,
    workspace: Path,
    grant_token: str,
    hmac_key: bytes,
    now: datetime | None = None,
) -> NativeReviewedPreparationDiagnosis:
    """Re-check facts and workspace bytes. Does not repair and does not launch."""

    try:
        verified = _verify(
            request=request,
            store=store,
            artifacts=artifacts,
            grant_token=grant_token,
            hmac_key=hmac_key,
            now=_clock(now),
        )
    except NativeReviewedPreparationError as exc:
        return _diagnosis(_as_reason(exc.code))
    return _inspect(workspace, verified)


def check_before_user_code(
    *,
    request: NativeReviewedExecutionRequest,
    store: EventStore,
    artifacts: LocalArtifactStore,
    workspace: Path,
    grant_token: str,
    hmac_key: bytes,
    now: datetime | None = None,
) -> NativeReviewedPreparationDiagnosis:
    """Last binding check before a later package may start user code.

    R04 always returns here. A substituted byte invalidates the old binding
    and this function does not import an entrypoint or spawn a process.
    """

    return diagnose_reviewed_environment(
        request=request,
        store=store,
        artifacts=artifacts,
        workspace=workspace,
        grant_token=grant_token,
        hmac_key=hmac_key,
        now=now,
    )


def _verify(
    *,
    request: NativeReviewedExecutionRequest,
    store: EventStore,
    artifacts: LocalArtifactStore,
    grant_token: str,
    hmac_key: bytes,
    now: datetime,
) -> _Verified:
    if type(request) is not NativeReviewedExecutionRequest:
        raise NativeReviewedPreparationError(
            "request is not a reviewed execution document",
            code="request-invalid",
        )
    authorization = _authorization(store, request)
    claims, grant = _grant(store, request, grant_token, hmac_key, now)
    files = _material_files(artifacts, request)
    parsed = _parsed_material(request, files)
    _require_host(parsed.interpreter)
    context = _context(request, authorization, claims, grant, parsed)
    report = validate_native_reviewed_execution(request, context)
    if report.launch_allowed or not report.accepted_for_preparation:
        raise NativeReviewedPreparationError(
            "reviewed binding was refused",
            code=_as_reason(report.reason_code),
        )
    receipt = _receipt(request, claims["grantId"], files, parsed)
    return _Verified(
        request=request,
        request_digest_value=request_digest(request),
        grant_id=claims["grantId"],
        files=files,
        receipt=receipt,
    )


@dataclass(frozen=True, slots=True)
class _Parsed:
    bundle: NativeReviewedPythonBundle
    interpreter: NativeReviewedInterpreterIdentity
    review_digest: str


def _parsed_material(
    request: NativeReviewedExecutionRequest,
    files: tuple[tuple[str, str, str, bytes], ...],
) -> _Parsed:
    by_path = {path: payload for path, _role, _digest, payload in files}
    bundle = _parse_model(
        by_path["material/bundle"],
        NativeReviewedPythonBundle,
        "code-digest-mismatch",
    )
    if bundle.entrypoint != request.code.entrypoint:
        raise NativeReviewedPreparationError(
            "bundle entrypoint does not match the request",
            code="entrypoint-mismatch",
        )
    interpreter = _parse_model(
        by_path["material/environment/interpreter"],
        NativeReviewedInterpreterIdentity,
        "interpreter-digest-mismatch",
    )
    _require_interpreter_document(request, interpreter)
    lock = _parse_model(
        by_path["material/environment/dependency-lock"],
        NativeReviewedDependencyLock,
        "dependency-lock-mismatch",
    )
    inventory = _parse_model(
        by_path["material/environment/inventory"],
        NativeReviewedDependencyInventory,
        "inventory-digest-mismatch",
    )
    if [item.model_dump(mode="json", by_alias=True) for item in lock.packages] != [
        item.model_dump(mode="json", by_alias=True) for item in inventory.packages
    ]:
        raise NativeReviewedPreparationError(
            "dependency inventory does not match the lock",
            code="environment-identity-mismatch",
        )
    review_bytes = by_path["material/environment/review"]
    review = _parse_model(review_bytes, NativeReviewedCodeReview, "review-digest-mismatch")
    review_digest = content_digest(review.model_dump(mode="json", by_alias=True, exclude_none=True))
    if review_digest != request.code.review.citation_digest:
        raise NativeReviewedPreparationError(
            "review citation does not match the request",
            code="review-digest-mismatch",
        )
    if (
        review.bundle_digest != request.code.bundle_digest
        or review.entrypoint != request.code.entrypoint
        or review.media_type != request.code.media_type
    ):
        raise NativeReviewedPreparationError(
            "review citation does not bind the code bundle",
            code="review-digest-mismatch",
        )
    if canonical_json(json.loads(review_bytes)).encode("utf-8") != review_bytes:
        raise NativeReviewedPreparationError(
            "review bytes are not canonical",
            code="review-digest-mismatch",
        )
    return _Parsed(bundle=bundle, interpreter=interpreter, review_digest=review_digest)


def _require_interpreter_document(
    request: NativeReviewedExecutionRequest,
    identity: NativeReviewedInterpreterIdentity,
) -> None:
    if (
        identity.python_version != request.environment.python_version
        or identity.abi != request.environment.abi
        or identity.platform.os != request.platform.os
        or identity.platform.architecture != request.platform.architecture
    ):
        raise NativeReviewedPreparationError(
            "interpreter identity does not match the request",
            code="environment-identity-mismatch",
        )


def _require_host(identity: NativeReviewedInterpreterIdentity) -> None:
    system = platform.system().lower()
    architecture = platform.machine()
    version = platform.python_version()
    abi = {12: "cp312", 13: "cp313", 14: "cp314"}.get(sys.version_info.minor)
    if (
        platform.python_implementation() != "CPython"
        or abi is None
        or system != identity.platform.os
        or architecture != identity.platform.architecture
        or version != identity.python_version
        or abi != identity.abi
    ):
        raise NativeReviewedPreparationError(
            "host interpreter identity does not match the reviewed bytes",
            code="environment-identity-mismatch",
        )


def _authorization(
    store: EventStore,
    request: NativeReviewedExecutionRequest,
) -> tuple[StoredEvent, PlanAuthorizationEvaluatedPayload]:
    stored = store.get_event(request.authorization_event_id)
    if stored is None or stored.event.type != PLAN_AUTHORIZATION_EVALUATED_TYPE:
        raise NativeReviewedPreparationError(
            "authorization fact is not on this store",
            code="prefix-unverified",
        )
    try:
        payload = validate_plan_authorization_evaluated_event(stored.event)
    except PlanAuthorizationRecordError:
        raise NativeReviewedPreparationError(
            "authorization fact is not valid",
            code="prefix-unverified",
        ) from None
    return stored, payload


def _grant(
    store: EventStore,
    request: NativeReviewedExecutionRequest,
    token: str,
    hmac_key: bytes,
    now: datetime,
) -> tuple[dict[str, str], GrantRecord]:
    if type(token) is not str or type(hmac_key) is not bytes:
        raise NativeReviewedPreparationError("grant token is not valid", code="grant-hmac-invalid")
    try:
        claims = verify_grant_token(hmac_key, token, now=now, require_live=True)
    except WorkerGrantError as exc:
        code = "grant-expired" if exc.code == "grant-expired" else "grant-hmac-invalid"
        raise NativeReviewedPreparationError("grant token was refused", code=code) from None
    try:
        fold = WorkerControl(store, project_id=request.project_id).rebuild().fold
    except (WorkerError, EventStoreError, OSError) as exc:
        raise NativeReviewedPreparationError(
            "grant facts could not be read",
            code="prefix-unverified",
        ) from exc
    grant = fold.grant(claims["grantId"])
    if grant is None or not _grant_matches(grant, claims, request):
        raise NativeReviewedPreparationError(
            "grant is not bound to this request",
            code="grant-binding-mismatch",
        )
    return claims, grant


def _grant_matches(
    grant: GrantRecord,
    claims: Mapping[str, str],
    request: NativeReviewedExecutionRequest,
) -> bool:
    return (
        grant.grant_event_id == claims["grantEventId"]
        and grant.worker_id == claims["workerId"]
        and grant.task_id == claims["taskId"]
        and grant.attempt_id == claims["attemptId"]
        and grant.run_id == claims["runId"]
        and grant.nonce == claims["nonce"]
        and grant.image_digest == claims["imageDigest"]
        and grant.config_digest == claims["configDigest"]
        and grant.authorization_event_id == request.authorization_event_id
        and grant.authorization_sequence == request.authorization_sequence
        and claims["projectId"] == request.project_id
    )


def _context(
    request: NativeReviewedExecutionRequest,
    authorization: tuple[StoredEvent, PlanAuthorizationEvaluatedPayload],
    claims: Mapping[str, str],
    grant: GrantRecord,
    parsed: _Parsed,
) -> ReviewedValidationContext:
    stored, payload = authorization
    actor_kind = stored.event.data.actor.kind
    kind = actor_kind.value if isinstance(actor_kind, ActorKind) else ""
    inputs = tuple((item.name, item.digest) for item in request.inputs)
    material = PreparedMaterialCitation(
        bundle_digest=request.code.bundle_digest,
        media_type=request.code.media_type,
        entrypoint=parsed.bundle.entrypoint,
        input_digests=inputs,
        config_digest=request.config_digest,
        interpreter_digest=request.environment.interpreter_digest,
        python_version=parsed.interpreter.python_version,
        abi=parsed.interpreter.abi,
        dependency_lock_digest=request.environment.dependency_lock_digest,
        inventory_digest=request.environment.inventory_digest,
        platform_os=parsed.interpreter.platform.os,
        platform_architecture=parsed.interpreter.platform.architecture,
    )
    citation = ReviewedPrefixCitation(
        prefix_verified=True,
        decision_kind="authorization-decision",
        project_id=stored.event.data.project_id,
        revision_id=str(stored.event.data.experiment_revision),
        workflow_id=payload.workflow_id,
        task_id=grant.task_id,
        run_id=grant.run_id,
        attempt_id=grant.attempt_id,
        worker_id=grant.worker_id,
        authorization_event_id=stored.event.id,
        authorization_sequence=stored.event.sequence,
        actor_id=stored.event.data.actor.id,
        actor_kind=kind,
        authorized=payload.authorized,
        capabilities=frozenset(payload.required_capabilities),
        spec_digest=payload.binding.spec_digest,
        registry_digest=payload.binding.registry_digest,
        plan_digest=payload.binding.plan_digest,
        decision_digest=payload.binding.decision_digest,
        review_citation_digest=parsed.review_digest,
        bundle_digest=material.bundle_digest,
        media_type=material.media_type,
        entrypoint=material.entrypoint,
        input_digests=material.input_digests,
        config_digest=material.config_digest,
        interpreter_digest=material.interpreter_digest,
        python_version=material.python_version,
        abi=material.abi,
        dependency_lock_digest=material.dependency_lock_digest,
        inventory_digest=material.inventory_digest,
        platform_os=material.platform_os,
        platform_architecture=material.platform_architecture,
    )
    consumed = grant.consumed_lease_id is not None
    grant_check = GrantContractCheck(
        capability=EXECUTE_NATIVE_CAPABILITY,
        hmac_valid=True,
        expired=False,
        revoked=grant.revoked,
        nonce_consumed=False,
        claim_state="consumed" if consumed else "unclaimed",
        image_digest=claims["imageDigest"],
        image_media_type=NATIVE_REVIEWED_MEDIA_TYPE,
        config_digest=claims["configDigest"],
        project_id=claims["projectId"],
        run_id=claims["runId"],
        task_id=claims["taskId"],
        worker_id=claims["workerId"],
        attempt_id=claims["attemptId"],
    )
    return ReviewedValidationContext(citation=citation, prepared=material, grant=grant_check)


def _material_files(
    artifacts: LocalArtifactStore,
    request: NativeReviewedExecutionRequest,
) -> tuple[tuple[str, str, str, bytes], ...]:
    bundle = _object(artifacts, request.code.bundle_digest)
    bundle_model = _parse_model(bundle, NativeReviewedPythonBundle, "code-digest-mismatch")
    code_rows: list[tuple[str, str, str, bytes]] = [
        ("material/bundle", "bundle", request.code.bundle_digest, bundle)
    ]
    expected_code = entrypoint_source_path(request.code.entrypoint)
    if expected_code not in {item.path for item in bundle_model.files}:
        raise NativeReviewedPreparationError(
            "bundle does not contain the entrypoint module",
            code="entrypoint-mismatch",
        )
    for item in bundle_model.files:
        payload = _object(artifacts, item.digest)
        code_rows.append((f"material/code/{item.path}", "code", item.digest, payload))
    rows: list[tuple[str, str, str, bytes]] = code_rows
    for item in request.inputs:
        payload = _object(artifacts, item.digest)
        if len(payload) != item.size_bytes:
            raise NativeReviewedPreparationError(
                "input size does not match the request",
                code="input-digest-mismatch",
            )
        rows.append((f"material/inputs/{item.name}", "input", item.digest, payload))
    config = canonical_json(execution_object(request)).encode("utf-8")
    if content_digest(execution_object(request)) != request.config_digest:
        raise NativeReviewedPreparationError(
            "config digest does not match the execution object",
            code="config-digest-mismatch",
        )
    rows.append(("material/config.json", "config", request.config_digest, config))
    interpreter = _object(artifacts, request.environment.interpreter_digest)
    rows.append(
        (
            "material/environment/interpreter",
            "interpreter",
            request.environment.interpreter_digest,
            interpreter,
        )
    )
    lock = _object(artifacts, request.environment.dependency_lock_digest)
    rows.append(
        (
            "material/environment/dependency-lock",
            "dependency-lock",
            request.environment.dependency_lock_digest,
            lock,
        )
    )
    inventory = _object(artifacts, request.environment.inventory_digest)
    rows.append(
        (
            "material/environment/inventory",
            "inventory",
            request.environment.inventory_digest,
            inventory,
        )
    )
    review_digest = "sha256:" + request.code.review.citation_digest.removeprefix("jcs-sha256:")
    review = _object(artifacts, review_digest)
    rows.append(
        (
            "material/environment/review",
            "review",
            request.code.review.citation_digest,
            review,
        )
    )
    return tuple(rows)


def _object(artifacts: LocalArtifactStore, digest: str) -> bytes:
    try:
        record = artifacts.verify(digest)
        handle = artifacts.open(digest)
    except ArtifactNotFoundError:
        raise NativeReviewedPreparationError(
            "artifact object is missing",
            code="artifact-missing",
        ) from None
    except (ArtifactIntegrityError, ArtifactPathError, ArtifactStoreError):
        raise NativeReviewedPreparationError(
            "artifact object failed verification",
            code="artifact-integrity",
        ) from None
    try:
        payload = handle.read()
    finally:
        handle.close()
    if len(payload) != record.size_bytes or len(payload) > MAX_PUT_BYTES:
        raise NativeReviewedPreparationError(
            "artifact object failed verification",
            code="artifact-integrity",
        )
    if "sha256:" + hashlib.sha256(payload).hexdigest() != digest and not digest.startswith(
        "jcs-sha256:"
    ):
        raise NativeReviewedPreparationError(
            "artifact object failed verification",
            code="artifact-integrity",
        )
    return payload


def _receipt(
    request: NativeReviewedExecutionRequest,
    grant_id: str,
    files: tuple[tuple[str, str, str, bytes], ...],
    parsed: _Parsed,
) -> NativeReviewedPreparationReceipt:
    records: list[dict[str, object]] = []
    for path, role, digest, _payload in files:
        record: dict[str, object] = {
            "role": role,
            "relativePath": path,
            "digest": digest,
        }
        if role == "input":
            record["name"] = path.removeprefix("material/inputs/")
        records.append(record)
    document = {
        "apiVersion": NATIVE_REVIEWED_API_VERSION,
        "kind": "NativeReviewedPreparationReceipt",
        "profile": NATIVE_REVIEWED_PROFILE,
        "evidenceClass": "preparation",
        "requestDigest": request_digest(request),
        "planDigest": request.plan_digest,
        "decisionDigest": request.decision_digest,
        "configDigest": request.config_digest,
        "grantId": grant_id,
        "projectId": request.project_id,
        "revisionId": request.revision_id,
        "runId": request.run_id,
        "attemptId": request.attempt_id,
        "taskId": request.task_id,
        "workerId": request.worker_id,
        "authorizationEventId": request.authorization_event_id,
        "authorizationSequence": request.authorization_sequence,
        "platform": {
            "os": request.platform.os,
            "architecture": request.platform.architecture,
        },
        "bundleDigest": request.code.bundle_digest,
        "mediaType": request.code.media_type,
        "entrypoint": parsed.bundle.entrypoint,
        "inputDigests": [{"name": item.name, "digest": item.digest} for item in request.inputs],
        "interpreterDigest": request.environment.interpreter_digest,
        "pythonVersion": parsed.interpreter.python_version,
        "abi": parsed.interpreter.abi,
        "dependencyLockDigest": request.environment.dependency_lock_digest,
        "inventoryDigest": request.environment.inventory_digest,
        "interpreterIdentity": "byte-digest",
        "files": records,
        "outcome": "prepared",
        "reasonCode": "prepared",
        "launchAllowed": False,
        "sideEffects": dict(_ZERO_EFFECTS),
    }
    try:
        return NativeReviewedPreparationReceipt.model_validate(document)
    except ValidationError:
        raise NativeReviewedPreparationError(
            "preparation receipt is not valid",
            code="preparation-damaged",
        ) from None


def _inspect(workspace: Path, verified: _Verified) -> NativeReviewedPreparationDiagnosis:
    if _is_fresh(workspace):
        return _diagnosis(
            "preparation-incomplete",
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
        )
    try:
        present = _list_files(workspace)
    except NativeReviewedPreparationError as exc:
        return _diagnosis(
            _as_reason(exc.code),
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
        )
    if "receipt.json" not in present:
        return _diagnosis(
            "preparation-incomplete",
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
            checks=(PreparationCheck(role="receipt", status="missing"),),
        )
    try:
        stored = _read_receipt(workspace)
    except NativeReviewedPreparationError:
        return _diagnosis(
            "preparation-damaged",
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
            checks=(PreparationCheck(role="receipt", status="mismatch"),),
        )
    if stored != verified.receipt:
        return _diagnosis(
            "environment-mismatch",
            request_digest=verified.request_digest_value,
            receipt_digest=_document_digest(stored),
            expected_receipt_digest=_document_digest(verified.receipt),
            grant_id=verified.grant_id,
            checks=(PreparationCheck(role="receipt", status="mismatch"),),
        )
    expected_paths = {item.relative_path for item in verified.receipt.files}
    if present - expected_paths - {"receipt.json"}:
        return _diagnosis(
            "preparation-damaged",
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
            checks=(PreparationCheck(role="receipt", status="match"),),
        )
    checks: list[PreparationCheck] = [PreparationCheck(role="receipt", status="match")]
    mismatch: PreparationReasonCode | None = None
    missing = False
    payloads = verified.payloads()
    for record in verified.receipt.files:
        payload = _read_file(workspace, record.relative_path)
        if payload is None:
            missing = True
            checks.append(_check(record, "missing"))
            continue
        digest_matches = _payload_digest(record, payload) == record.digest
        bytes_match = payload == payloads[record.relative_path]
        if not digest_matches or not bytes_match:
            reason = _as_reason(_SUBSTITUTION[record.role])
            mismatch = mismatch or reason
            checks.append(_check(record, "mismatch"))
            continue
        checks.append(_check(record, "match"))
    if mismatch is not None:
        return _diagnosis(
            mismatch,
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
            checks=tuple(checks),
        )
    if missing:
        return _diagnosis(
            "preparation-incomplete",
            request_digest=verified.request_digest_value,
            grant_id=verified.grant_id,
            checks=tuple(checks),
        )
    digest = _document_digest(verified.receipt)
    return _diagnosis(
        "preparation-ready",
        request_digest=verified.request_digest_value,
        receipt_digest=digest,
        expected_receipt_digest=digest,
        grant_id=verified.grant_id,
        checks=tuple(checks),
    )


def _check(
    record: PreparedFileRecord,
    status: Literal["match", "missing", "mismatch"],
) -> PreparationCheck:
    if record.name is None:
        return PreparationCheck(role=record.role, status=status)
    return PreparationCheck(role=record.role, status=status, name=record.name)


def _payload_digest(record: PreparedFileRecord, payload: bytes) -> str:
    if record.role in {"config", "review"}:
        try:
            document = json.loads(payload)
        except json.JSONDecodeError:
            return ""
        if type(document) is not dict or canonical_json(document).encode("utf-8") != payload:
            return ""
        return content_digest(document)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write_workspace(workspace: Path, verified: _Verified) -> None:
    if workspace.is_symlink():
        raise NativeReviewedPreparationError(
            "workspace path is not a directory",
            code="preparation-damaged",
        )
    if not workspace.exists():
        parent = workspace.parent
        if parent.is_symlink() or not parent.is_dir():
            raise NativeReviewedPreparationError(
                "workspace parent is missing",
                code="preparation-incomplete",
            )
        os.mkdir(workspace, 0o700)
    os.chmod(workspace, 0o700)
    root_fd = os.open(workspace, _DIR_FLAGS)
    try:
        for relative, payload in verified.payloads().items():
            _write_relative(root_fd, relative, payload)
        _write_relative(root_fd, "receipt.json", _receipt_bytes(verified.receipt))
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def _write_relative(root_fd: int, relative: str, payload: bytes) -> None:
    parts = relative.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise NativeReviewedPreparationError(
            "material path is not relative",
            code="preparation-damaged",
        )
    parent = root_fd
    owned: list[int] = []
    try:
        for part in parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=parent)
            directory = os.open(part, _DIR_FLAGS, dir_fd=parent)
            owned.append(directory)
            os.fchmod(directory, 0o700)
            os.fsync(directory)
            parent = directory
        file_fd = os.open(parts[-1], _WRITE_FLAGS, 0o600, dir_fd=parent)
        owned.append(file_fd)
        os.fchmod(file_fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(file_fd, view)
            view = view[written:]
        os.fsync(file_fd)
        os.fsync(parent)
    except OSError:
        raise NativeReviewedPreparationError(
            "preparation workspace could not be written",
            code="preparation-damaged",
        ) from None
    finally:
        for descriptor in reversed(owned):
            os.close(descriptor)


def _read_receipt(workspace: Path) -> NativeReviewedPreparationReceipt:
    payload = _read_file(workspace, "receipt.json")
    if payload is None:
        raise NativeReviewedPreparationError(
            "preparation receipt is missing",
            code="preparation-incomplete",
        )
    try:
        document = _load_object(payload)
        return NativeReviewedPreparationReceipt.model_validate(document)
    except (NativeReviewedPreparationError, ValidationError):
        raise NativeReviewedPreparationError(
            "preparation receipt is not valid",
            code="preparation-damaged",
        ) from None


def _read_file(workspace: Path, relative: str) -> bytes | None:
    parts = relative.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise NativeReviewedPreparationError(
            "material path is not relative",
            code="preparation-damaged",
        )
    root_fd = os.open(workspace, _DIR_FLAGS)
    owned = [root_fd]
    try:
        parent = root_fd
        for part in parts[:-1]:
            try:
                parent = os.open(part, _DIR_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                return None
            owned.append(parent)
        try:
            file_fd = os.open(parts[-1], _READ_FLAGS, dir_fd=parent)
        except FileNotFoundError:
            return None
        owned.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PUT_BYTES:
            raise NativeReviewedPreparationError(
                "prepared file is not a regular object",
                code="preparation-damaged",
            )
        return os.read(file_fd, info.st_size)
    except OSError:
        raise NativeReviewedPreparationError(
            "prepared file could not be read",
            code="preparation-damaged",
        ) from None
    finally:
        for descriptor in reversed(owned):
            os.close(descriptor)


def _list_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise NativeReviewedPreparationError(
            "workspace path is not a directory",
            code="preparation-damaged",
        )
    found: set[str] = set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink():
            raise NativeReviewedPreparationError(
                "workspace contains a symlink",
                code="preparation-damaged",
            )
        kept: list[str] = []
        for name in dirnames:
            child = current_path / name
            if child.is_symlink():
                raise NativeReviewedPreparationError(
                    "workspace contains a symlink",
                    code="preparation-damaged",
                )
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            child = current_path / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise NativeReviewedPreparationError(
                    "workspace contains a non-regular file",
                    code="preparation-damaged",
                )
            found.add(child.relative_to(root).as_posix())
            if len(found) > 256:
                raise NativeReviewedPreparationError(
                    "workspace contains too many files",
                    code="preparation-damaged",
                )
    return found


def _is_fresh(workspace: Path) -> bool:
    if workspace.is_symlink():
        return False
    if not workspace.exists():
        return True
    if not workspace.is_dir():
        return False
    return next(workspace.iterdir(), None) is None


def _diagnosis(
    reason: PreparationReasonCode,
    *,
    checks: tuple[PreparationCheck, ...] = (),
    request_digest: str | None = None,
    receipt_digest: str | None = None,
    expected_receipt_digest: str | None = None,
    grant_id: str | None = None,
) -> NativeReviewedPreparationDiagnosis:
    document: dict[str, object] = {
        "apiVersion": NATIVE_REVIEWED_API_VERSION,
        "kind": "NativeReviewedPreparationDiagnosis",
        "profile": NATIVE_REVIEWED_PROFILE,
        "evidenceClass": "preparation-diagnosis",
        "outcome": diagnosis_outcome(reason),
        "reasonCode": reason,
        "launchAllowed": False,
        "interpreterIdentity": "byte-digest",
        "checks": [
            item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in checks
        ],
        "sideEffects": dict(_ZERO_EFFECTS),
    }
    if request_digest is not None:
        document["requestDigest"] = request_digest
    if receipt_digest is not None:
        document["receiptDigest"] = receipt_digest
    if expected_receipt_digest is not None:
        document["expectedReceiptDigest"] = expected_receipt_digest
    if grant_id is not None:
        document["grantId"] = grant_id
    return NativeReviewedPreparationDiagnosis.model_validate(document)


def _receipt_bytes(receipt: NativeReviewedPreparationReceipt) -> bytes:
    payload = receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    return canonical_json(payload).encode("utf-8")


def _document_digest(document: NativeReviewedPreparationReceipt) -> str:
    payload = document.model_dump(mode="json", by_alias=True, exclude_none=True)
    return content_digest(payload)


def _parse_model(payload: bytes, model: type[BaseModel], code: str) -> Any:
    try:
        document = _load_object(payload)
        return model.model_validate(document)
    except (NativeReviewedPreparationError, ValidationError):
        raise NativeReviewedPreparationError("material bytes are not valid", code=code) from None


def _load_object(payload: bytes) -> dict[str, object]:
    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key, value in pairs:
            if key in fields:
                raise NativeReviewedPreparationError(
                    "material has a duplicate field",
                    code="preparation-damaged",
                )
            fields[key] = value
        return fields

    if len(payload) > MAX_PUT_BYTES:
        raise NativeReviewedPreparationError(
            "material exceeds the byte limit",
            code="artifact-integrity",
        )
    try:
        document = json.loads(payload, object_pairs_hook=unique_fields)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise NativeReviewedPreparationError(
            "material is not JSON",
            code="preparation-damaged",
        ) from None
    if type(document) is not dict:
        raise NativeReviewedPreparationError(
            "material must be a JSON object",
            code="preparation-damaged",
        )
    return document


def _clock(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        raise NativeReviewedPreparationError(
            "clock must be timezone-aware",
            code="request-invalid",
        )
    return now.astimezone(UTC)


def _as_reason(code: str) -> PreparationReasonCode:
    if code not in _REASONS:
        return "binding-invalidated"
    return cast(PreparationReasonCode, code)


def load_bounded_file(path: Path, *, limit: int) -> bytes:
    """Read one regular file without following a symlink."""

    if path.is_symlink():
        raise NativeReviewedPreparationError(
            "input path is a symlink",
            code="source-path-rejected",
        )
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except OSError:
        raise NativeReviewedPreparationError(
            "input path could not be read",
            code="source-path-rejected",
        ) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise NativeReviewedPreparationError(
                "input path is not a bounded regular file",
                code="source-path-rejected",
            )
        return os.read(descriptor, info.st_size)
    finally:
        os.close(descriptor)
