"""Durable Worker-local preparation from pinned, grant-scoped native material."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import secrets
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from llm_research_os.artifacts.errors import ArtifactNotFoundError
from llm_research_os.artifacts.models import ArtifactRecord
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json
from llm_research_os.execution.errors import NativeReviewedPreparationError, NativeTransferError
from llm_research_os.execution.native_reviewed import _ceiling_reason, execution_object
from llm_research_os.execution.native_reviewed_preparation import (
    _inspect,
    _is_fresh,
    _parsed_material,
    _read_file,
    _receipt,
    _receipt_bytes,
    _require_host,
    _Verified,
    _write_relative,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NativeReviewedPreparationReceipt,
)
from llm_research_os.execution.native_transfer import (
    INTERRUPTED,
    MAX_TRANSFER_FILES,
    _directory,
    _require_disk,
    manifest_from_document,
    stage_scoped_inputs,
)
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_material_documents import (
    NativeMaterialFile,
    NativeMaterialIndex,
)

_PREPARATION_LOCK = threading.Lock()


class _RemoteSource(LocalArtifactStore):
    def __init__(self, store: LocalArtifactStore, client: WorkerClient, index: NativeMaterialIndex):
        super().__init__(store.root)
        self.store = store
        self.client = client
        self.files = {item.byte_digest: item for item in index.files}

    def open(self, digest: str) -> BinaryIO:
        return self.store.open(digest)

    def verify(self, digest: str) -> ArtifactRecord:
        item = self.files.get(digest)
        if item is None:
            raise NativeTransferError("material is not indexed", code="transfer-path-unauthorized")
        try:
            with self.open(digest) as handle:
                if os.fstat(handle.fileno()).st_size != item.size_bytes:
                    raise NativeTransferError(
                        "cached material differs", code="transfer-integrity-mismatch"
                    )
        except ArtifactNotFoundError:
            try:
                payload = self.client.fetch_native_input(digest=digest, size_bytes=item.size_bytes)
            except WorkerError as exc:
                code = INTERRUPTED if exc.code == "http-disconnect" else exc.code
                raise NativeTransferError(
                    "material fetch refused or interrupted", code=code
                ) from None
            if len(payload) != item.size_bytes or _digest(payload) != digest:
                raise NativeTransferError(
                    "downloaded material differs", code="transfer-integrity-mismatch"
                ) from None
            _require_disk(self.root, len(payload))
            self.store.put_bytes(payload)
        # A corrupt existing object is never repaired or replaced by a download.
        return self.store.verify(digest)


def prepare_remote_native(
    client: WorkerClient,
    *,
    artifacts: LocalArtifactStore,
    workspace: Path,
    staging_root: Path,
) -> NativeReviewedPreparationReceipt:
    """Resume bounded transfers, verify this host and atomically publish preparation only."""

    index = NativeMaterialIndex.model_validate(client.fetch_native_material_index())
    reason = _ceiling_reason(index.request)
    if reason is not None:
        raise NativeReviewedPreparationError("required isolation is not enforced", code=reason)
    if any(item.purpose == "checkpoint" for item in index.request.inputs):
        raise NativeTransferError(
            "remote restore verification is not integrated", code="transfer-restore-unsupported"
        )
    workspace, staging_root = workspace.absolute(), staging_root.absolute()
    roots = (workspace, staging_root, artifacts.root)
    if any(a.is_relative_to(b) for i, a in enumerate(roots) for j, b in enumerate(roots) if i != j):
        raise NativeTransferError("preparation roots overlap", code="transfer-path-unauthorized")
    with _workspace_lock(workspace), _directory(staging_root, create=True) as stage_fd:
        _private_directory(stage_fd)
        source = _RemoteSource(artifacts, client, index)
        # The namespace binds the complete index, including grant and all byte sizes.
        namespace = hashlib.sha256(
            canonical_json(index.model_dump(mode="json", by_alias=True, exclude_none=True)).encode()
        ).hexdigest()
        state = staging_root / namespace
        files = sorted(index.files, key=lambda item: item.relative_path)
        for offset in range(0, len(files), MAX_TRANSFER_FILES):
            group = files[offset : offset + MAX_TRANSFER_FILES]
            manifest = manifest_from_document(
                {
                    "grantId": index.grant_id,
                    "taskId": index.request.task_id,
                    "runId": index.request.run_id,
                    "attemptId": index.request.attempt_id,
                    "direction": "input",
                    "files": [
                        {
                            "path": _opaque(item),
                            "digest": item.byte_digest,
                            "sizeBytes": item.size_bytes,
                        }
                        for item in group
                    ],
                }
            )
            receipt = stage_scoped_inputs(
                manifest=manifest,
                source=source,
                destination=state / f"batch-{offset // MAX_TRANSFER_FILES}",
                journal_path=state / f"journal-{offset // MAX_TRANSFER_FILES}.json",
            )
            if receipt.status != "complete":
                raise NativeTransferError("preparation transfer is incomplete", code=INTERRUPTED)
        rows: list[tuple[str, str, str, bytes]] = []
        for number, item in enumerate(files):
            payload = _read_file(state / f"batch-{number // MAX_TRANSFER_FILES}", _opaque(item))
            if (
                payload is None
                or len(payload) != item.size_bytes
                or _digest(payload) != item.byte_digest
            ):
                raise NativeTransferError(
                    "staged material differs", code="transfer-integrity-mismatch"
                )
            rows.append((item.relative_path, item.role, item.digest, payload))
        material = tuple(rows)
        parsed = _parsed_material(index.request, material)
        _require_host(parsed.interpreter)
        expected_code = {f"material/code/{item.path}": item.digest for item in parsed.bundle.files}
        actual_code = {path: digest for path, role, digest, _ in material if role == "code"}
        if expected_code != actual_code:
            raise NativeReviewedPreparationError(
                "code index differs from bundle", code="code-digest-mismatch"
            )
        config = dict((path, payload) for path, _, _, payload in material)["material/config.json"]
        if config != canonical_json(execution_object(index.request)).encode():
            raise NativeReviewedPreparationError(
                "configuration bytes differ", code="config-digest-mismatch"
            )
        prepared = _receipt(index.request, index.grant_id, material, parsed)
        verified = _Verified(
            index.request, index.request_digest, index.grant_id, material, prepared
        )
        # Recheck live authority after transfers and host probes, even for cached replay.
        if NativeMaterialIndex.model_validate(client.fetch_native_material_index()) != index:
            raise NativeTransferError(
                "material context changed", code="transfer-integrity-mismatch"
            )
        _publish(workspace, verified)
        return prepared


def _opaque(item: NativeMaterialFile) -> str:
    # Keep legacy transfer path grammar intact; native module/input names remain opaque.
    return "objects/" + hashlib.sha256(item.relative_path.encode()).hexdigest()


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _private_directory(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise NativeTransferError(
            "preparation directory is not private", code="transfer-path-unauthorized"
        )


@contextlib.contextmanager
def _workspace_lock(workspace: Path) -> Iterator[None]:
    with _PREPARATION_LOCK, _directory(workspace.parent, create=False) as parent:
        _private_directory(parent)
        name = ".prepare-" + hashlib.sha256(workspace.name.encode()).hexdigest() + ".lock"
        try:
            descriptor = os.open(
                name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent
            )
        except OSError:
            raise NativeTransferError(
                "preparation lock is invalid", code="transfer-journal-invalid"
            ) from None
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_size != 0
                or info.st_mode & 0o077
            ):
                raise NativeTransferError(
                    "preparation lock is invalid", code="transfer-journal-invalid"
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NativeTransferError(
                    "preparation is busy", code="transfer-journal-busy"
                ) from None
            yield
        finally:
            os.close(descriptor)


def _publish(workspace: Path, verified: _Verified) -> None:
    if not _is_fresh(workspace):
        with _directory(workspace, create=False) as root:
            _private_directory(root)
        diagnosis = _inspect(workspace, verified)
        if diagnosis.outcome != "ready":
            raise NativeReviewedPreparationError(
                "workspace is not reusable", code=diagnosis.reason_code
            )
        return
    with _directory(workspace.parent, create=False) as parent:
        _private_directory(parent)
        _require_disk(
            parent,
            sum(len(row[3]) for row in verified.files) + len(_receipt_bytes(verified.receipt)),
        )
        name = ".prepare-candidate-" + secrets.token_hex(16)
        os.mkdir(name, 0o700, dir_fd=parent)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            for path, payload in {
                **verified.payloads(),
                "receipt.json": _receipt_bytes(verified.receipt),
            }.items():
                _write_relative(descriptor, path, payload)
            os.fsync(descriptor)
            diagnosis = _inspect(workspace.parent / name, verified)
            if diagnosis.outcome != "ready" or not _is_fresh(workspace):
                raise NativeReviewedPreparationError(
                    "workspace publication refused", code="preparation-damaged"
                )
            os.rename(name, workspace.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(descriptor)
        # A crash before rename leaves an unreferenced private candidate, never a ready workspace.
