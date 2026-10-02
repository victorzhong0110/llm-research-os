"""One scoped native result and its durable Worker completion receipt."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from llm_research_os.artifacts.errors import ArtifactNotFoundError
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.storage.errors import DuplicateEventError, EventSequenceConflictError
from llm_research_os.workers.drafts import work_completed_draft
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.native_output_documents import NativeReviewedTaskOutput
from llm_research_os.workers.tokens import format_rfc3339

if TYPE_CHECKING:
    from llm_research_os.workers.control import LeaseRecord
    from llm_research_os.workers.plane import NativeOutputAuthority, WorkerPlane


def output_lock_path(database: Path) -> Path:
    name = hashlib.sha256(database.name.encode()).hexdigest()
    return database.parent / f"native-output-{name}.lock"


@contextmanager
def output_lock(database: Path) -> Iterator[None]:
    """Serialize publication across controllers; never wait on a remote caller's lock."""

    parent = os.open(database.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            output_lock_path(database).name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_size != 0
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise WorkerCallError("native output lock is unsafe", code="transfer-lock-invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerCallError(
                "native output publication is busy", code="transfer-busy"
            ) from None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def complete_native_output(
    plane: WorkerPlane,
    *,
    worker_id: str,
    grant_token: str,
    lease_id: str,
    digest: str,
    payload: bytes,
) -> dict[str, object]:
    """Verify bytes before publication; CAS head binds authorization to the completion fact."""

    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != digest:
        raise WorkerCallError("native output digest differs", code="transfer-digest-mismatch")
    for _ in range(3):
        authority = plane.authorize_native_output(
            worker_id=worker_id,
            grant_token=grant_token,
            lease_id=lease_id,
            digest=digest,
            size_bytes=len(payload),
        )
        document = _output_document(payload, authority.lease)
        result_digest = content_digest(document)
        if authority.lease.status == "completed":
            return _replay(plane, authority, digest, len(payload), result_digest)
        try:
            record = plane.artifacts.verify(digest)
        except ArtifactNotFoundError:
            space = os.statvfs(plane.artifacts.root)
            if space.f_bavail * space.f_frsize < len(payload) + 4096:
                raise WorkerCallError(
                    "native output has insufficient disk", code="transfer-disk-bound"
                ) from None
            record = plane.artifacts.put_bytes(payload, limit=authority.byte_limit)
        if record.digest != digest or record.size_bytes != len(payload):
            raise WorkerCallError("native output object differs", code="transfer-size-mismatch")
        # Recheck time, revocation, cancellation and head after any CAS I/O. A
        # concurrent fact between this snapshot and append forces full reauthorization.
        authority = plane.authorize_native_output(
            worker_id=worker_id,
            grant_token=grant_token,
            lease_id=lease_id,
            digest=digest,
            size_bytes=len(payload),
        )
        if authority.lease.status == "completed":
            return _replay(plane, authority, digest, len(payload), result_digest)
        try:
            stored = plane._control.append(
                work_completed_draft(
                    project_id=plane.project_id,
                    lease_id=lease_id,
                    worker_id=worker_id,
                    result_digest=result_digest,
                    artifact_digest=digest,
                    run_id=authority.lease.run_id,
                    attempt_id=authority.lease.attempt_id,
                    event_id=f"evt.work.completed.{lease_id}",
                    time=format_rfc3339(authority.authorized_at),
                    source=plane.source,
                    experiment_revision=plane.experiment_revision,
                ),
                expected_last_sequence=authority.head_sequence,
            )
        except (DuplicateEventError, EventSequenceConflictError):
            continue
        return {
            "digest": digest,
            "sizeBytes": len(payload),
            "resultDigest": result_digest,
            "leaseId": lease_id,
            "eventId": stored.event.id,
            "type": stored.event.type,
            "sequence": stored.sequence,
        }
    raise WorkerCallError("native completion did not settle", code="complete-conflict")


def _output_document(payload: bytes, lease: LeaseRecord) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (ValueError, RecursionError):
        raise WorkerCallError(
            "native output is invalid JSON", code="transfer-output-invalid"
        ) from None
    try:
        parsed = NativeReviewedTaskOutput.model_validate(document)
    except ValidationError:
        raise WorkerCallError("native output is invalid", code="transfer-output-invalid") from None
    if (parsed.task_id, parsed.run_id, parsed.attempt_id) != (
        lease.task_id,
        lease.run_id,
        lease.attempt_id,
    ):
        raise WorkerCallError(
            "native output is not bound to this task", code="transfer-output-invalid"
        )
    # Canonicalization also rejects non-finite values and unsupported JSON numbers.
    try:
        if canonical_json(document).encode() != payload:
            raise ValueError("output bytes are not canonical")
    except (ValueError, RecursionError):
        raise WorkerCallError(
            "native output is not canonicalizable", code="transfer-output-invalid"
        ) from None
    return cast(dict[str, Any], document)


def _replay(
    plane: WorkerPlane, authority: NativeOutputAuthority, digest: str, size: int, result_digest: str
) -> dict[str, object]:
    record = plane.artifacts.verify(digest)
    if record.size_bytes != size or authority.lease.result_digest != result_digest:
        raise WorkerCallError("completed output differs", code="complete-mismatch")
    stored = plane.store.get_event(f"evt.work.completed.{authority.lease.lease_id}")
    if stored is None:
        raise WorkerCallError("completion fact is missing", code="complete-missing")
    return {
        "digest": digest,
        "sizeBytes": size,
        "resultDigest": result_digest,
        "leaseId": authority.lease.lease_id,
        "eventId": stored.event.id,
        "type": stored.event.type,
        "sequence": stored.sequence,
    }
