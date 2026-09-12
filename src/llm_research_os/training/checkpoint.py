"""Offline snapshot, resume overlay, and persistent checkpoint CAS collect.

This path does not download Hub snapshots, start docker, or claim a GPU run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import MAX_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.events.models import EventDocumentModel
from llm_research_os.spec.io import load_document
from llm_research_os.training.errors import TrainingBackendError, TrainingBackendRequestError
from llm_research_os.training.gpu_bind import plan_document_digest
from llm_research_os.training.requests import TrainingBackendPlan

_REVISION = r"^(?:pending-live|[0-9a-f]{40})$"
GPU_MODEL_MOUNT: Literal["/work/model"] = "/work/model"
GPU_DATA_MOUNT: Literal["/work/data"] = "/work/data"
GPU_OUTPUT_MOUNT: Literal["/work/output"] = "/work/output"

GPU_DATA_CHECKPOINT_SCHEMA_ID = (
    "https://researchos.dev/schemas/gpu-data-checkpoint/v0alpha1.schema.json"
)
PINNED_MODEL_ID: Literal["Qwen/Qwen2.5-0.5B-Instruct"] = "Qwen/Qwen2.5-0.5B-Instruct"
PINNED_MODEL_REVISION: Literal["7ae557604adf67be50417f59c2c2f167def9a775"] = (
    "7ae557604adf67be50417f59c2c2f167def9a775"
)
PINNED_DATASET_ID: Literal["AI-ModelScope/alpaca-gpt4-data-en"] = (
    "AI-ModelScope/alpaca-gpt4-data-en"
)
MAX_CHECKPOINT_FILES = 32
MAX_CHECKPOINT_UPLOAD_BYTES = MAX_PUT_BYTES
MAX_MPS_CHECKPOINT_FILES = 64
MAX_MPS_CHECKPOINT_UPLOAD_BYTES = 268_435_456
MAX_MPS_SNAPSHOT_FILE_BYTES = 8_589_934_592


class GpuModelSnapshot(EventDocumentModel):
    id: Literal["Qwen/Qwen2.5-0.5B-Instruct"]
    hub: Literal["huggingface"]
    revision: Literal["7ae557604adf67be50417f59c2c2f167def9a775"]
    mount: Literal["/work/model"] = GPU_MODEL_MOUNT
    content_digest: str | None = Field(
        default=None, alias="contentDigest", pattern=SEMANTIC_DIGEST_PATTERN
    )


class GpuDatasetSnapshot(EventDocumentModel):
    id: Literal["AI-ModelScope/alpaca-gpt4-data-en"]
    hub: Literal["modelscope"]
    row_limit: Literal[8] = Field(alias="rowLimit")
    revision: str = Field(pattern=_REVISION)
    lineage_hub: Literal["huggingface"] = Field(alias="lineageHub")
    lineage_id: Literal["vicgalle/alpaca-gpt4"] = Field(alias="lineageId")
    lineage_revision: Literal["f7e3ded725cb81e8e564e32feb12860f376f2b51"] = Field(
        alias="lineageRevision"
    )
    mount: Literal["/work/data"] = GPU_DATA_MOUNT
    content_digest: str | None = Field(
        default=None, alias="contentDigest", pattern=SEMANTIC_DIGEST_PATTERN
    )


class GpuOutputBinding(EventDocumentModel):
    mount: Literal["/work/output"] = GPU_OUTPUT_MOUNT
    persist: Literal["bind"] = "bind"
    max_upload_bytes: Literal[1_048_576] = Field(alias="maxUploadBytes")
    max_upload_files: Literal[32] = Field(alias="maxUploadFiles")


class GpuDataCheckpointBinding(EventDocumentModel):
    """Pins model/data identity and output persistence. Not a CUDA receipt."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["GpuDataCheckpointBinding"]
    plan_digest: str = Field(alias="planDigest", pattern=SEMANTIC_DIGEST_PATTERN)
    offline: Literal[True] = True
    model: GpuModelSnapshot
    dataset: GpuDatasetSnapshot
    output: GpuOutputBinding


@dataclass(frozen=True, slots=True)
class TreeFile:
    path: str
    digest: str
    size: int


@dataclass(frozen=True, slots=True)
class SnapshotStatus:
    role: str
    status: Literal["present", "missing", "mismatch", "recorded", "pending-live"]
    digest: str | None
    revision: str


@dataclass(frozen=True, slots=True)
class SnapshotReceipt:
    model: SnapshotStatus
    dataset: SnapshotStatus
    fetched: bool
    gpu: str
    prefetch_argv: tuple[str, ...]
    dataset_prefetch_argv: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "GpuSnapshotReceipt",
            "fetched": self.fetched,
            "gpu": self.gpu,
            "offline": True,
            "model": {
                "role": self.model.role,
                "status": self.model.status,
                "digest": self.model.digest,
                "revision": self.model.revision,
            },
            "dataset": {
                "role": self.dataset.role,
                "status": self.dataset.status,
                "digest": self.dataset.digest,
                "revision": self.dataset.revision,
            },
            "prefetchArgv": list(self.prefetch_argv),
            "datasetPrefetchArgv": list(self.dataset_prefetch_argv),
        }


@dataclass(frozen=True, slots=True)
class CollectReceipt:
    status: Literal["complete", "incomplete"]
    files: tuple[TreeFile, ...]
    manifest_digest: str
    bytes_uploaded: int
    gpu: str
    executed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "GpuCheckpointCollectReceipt",
            "status": self.status,
            "executed": self.executed,
            "gpu": self.gpu,
            "manifestDigest": self.manifest_digest,
            "bytesUploaded": self.bytes_uploaded,
            "files": [
                {"path": item.path, "digest": item.digest, "size": item.size} for item in self.files
            ],
        }


def load_gpu_data_checkpoint_binding(path: str | Path) -> GpuDataCheckpointBinding:
    try:
        return GpuDataCheckpointBinding.model_validate(load_document(path))
    except ValidationError as exc:
        raise TrainingBackendRequestError(exc) from exc


def require_binding_matches_plan(
    binding: GpuDataCheckpointBinding, plan: TrainingBackendPlan
) -> None:
    expected = plan_document_digest(plan)
    if binding.plan_digest != expected:
        raise TrainingBackendError(
            "data-checkpoint binding does not match the pinned plan digest",
            code="execution-binding-mismatch",
        )
    if plan.model != binding.model.id:
        raise TrainingBackendError(
            "data-checkpoint model id does not match the pinned plan",
            code="execution-binding-mismatch",
        )
    dataset_id, _sep, rows = plan.dataset.partition("#")
    if dataset_id != binding.dataset.id or rows != str(binding.dataset.row_limit):
        raise TrainingBackendError(
            "data-checkpoint dataset id does not match the pinned plan",
            code="execution-binding-mismatch",
        )


def list_tree_files(
    root: Path,
    *,
    max_files: int = MAX_CHECKPOINT_FILES,
    max_file_bytes: int = MAX_PUT_BYTES,
) -> tuple[TreeFile, ...]:
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise TrainingBackendError("snapshot path is not a directory", code="snapshot-path-invalid")
    found: list[TreeFile] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise TrainingBackendError(
                "snapshot tree must not contain symlinks",
                code="snapshot-symlink-forbidden",
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise TrainingBackendError(
                "snapshot tree contains a non-regular file",
                code="snapshot-path-invalid",
            )
        if len(found) >= max_files:
            raise TrainingBackendError(
                "snapshot tree exceeds the closed file bound",
                code="gpu-resource-limit",
            )
        digest, size = _hash_regular_file(path, max_file_bytes=max_file_bytes)
        relative = path.relative_to(root).as_posix()
        found.append(TreeFile(path=relative, digest=digest, size=size))
    return tuple(found)


def tree_digest(files: tuple[TreeFile, ...]) -> str | None:
    if not files:
        return None
    return content_digest(
        {"files": [{"path": item.path, "digest": item.digest, "size": item.size} for item in files]}
    )


def inspect_snapshot(
    binding: GpuDataCheckpointBinding,
    *,
    model_dir: Path | None,
    data_dir: Path | None,
) -> SnapshotReceipt:
    """Compare local trees to the binding. MUST NOT download or train."""

    model = _status_for(
        role="model",
        directory=model_dir,
        expected=binding.model.content_digest,
        revision=binding.model.revision,
    )
    dataset = _status_for(
        role="dataset",
        directory=data_dir,
        expected=binding.dataset.content_digest,
        revision=binding.dataset.revision,
    )
    prefetch = (
        "modelscope",
        "download",
        PINNED_MODEL_ID,
        "--revision",
        PINNED_MODEL_REVISION,
        "--local-dir",
        GPU_MODEL_MOUNT,
    )
    dataset_prefetch = (
        "modelscope",
        "download",
        "--dataset",
        PINNED_DATASET_ID,
        "--local-dir",
        GPU_DATA_MOUNT,
    )
    return SnapshotReceipt(
        model=model,
        dataset=dataset,
        fetched=False,
        gpu="not-run",
        prefetch_argv=prefetch,
        dataset_prefetch_argv=dataset_prefetch,
    )


def collect_output_artifacts(
    output_dir: Path,
    artifacts: LocalArtifactStore,
    *,
    prior: Mapping[str, str] | None = None,
    max_files: int = MAX_CHECKPOINT_FILES,
    max_file_bytes: int = MAX_PUT_BYTES,
    max_upload_bytes: int = MAX_CHECKPOINT_UPLOAD_BYTES,
) -> CollectReceipt:
    """Put checkpoint files into CAS. Output is a bind mount, not tmpfs."""

    files = list_tree_files(output_dir, max_files=max_files, max_file_bytes=max_file_bytes)
    total = 0
    uploaded: list[TreeFile] = []
    known = dict(prior or {})
    for item in files:
        total += item.size
        if total > max_upload_bytes:
            raise TrainingBackendError(
                "checkpoint upload exceeds the closed byte bound",
                code="gpu-resource-limit",
            )
        previous = known.get(item.path)
        if previous is not None and previous != item.digest:
            raise TrainingBackendError(
                "checkpoint file digest changed during upload resume",
                code="artifact-integrity-mismatch",
            )
        source = output_dir / item.path
        if previous is not None:
            try:
                artifacts.verify(item.digest)
                uploaded.append(item)
                continue
            except (ArtifactNotFoundError, ArtifactStoreError):
                pass
        try:
            record = artifacts.put(source)
        except ArtifactStoreError:
            return _collect_receipt(tuple(uploaded), status="incomplete")
        if record.digest != item.digest:
            raise TrainingBackendError(
                "checkpoint file digest does not match CAS",
                code="artifact-integrity-mismatch",
            )
        uploaded.append(item)
        known[item.path] = item.digest
    status: Literal["complete", "incomplete"] = (
        "complete" if len(uploaded) == len(files) else "incomplete"
    )
    return _collect_receipt(tuple(uploaded), status=status)


def load_collect_manifest(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingBackendError(
            "collect manifest is invalid",
            code="checkpoint-manifest-invalid",
        ) from exc
    if type(document) is not dict:
        raise TrainingBackendError(
            "collect manifest is invalid",
            code="checkpoint-manifest-invalid",
        )
    files = document.get("files")
    if type(files) is not list:
        raise TrainingBackendError(
            "collect manifest is invalid",
            code="checkpoint-manifest-invalid",
        )
    mapping: dict[str, str] = {}
    for item in files:
        if type(item) is not dict:
            raise TrainingBackendError(
                "collect manifest is invalid",
                code="checkpoint-manifest-invalid",
            )
        relative = item.get("path")
        digest = item.get("digest")
        if type(relative) is not str or type(digest) is not str:
            raise TrainingBackendError(
                "collect manifest is invalid",
                code="checkpoint-manifest-invalid",
            )
        mapping[relative] = digest
    return mapping


def _collect_receipt(
    files: tuple[TreeFile, ...],
    *,
    status: Literal["complete", "incomplete"],
) -> CollectReceipt:
    manifest = {
        "kind": "GpuCheckpointCollectReceipt",
        "status": status,
        "executed": False,
        "gpu": "not-run",
        "files": [{"path": item.path, "digest": item.digest, "size": item.size} for item in files],
    }
    return CollectReceipt(
        status=status,
        files=files,
        manifest_digest=content_digest(manifest),
        bytes_uploaded=sum(item.size for item in files),
        gpu="not-run",
        executed=False,
    )


def _status_for(
    *,
    role: str,
    directory: Path | None,
    expected: str | None,
    revision: str,
) -> SnapshotStatus:
    if directory is None:
        status: Literal["present", "missing", "mismatch", "recorded", "pending-live"]
        status = "pending-live" if revision == "pending-live" else "missing"
        return SnapshotStatus(role=role, status=status, digest=expected, revision=revision)
    files = list_tree_files(directory)
    digest = tree_digest(files)
    if digest is None:
        status = "pending-live" if revision == "pending-live" else "missing"
        return SnapshotStatus(role=role, status=status, digest=None, revision=revision)
    if expected is None:
        return SnapshotStatus(role=role, status="recorded", digest=digest, revision=revision)
    if digest != expected:
        return SnapshotStatus(role=role, status="mismatch", digest=digest, revision=revision)
    return SnapshotStatus(role=role, status="present", digest=digest, revision=revision)


def _hash_regular_file(path: Path, *, max_file_bytes: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > max_file_bytes:
                raise TrainingBackendError(
                    "snapshot file exceeds the closed CAS put bound",
                    code="gpu-resource-limit",
                )
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest(), size
