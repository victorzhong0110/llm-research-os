"""Grant- and task-scoped file transfer between two artifact roots.

The controller names every byte by digest. This module never lists a CAS,
never follows a symlink, and never treats a local copy as two-host acceptance.
A reconnect continues the same lease. It does not start another task.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from llm_research_os.artifacts.errors import ArtifactStoreError
from llm_research_os.artifacts.store import MAX_WORKER_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.execution.errors import NativeTransferError
from llm_research_os.execution.native_reviewed_checkpoint import (
    NativeRestoreClaim,
    NativeRestoreError,
    verify_native_restore,
)
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.supervise import ExecutionIdentity

NATIVE_TRANSFER_IMPLEMENTATION = "native-scoped-transfer/v0alpha1"
MAX_TRANSFER_FILES = 32
MAX_TRANSFER_FILE_BYTES = MAX_WORKER_PUT_BYTES
MAX_TRANSFER_TOTAL_BYTES = MAX_WORKER_PUT_BYTES
MAX_TRANSFER_RETRIES = 3
MAX_TRANSFER_MANIFEST_BYTES = 65_536
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,63}){0,7}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)

TransferObservation = Literal["success", "failure", "stopped", "unknown", "cancel-requested"]
TransferStatus = Literal["complete", "incomplete", "refused"]
TransferDirection = Literal["input", "output"]
_OBSERVATIONS = frozenset({"success", "failure", "stopped", "unknown", "cancel-requested"})
_FAULTS: dict[str, TransferObservation] = {
    "disconnect-before-claim": "unknown",
    "tunnel-loss": "unknown",
    "controller-restart": "unknown",
    "worker-restart": "unknown",
    "interrupted-upload": "unknown",
    "lost-completion": "unknown",
    "disconnected-cancel": "cancel-requested",
    "observation-unavailable": "unknown",
}
_GPU_PROFILES = frozenset({"gpu-oci", "macos-mps"})
INTERRUPTED = "transfer-interrupted"


@dataclass(frozen=True, slots=True)
class TransferFile:
    relative_path: str
    digest: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TransferManifest:
    grant_id: str
    task_id: str
    run_id: str
    attempt_id: str
    direction: TransferDirection
    files: tuple[TransferFile, ...]


@dataclass(frozen=True, slots=True)
class TransferReceipt:
    manifest_digest: str
    grant_id: str
    task_id: str
    run_id: str
    attempt_id: str
    direction: TransferDirection
    lease_id: str | None
    status: TransferStatus
    observation: TransferObservation
    completed: tuple[str, ...]
    attempts: int
    starts: int
    runtime: str
    process_observation: Literal["present", "unavailable"]
    process_pid: int | None

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "NativeScopedTransferReceipt",
            "implementation": NATIVE_TRANSFER_IMPLEMENTATION,
            "runtime": self.runtime,
            "manifestDigest": self.manifest_digest,
            "inputDigest": self.manifest_digest,
            "grantId": self.grant_id,
            "taskId": self.task_id,
            "runId": self.run_id,
            "attemptId": self.attempt_id,
            "direction": self.direction,
            "leaseId": self.lease_id,
            "status": self.status,
            "observation": self.observation,
            "completed": list(self.completed),
            "attempts": self.attempts,
            "starts": self.starts,
            "processObservation": self.process_observation,
            "processPid": self.process_pid,
            "gpuProfile": "pending-live",
        }


@dataclass(frozen=True, slots=True)
class FaultRecord:
    kind: str
    observation: TransferObservation
    starts_task: bool

    def as_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "observation": self.observation,
            "startsTask": self.starts_task,
        }


class TransferHooks:
    """Test seam. Production callers leave the default in place."""

    def before_file(self, relative_path: str) -> None:
        del relative_path


def fault_kinds() -> tuple[str, ...]:
    return tuple(_FAULTS)


def classify_two_host_fault(kind: str) -> FaultRecord:
    """Map a transport fault to an observation that cannot collapse into success."""

    observation = _FAULTS.get(kind)
    if observation is None:
        raise NativeTransferError("transfer fault is not recognized", code="transfer-fault-unknown")
    if observation in {"success", "failure", "stopped"}:
        raise NativeTransferError("transfer fault collapsed", code="transfer-fault-collapsed")
    return FaultRecord(kind=kind, observation=observation, starts_task=False)


def gpu_profile_evidence(profile: str) -> str:
    """Supported GPU profiles stay pending-live until an authorized host is used."""

    if profile not in _GPU_PROFILES:
        raise NativeTransferError(
            "GPU profile is not a supported transfer target",
            code="transfer-profile-unsupported",
        )
    return "pending-live"


def runtime_identity() -> str:
    return f"{platform.system().lower()}/{platform.machine()}"


def manifest_from_document(document: object) -> TransferManifest:
    if type(document) is not dict:
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    body = cast(dict[str, object], document)
    direction = body.get("direction")
    if direction not in {"input", "output"}:
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    files_value = body.get("files")
    if type(files_value) is not list or not files_value or len(files_value) > MAX_TRANSFER_FILES:
        raise NativeTransferError("transfer file count is outside its bound", code="transfer-bound")
    files: list[TransferFile] = []
    seen: set[str] = set()
    total = 0
    for item in files_value:
        parsed = _file(item)
        if parsed.relative_path in seen:
            raise NativeTransferError(
                "transfer path is not authorized",
                code="transfer-path-unauthorized",
            )
        seen.add(parsed.relative_path)
        total += parsed.size_bytes
        if total > MAX_TRANSFER_TOTAL_BYTES:
            raise NativeTransferError(
                "transfer byte total is outside its bound",
                code="transfer-bound",
            )
        files.append(parsed)
    manifest = TransferManifest(
        grant_id=_identifier(body.get("grantId")),
        task_id=_identifier(body.get("taskId")),
        run_id=_identifier(body.get("runId")),
        attempt_id=_identifier(body.get("attemptId")),
        direction=cast(TransferDirection, direction),
        files=tuple(sorted(files, key=lambda entry: entry.relative_path)),
    )
    return manifest


def load_manifest(path: Path) -> TransferManifest:
    if path.is_symlink():
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except OSError:
        raise NativeTransferError(
            "transfer manifest is invalid",
            code="transfer-manifest-invalid",
        ) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TRANSFER_MANIFEST_BYTES:
            raise NativeTransferError(
                "transfer manifest is invalid",
                code="transfer-manifest-invalid",
            )
        raw = os.read(descriptor, info.st_size)
    finally:
        os.close(descriptor)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NativeTransferError(
            "transfer manifest is invalid",
            code="transfer-manifest-invalid",
        ) from exc
    return manifest_from_document(document)


def manifest_digest(manifest: TransferManifest) -> str:
    return content_digest(
        {
            "attemptId": manifest.attempt_id,
            "direction": manifest.direction,
            "files": [
                {
                    "digest": item.digest,
                    "path": item.relative_path,
                    "sizeBytes": item.size_bytes,
                }
                for item in manifest.files
            ],
            "grantId": manifest.grant_id,
            "implementation": NATIVE_TRANSFER_IMPLEMENTATION,
            "runId": manifest.run_id,
            "taskId": manifest.task_id,
        }
    )


def claim_for_transfer(
    journal_path: Path,
    manifest: TransferManifest,
    *,
    lease_id: str,
) -> TransferReceipt:
    """Record the single task start for this lease. A repeat is the same start."""

    _identifier(lease_id)
    journal = _load_or_create(journal_path, manifest)
    _require_same_manifest(journal, manifest)
    if journal.lease_id not in {None, lease_id}:
        raise NativeTransferError(
            "reconnect cannot start a second task",
            code="transfer-duplicate-start",
        )
    if journal.starts > 1:
        raise NativeTransferError(
            "reconnect cannot start a second task",
            code="transfer-duplicate-start",
        )
    if journal.starts == 0:
        journal.starts = 1
        journal.lease_id = lease_id
        _save(journal_path, journal)
    return _receipt(journal)


def record_fault(
    journal_path: Path,
    manifest: TransferManifest,
    kind: str,
) -> TransferReceipt:
    """Apply a fault without incrementing the task start count."""

    fault = classify_two_host_fault(kind)
    journal = _load_or_create(journal_path, manifest)
    _require_same_manifest(journal, manifest)
    if kind == "lost-completion" and journal.status == "complete":
        return _receipt(journal)
    before = journal.starts
    journal.observation = fault.observation
    if journal.starts != before or fault.starts_task:
        raise NativeTransferError(
            "reconnect cannot start a second task",
            code="transfer-duplicate-start",
        )
    _save(journal_path, journal)
    return _receipt(journal)


def record_observation(receipt: TransferReceipt, observation: str) -> TransferReceipt:
    if observation not in _OBSERVATIONS:
        raise NativeTransferError("transfer observation is invalid", code="transfer-observation")
    return TransferReceipt(
        manifest_digest=receipt.manifest_digest,
        grant_id=receipt.grant_id,
        task_id=receipt.task_id,
        run_id=receipt.run_id,
        attempt_id=receipt.attempt_id,
        direction=receipt.direction,
        lease_id=receipt.lease_id,
        status=receipt.status,
        observation=cast(TransferObservation, observation),
        completed=receipt.completed,
        attempts=receipt.attempts,
        starts=receipt.starts,
        runtime=receipt.runtime,
        process_observation=receipt.process_observation,
        process_pid=receipt.process_pid,
    )


def attach_process_observation(
    receipt: TransferReceipt,
    identity: ExecutionIdentity | None,
) -> TransferReceipt:
    """Missing process identity stays unknown. It is not failure or success."""

    if identity is None or identity.pid is None or not identity.start_token:
        return TransferReceipt(
            manifest_digest=receipt.manifest_digest,
            grant_id=receipt.grant_id,
            task_id=receipt.task_id,
            run_id=receipt.run_id,
            attempt_id=receipt.attempt_id,
            direction=receipt.direction,
            lease_id=receipt.lease_id,
            status=receipt.status,
            observation="unknown",
            completed=receipt.completed,
            attempts=receipt.attempts,
            starts=receipt.starts,
            runtime=receipt.runtime,
            process_observation="unavailable",
            process_pid=None,
        )
    return TransferReceipt(
        manifest_digest=receipt.manifest_digest,
        grant_id=receipt.grant_id,
        task_id=receipt.task_id,
        run_id=receipt.run_id,
        attempt_id=receipt.attempt_id,
        direction=receipt.direction,
        lease_id=receipt.lease_id,
        status=receipt.status,
        observation=receipt.observation,
        completed=receipt.completed,
        attempts=receipt.attempts,
        starts=receipt.starts,
        runtime=receipt.runtime,
        process_observation="present",
        process_pid=identity.pid,
    )


def stage_scoped_inputs(
    *,
    manifest: TransferManifest,
    source: LocalArtifactStore,
    destination: Path,
    journal_path: Path,
    lease_id: str | None = None,
    hooks: TransferHooks | None = None,
) -> TransferReceipt:
    if manifest.direction != "input":
        raise NativeTransferError(
            "transfer direction does not match the operation",
            code="transfer-direction-mismatch",
        )
    _prepare_directory(destination)
    _require_disk(destination, _remaining_bytes(manifest, ()))

    def read_file(item: TransferFile) -> bytes:
        return _read_store(source, item)

    def write_file(item: TransferFile, payload: bytes) -> None:
        _place_file(destination, item.relative_path, payload)

    return _transfer(
        manifest=manifest,
        journal_path=journal_path,
        lease_id=lease_id,
        hooks=hooks or TransferHooks(),
        read_file=read_file,
        write_file=write_file,
        already=lambda item: _existing_file_digest(destination, item),
    )


def export_scoped_outputs(
    *,
    manifest: TransferManifest,
    source_dir: Path,
    destination: LocalArtifactStore,
    journal_path: Path,
    lease_id: str | None = None,
    hooks: TransferHooks | None = None,
) -> TransferReceipt:
    if manifest.direction != "output":
        raise NativeTransferError(
            "transfer direction does not match the operation",
            code="transfer-direction-mismatch",
        )
    _reject_unexpected(source_dir, manifest)

    def read_file(item: TransferFile) -> bytes:
        return _read_tree(source_dir, item)

    def write_file(item: TransferFile, payload: bytes) -> None:
        record = destination.put_bytes(payload, limit=MAX_TRANSFER_FILE_BYTES)
        if record.digest != item.digest or record.size_bytes != item.size_bytes:
            raise NativeTransferError(
                "transferred bytes do not match the manifest",
                code="transfer-integrity-mismatch",
            )

    return _transfer(
        manifest=manifest,
        journal_path=journal_path,
        lease_id=lease_id,
        hooks=hooks or TransferHooks(),
        read_file=read_file,
        write_file=write_file,
        already=lambda item: _existing_store_digest(destination, item),
    )


def deliver_verified_checkpoint(
    *,
    claim: NativeRestoreClaim | None,
    source: NativeReviewedExecutionRequest | None,
    target: NativeReviewedExecutionRequest | None,
    plane: WorkerPlane | None,
    destination: Path,
    journal_path: Path,
) -> TransferReceipt:
    """Copy one verified checkpoint into the designated Attempt, or refuse."""

    if claim is None or source is None or target is None or plane is None:
        raise NativeTransferError(
            "checkpoint restore is unsupported",
            code="transfer-restore-unsupported",
        )
    if claim.mode not in {"full-state", "adapter-only"}:
        raise NativeTransferError(
            "checkpoint restore is unsupported",
            code="transfer-restore-unsupported",
        )
    try:
        verify_native_restore(claim=claim, source=source, target=target, plane=plane)
    except NativeRestoreError as exc:
        raise NativeTransferError(
            "checkpoint restore is unsupported",
            code="transfer-restore-unsupported",
        ) from exc
    selected = next(item for item in target.inputs if item.name == claim.checkpoint_input)
    manifest = manifest_from_document(
        {
            "grantId": target.worker_id,
            "taskId": target.task_id,
            "runId": target.run_id,
            "attemptId": target.attempt_id,
            "direction": "input",
            "files": [
                {
                    "path": claim.checkpoint_input,
                    "digest": claim.artifact_digest,
                    "sizeBytes": selected.size_bytes,
                }
            ],
        }
    )
    return stage_scoped_inputs(
        manifest=manifest,
        source=plane.artifacts,
        destination=destination,
        journal_path=journal_path,
        lease_id=None,
    )


def _transfer(
    *,
    manifest: TransferManifest,
    journal_path: Path,
    lease_id: str | None,
    hooks: TransferHooks,
    read_file: Callable[[TransferFile], bytes],
    write_file: Callable[[TransferFile, bytes], None],
    already: Callable[[TransferFile], str | None],
) -> TransferReceipt:
    journal = _load_or_create(journal_path, manifest)
    _require_same_manifest(journal, manifest)
    if lease_id is not None:
        _identifier(lease_id)
        if journal.lease_id not in {None, lease_id}:
            raise NativeTransferError(
                "reconnect cannot start a second task",
                code="transfer-duplicate-start",
            )
        journal.lease_id = lease_id
    if journal.status == "complete":
        for item in manifest.files:
            if already(item) != item.digest:
                raise NativeTransferError(
                    "transferred bytes do not match the manifest",
                    code="transfer-integrity-mismatch",
                )
        return _receipt(journal)
    if journal.attempts >= MAX_TRANSFER_RETRIES:
        raise NativeTransferError("transfer retries are exhausted", code="transfer-retry-exhausted")
    journal.attempts += 1
    starts_before = journal.starts
    try:
        for item in manifest.files:
            existing = already(item)
            if existing == item.digest:
                if item.relative_path not in journal.completed:
                    journal.completed.append(item.relative_path)
                continue
            if existing is not None:
                raise NativeTransferError(
                    "transferred bytes do not match the manifest",
                    code="transfer-integrity-mismatch",
                )
            hooks.before_file(item.relative_path)
            payload = read_file(item)
            _require_payload(item, payload)
            write_file(item, payload)
            journal.completed.append(item.relative_path)
        journal.status = "complete"
    except NativeTransferError as exc:
        if exc.code != INTERRUPTED:
            _save(journal_path, journal)
            raise
        journal.status = "incomplete"
        journal.observation = "unknown"
    if journal.starts != starts_before:
        raise NativeTransferError(
            "reconnect cannot start a second task",
            code="transfer-duplicate-start",
        )
    _save(journal_path, journal)
    return _receipt(journal)


def _file(value: object) -> TransferFile:
    if type(value) is not dict:
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    body = cast(dict[str, object], value)
    path = body.get("path")
    digest = body.get("digest")
    size = body.get("sizeBytes")
    if type(path) is not str or _PATH.fullmatch(path) is None or path.startswith("/"):
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        )
    if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    if type(size) is not int or isinstance(size, bool):
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    if size < 0 or size > MAX_TRANSFER_FILE_BYTES:
        raise NativeTransferError("transfer file size is outside its bound", code="transfer-bound")
    return TransferFile(relative_path=path, digest=digest, size_bytes=size)


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise NativeTransferError("transfer manifest is invalid", code="transfer-manifest-invalid")
    return value


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_payload(item: TransferFile, payload: bytes) -> None:
    if len(payload) != item.size_bytes or _digest(payload) != item.digest:
        raise NativeTransferError(
            "transferred bytes do not match the manifest",
            code="transfer-integrity-mismatch",
        )


def _read_store(source: LocalArtifactStore, item: TransferFile) -> bytes:
    try:
        record = source.verify(item.digest)
        if record.size_bytes != item.size_bytes:
            raise NativeTransferError(
                "transferred bytes do not match the manifest",
                code="transfer-integrity-mismatch",
            )
        with source.open(item.digest) as handle:
            payload = handle.read(item.size_bytes + 1)
    except NativeTransferError:
        raise
    except (ArtifactStoreError, OSError) as exc:
        raise NativeTransferError(
            "authorized object is not available",
            code="transfer-object-missing",
        ) from exc
    return payload


def _read_tree(root: Path, item: TransferFile) -> bytes:
    path = _contained(root, item.relative_path)
    if path is None or not path.is_file() or path.is_symlink():
        raise NativeTransferError(
            "authorized object is not available",
            code="transfer-object-missing",
        )
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except OSError as exc:
        raise NativeTransferError(
            "authorized object is not available",
            code="transfer-object-missing",
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != item.size_bytes:
            raise NativeTransferError(
                "transferred bytes do not match the manifest",
                code="transfer-integrity-mismatch",
            )
        if info.st_size > MAX_TRANSFER_FILE_BYTES:
            raise NativeTransferError(
                "transfer file size is outside its bound",
                code="transfer-bound",
            )
        return os.read(descriptor, info.st_size)
    finally:
        os.close(descriptor)


def _existing_file_digest(root: Path, item: TransferFile) -> str | None:
    path = _contained(root, item.relative_path)
    if path is None or not path.exists():
        return None
    return _digest(_read_tree(root, item))


def _existing_store_digest(store: LocalArtifactStore, item: TransferFile) -> str | None:
    try:
        record = store.verify(item.digest)
    except (ArtifactStoreError, OSError):
        return None
    if record.size_bytes != item.size_bytes:
        raise NativeTransferError(
            "transferred bytes do not match the manifest",
            code="transfer-integrity-mismatch",
        )
    return item.digest


def _place_file(root: Path, relative: str, payload: bytes) -> None:
    _require_disk(root, len(payload))
    path = _contained(root, relative)
    if path is None:
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        )
    if path.is_symlink():
        raise NativeTransferError("transfer path is a symlink", code="transfer-symlink-forbidden")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        )
    parent.mkdir(mode=0o700, exist_ok=True)
    if path.exists():
        raise NativeTransferError(
            "transferred bytes do not match the manifest",
            code="transfer-integrity-mismatch",
        )
    try:
        descriptor = os.open(path, _WRITE_FLAGS, 0o600)
    except OSError as exc:
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        ) from exc
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_directory(root: Path) -> None:
    if root.is_symlink():
        raise NativeTransferError("transfer path is a symlink", code="transfer-symlink-forbidden")
    try:
        root.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        ) from exc
    if root.is_symlink() or not root.is_dir():
        raise NativeTransferError(
            "transfer path is not authorized",
            code="transfer-path-unauthorized",
        )


def _contained(root: Path, relative: str) -> Path | None:
    if _PATH.fullmatch(relative) is None:
        return None
    current = root
    if current.is_symlink():
        raise NativeTransferError("transfer path is a symlink", code="transfer-symlink-forbidden")
    parts = relative.split("/")
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise NativeTransferError(
                "transfer path is a symlink",
                code="transfer-symlink-forbidden",
            )
        if current.exists() and not current.is_dir():
            raise NativeTransferError(
                "transfer path is not authorized",
                code="transfer-path-unauthorized",
            )
        current.mkdir(mode=0o700, exist_ok=True)
    return current / parts[-1]


def _reject_unexpected(root: Path, manifest: TransferManifest) -> None:
    _prepare_directory(root)
    allowed = {item.relative_path for item in manifest.files}
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        kept: list[str] = []
        for name in dirnames:
            child = Path(dirpath) / name
            if child.is_symlink():
                raise NativeTransferError(
                    "transfer path is a symlink",
                    code="transfer-symlink-forbidden",
                )
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            child = Path(dirpath) / name
            if child.is_symlink():
                raise NativeTransferError(
                    "transfer path is a symlink",
                    code="transfer-symlink-forbidden",
                )
            if not child.is_file():
                raise NativeTransferError(
                    "transfer path is not authorized",
                    code="transfer-path-unauthorized",
                )
            relative = child.relative_to(root).as_posix()
            if relative not in allowed:
                raise NativeTransferError(
                    "transfer path is not authorized",
                    code="transfer-path-unauthorized",
                )
            found.append(relative)
    if len(found) > MAX_TRANSFER_FILES:
        raise NativeTransferError("transfer file count is outside its bound", code="transfer-bound")


def _require_disk(root: Path, needed: int) -> None:
    if needed < 0:
        raise NativeTransferError("transfer byte total is outside its bound", code="transfer-bound")
    target = root if root.exists() else root.parent
    free = shutil.disk_usage(target).free
    if free < needed + 4096:
        raise NativeTransferError(
            "temporary disk is below the transfer bound",
            code="transfer-disk-exhausted",
        )


def _remaining_bytes(manifest: TransferManifest, completed: tuple[str, ...] | list[str]) -> int:
    done = set(completed)
    return sum(item.size_bytes for item in manifest.files if item.relative_path not in done)


@dataclass
class _Journal:
    manifest_digest: str
    grant_id: str
    task_id: str
    run_id: str
    attempt_id: str
    direction: TransferDirection
    lease_id: str | None
    status: TransferStatus
    observation: TransferObservation
    completed: list[str]
    attempts: int
    starts: int
    process_observation: Literal["present", "unavailable"]
    process_pid: int | None


def _load_or_create(path: Path, manifest: TransferManifest) -> _Journal:
    if not path.exists():
        return _Journal(
            manifest_digest=manifest_digest(manifest),
            grant_id=manifest.grant_id,
            task_id=manifest.task_id,
            run_id=manifest.run_id,
            attempt_id=manifest.attempt_id,
            direction=manifest.direction,
            lease_id=None,
            status="incomplete",
            observation="unknown",
            completed=[],
            attempts=0,
            starts=0,
            process_observation="unavailable",
            process_pid=None,
        )
    if path.is_symlink():
        raise NativeTransferError("transfer journal is invalid", code="transfer-journal-invalid")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeTransferError(
            "transfer journal is invalid",
            code="transfer-journal-invalid",
        ) from exc
    if type(document) is not dict:
        raise NativeTransferError("transfer journal is invalid", code="transfer-journal-invalid")
    body = cast(dict[str, object], document)
    try:
        journal = _journal_from(body)
    except (KeyError, TypeError, ValueError) as exc:
        raise NativeTransferError(
            "transfer journal is invalid",
            code="transfer-journal-invalid",
        ) from exc
    return journal


def _journal_from(body: dict[str, object]) -> _Journal:
    status = body["status"]
    observation = body["observation"]
    direction = body["direction"]
    process_observation = body["processObservation"]
    if status not in {"complete", "incomplete", "refused"}:
        raise ValueError(status)
    if observation not in _OBSERVATIONS:
        raise ValueError(observation)
    if direction not in {"input", "output"}:
        raise ValueError(direction)
    if process_observation not in {"present", "unavailable"}:
        raise ValueError(process_observation)
    completed = body["completed"]
    attempts = body["attempts"]
    starts = body["starts"]
    if type(completed) is not list or any(type(item) is not str for item in completed):
        raise ValueError(completed)
    if type(attempts) is not int or type(starts) is not int or isinstance(attempts, bool):
        raise ValueError(attempts)
    lease = body["leaseId"]
    pid = body["processPid"]
    if lease is not None and type(lease) is not str:
        raise ValueError(lease)
    if pid is not None and type(pid) is not int:
        raise ValueError(pid)
    return _Journal(
        manifest_digest=_identifier_digest(body["manifestDigest"]),
        grant_id=_identifier(body["grantId"]),
        task_id=_identifier(body["taskId"]),
        run_id=_identifier(body["runId"]),
        attempt_id=_identifier(body["attemptId"]),
        direction=cast(TransferDirection, direction),
        lease_id=lease,
        status=cast(TransferStatus, status),
        observation=cast(TransferObservation, observation),
        completed=list(cast(list[str], completed)),
        attempts=attempts,
        starts=starts,
        process_observation=cast(Literal["present", "unavailable"], process_observation),
        process_pid=pid,
    )


def _identifier_digest(value: object) -> str:
    if type(value) is not str or not value.startswith("jcs-sha256:") or len(value) != 75:
        raise NativeTransferError("transfer journal is invalid", code="transfer-journal-invalid")
    return value


def _require_same_manifest(journal: _Journal, manifest: TransferManifest) -> None:
    if (
        journal.manifest_digest != manifest_digest(manifest)
        or journal.grant_id != manifest.grant_id
        or journal.task_id != manifest.task_id
        or journal.run_id != manifest.run_id
        or journal.attempt_id != manifest.attempt_id
        or journal.direction != manifest.direction
    ):
        raise NativeTransferError(
            "transfer journal belongs to another manifest",
            code="transfer-manifest-mismatch",
        )


def _save(path: Path, journal: _Journal) -> None:
    if path.is_symlink():
        raise NativeTransferError("transfer journal is invalid", code="transfer-journal-invalid")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(_journal_document(journal), ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _journal_document(journal: _Journal) -> dict[str, object]:
    return {
        "attemptId": journal.attempt_id,
        "attempts": journal.attempts,
        "completed": journal.completed,
        "direction": journal.direction,
        "grantId": journal.grant_id,
        "leaseId": journal.lease_id,
        "manifestDigest": journal.manifest_digest,
        "observation": journal.observation,
        "processObservation": journal.process_observation,
        "processPid": journal.process_pid,
        "runId": journal.run_id,
        "starts": journal.starts,
        "status": journal.status,
        "taskId": journal.task_id,
    }


def _receipt(journal: _Journal) -> TransferReceipt:
    return TransferReceipt(
        manifest_digest=journal.manifest_digest,
        grant_id=journal.grant_id,
        task_id=journal.task_id,
        run_id=journal.run_id,
        attempt_id=journal.attempt_id,
        direction=journal.direction,
        lease_id=journal.lease_id,
        status=journal.status,
        observation=journal.observation,
        completed=tuple(journal.completed),
        attempts=journal.attempts,
        starts=journal.starts,
        runtime=runtime_identity(),
        process_observation=journal.process_observation,
        process_pid=journal.process_pid,
    )
