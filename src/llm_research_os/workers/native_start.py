"""Controller-bound, journaled remote start recording with conservative replay."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import _ceiling_reason, request_digest
from llm_research_os.execution.native_reviewed_material import NativeReviewedInterpreterIdentity
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.native_claim import (
    NativeControllerContext,
    _append_bound,
    _event_id,
    _queue_rows,
    _require_binding,
)
from llm_research_os.workers.native_material import _read_bound, material_index
from llm_research_os.workers.native_start_documents import NativeStartReceipt, NativeStartRequest
from llm_research_os.workers.native_state import start_journal_name
from llm_research_os.workers.plane import WorkerPlane


def record_native_start(
    plane: WorkerPlane,
    *,
    context: NativeControllerContext | None,
    worker_id: str,
    grant_token: str,
    document: NativeStartRequest,
) -> NativeStartReceipt:
    """Caller holds output_lock. No process is created or observed by this endpoint."""
    if context is None:
        raise WorkerCallError(
            "native start requires controller context", code="native-context-required"
        )
    request = plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
    if _ceiling_reason(request) is not None or any(
        item.purpose == "checkpoint" for item in request.inputs
    ):
        raise WorkerCallError("native remote profile is unsupported", code="native-start-binding")
    _require_binding(plane, context, request)
    _, grant = plane.native_input_scope(worker_id=worker_id, grant_token=grant_token)
    fold = plane.rebuild()
    lease = fold.lease(document.lease_id)
    if (
        lease is None
        or lease.worker_id != worker_id
        or not lease.claimed
        or lease.status != "leased"
        or grant.consumed_lease_id != document.lease_id
        or (lease.task_id, lease.run_id, lease.attempt_id, lease.grant_id)
        != (request.task_id, request.run_id, request.attempt_id, grant.grant_id)
    ):
        raise WorkerCallError("native start lease differs", code="native-start-binding")
    index = material_index(plane, worker_id=worker_id, grant_token=grant_token)
    prepared = document.preparation
    identity = NativeReviewedInterpreterIdentity.model_validate_json(
        _read_bound(plane.artifacts, request.environment.interpreter_digest)
    )
    expected = {
        "requestDigest": request_digest(request),
        "planDigest": request.plan_digest,
        "decisionDigest": request.decision_digest,
        "configDigest": request.config_digest,
        "grantId": grant.grant_id,
        "projectId": request.project_id,
        "revisionId": request.revision_id,
        "runId": request.run_id,
        "attemptId": request.attempt_id,
        "taskId": request.task_id,
        "workerId": request.worker_id,
        "authorizationEventId": request.authorization_event_id,
        "authorizationSequence": request.authorization_sequence,
        "platform": request.platform.model_dump(mode="json", by_alias=True),
        "bundleDigest": request.code.bundle_digest,
        "mediaType": request.code.media_type,
        "entrypoint": request.code.entrypoint,
        "inputDigests": [{"name": item.name, "digest": item.digest} for item in request.inputs],
        "interpreterDigest": request.environment.interpreter_digest,
        "pythonVersion": identity.python_version,
        "abi": identity.abi,
        "dependencyLockDigest": request.environment.dependency_lock_digest,
        "inventoryDigest": request.environment.inventory_digest,
    }
    actual = prepared.model_dump(mode="json", by_alias=True, exclude_none=True)
    files = sorted(
        [
            {
                "relativePath": item.relative_path,
                "role": item.role,
                "digest": item.digest,
                **({"name": item.name} if item.name is not None else {}),
            }
            for item in index.files
        ],
        key=lambda item: item["relativePath"],
    )
    if (
        any(actual.get(key) != value for key, value in expected.items())
        or sorted(actual["files"], key=lambda item: item["relativePath"]) != files
    ):
        raise WorkerCallError("native preparation binding differs", code="native-start-binding")
    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
    for event_type, payload_data, attempt in _queue_rows(request):
        if plane.store.get_event(_event_id(request, event_type)) is None:
            raise WorkerCallError("native queue prefix is missing", code="native-run-conflict")
        _append_bound(run, plane, request, event_type, payload_data, attempt=attempt)
    snapshot = run.rebuild().snapshot
    if (
        plane.store.get_event(_event_id(request, "run.queued")) is None
        or snapshot is None
        or snapshot.status is not RunStatus.RUNNING
        or len(snapshot.attempts) != 1
        or snapshot.attempts[0].attempt_id != request.attempt_id
        or snapshot.attempts[0].status not in {AttemptStatus.QUEUED, AttemptStatus.RUNNING}
    ):
        raise WorkerCallError("native start Run differs", code="native-run-conflict")
    binding = {
        "workerId": worker_id,
        "grantId": grant.grant_id,
        "start": document.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    payload = canonical_json(binding).encode()
    if len(payload) > 16384:
        raise WorkerCallError("native start exceeds its bound", code="http-too-large")
    name = start_journal_name(plane.store.path, request)
    with _journal(
        plane.store.path.parent,
        name,
        payload,
        allow_new=snapshot.attempts[0].status is AttemptStatus.QUEUED,
    ):
        # Journal I/O cannot hide revocation, lease expiry, cancellation or plan drift.
        plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
        _require_binding(plane, context, request)
        current = run.rebuild().snapshot
        if (
            current is None
            or current.status is not RunStatus.RUNNING
            or len(current.attempts) != 1
            or current.attempts[0].status not in {AttemptStatus.QUEUED, AttemptStatus.RUNNING}
        ):
            raise WorkerCallError("native start outcome changed", code="native-run-conflict")
        _append_bound(run, plane, request, "attempt.started", {}, attempt=True)
        plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
        _require_binding(plane, context, request)
        current = run.rebuild().snapshot
        if (
            current is None
            or current.status is not RunStatus.RUNNING
            or current.attempts[0].status is not AttemptStatus.RUNNING
        ):
            raise WorkerCallError("native start outcome changed", code="native-run-conflict")
        event = plane.store.get_event(_event_id(request, "attempt.started"))
        if event is None:
            raise WorkerCallError("native start fact is missing", code="native-run-conflict")
        return NativeStartReceipt.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeStartReceipt",
                "leaseId": lease.lease_id,
                "bindingDigest": content_digest(binding),
                "eventId": event.event.id,
                "sequence": event.sequence,
                "launchAllowed": False,
            }
        )


@contextmanager
def _journal(parent: Path, name: str, payload: bytes, *, allow_new: bool) -> Iterator[None]:
    root = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        parent_info = os.fstat(root)
        if parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o022:
            raise WorkerCallError("native start parent is unsafe", code="native-start-journal")
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        except FileNotFoundError:
            if not allow_new:
                raise WorkerCallError(
                    "native start journal is missing", code="native-start-journal"
                ) from None
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
            )
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(root)
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 16384
            or os.read(descriptor, 16385) != payload
        ):
            raise WorkerCallError("native start journal differs", code="native-start-journal")
        # An exact prefix may have crashed before its original directory fsync.
        os.fsync(descriptor)
        os.fsync(root)
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(root)
