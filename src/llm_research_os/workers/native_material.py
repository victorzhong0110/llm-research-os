"""Resolve only reviewed native material, including bundle members and identity documents."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from llm_research_os.artifacts.errors import ArtifactNotFoundError
from llm_research_os.artifacts.store import MAX_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import canonical_json
from llm_research_os.execution.errors import NativeReviewedPreparationError
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_material import (
    NativeReviewedCodeReview,
    NativeReviewedInterpreterIdentity,
    NativeReviewedPythonBundle,
)
from llm_research_os.execution.native_reviewed_preparation import _require_interpreter_document
from llm_research_os.execution.native_reviewed_preparation_documents import MAX_PREPARATION_FILES
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.native_material_documents import NativeMaterialIndex

if TYPE_CHECKING:
    from llm_research_os.workers.plane import WorkerPlane


@dataclass(frozen=True)
class _Material:
    path: str
    role: str
    digest: str
    payload: bytes | None = None
    size: int | None = None
    name: str | None = None


def material_index(plane: WorkerPlane, *, worker_id: str, grant_token: str) -> NativeMaterialIndex:
    request = plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
    _, grant = plane.native_input_scope(worker_id=worker_id, grant_token=grant_token)
    files: list[dict[str, object]] = []
    for item in _materials(plane.artifacts, request):
        payload = _payload(plane.artifacts, request, item)
        row: dict[str, object] = {
            "relativePath": item.path,
            "role": item.role,
            "digest": item.digest,
            "byteDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
        }
        if item.name is not None:
            row["name"] = item.name
        files.append(row)
    return NativeMaterialIndex.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeMaterialIndex",
            "request": request.model_dump(mode="json", by_alias=True, exclude_none=True),
            "requestDigest": request_digest(request),
            "grantId": grant.grant_id,
            "files": files,
            "launchAllowed": False,
        }
    )


def extra_material_payload(
    plane: WorkerPlane, *, worker_id: str, grant_token: str, digest: str, size_bytes: int
) -> bytes:
    request = plane.native_reviewed_request(worker_id=worker_id, grant_token=grant_token)
    for item in _materials(plane.artifacts, request):
        if "sha256:" + item.digest.split(":", 1)[1] != digest:
            continue
        payload = _payload(plane.artifacts, request, item)
        if len(payload) != size_bytes:
            raise WorkerCallError("material size differs", code="transfer-size-mismatch")
        return payload
    raise WorkerCallError("material is not planned", code="execution-binding-mismatch")


def _materials(
    artifacts: LocalArtifactStore, request: NativeReviewedExecutionRequest
) -> tuple[_Material, ...]:
    payload = _read_bound(artifacts, request.code.bundle_digest)
    bundle = _parse(payload, NativeReviewedPythonBundle)
    if bundle.entrypoint != request.code.entrypoint:
        raise WorkerCallError("bundle entrypoint differs", code="execution-binding-mismatch")
    rows = [_Material("material/bundle", "bundle", request.code.bundle_digest, payload)]
    rows.extend(
        _Material(f"material/code/{item.path}", "code", item.digest) for item in bundle.files
    )
    rows.extend(
        _Material(
            f"material/inputs/{item.name}",
            "input",
            item.digest,
            size=item.size_bytes,
            name=item.name,
        )
        for item in request.inputs
    )
    rows.extend(
        [
            _Material(
                "material/config.json",
                "config",
                request.config_digest,
                canonical_json(execution_object(request)).encode(),
            ),
            _Material(
                "material/environment/interpreter",
                "interpreter",
                request.environment.interpreter_digest,
            ),
            _Material(
                "material/environment/dependency-lock",
                "dependency-lock",
                request.environment.dependency_lock_digest,
            ),
            _Material(
                "material/environment/inventory", "inventory", request.environment.inventory_digest
            ),
            _Material("material/environment/review", "review", request.code.review.citation_digest),
        ]
    )
    if len(rows) > MAX_PREPARATION_FILES:
        raise WorkerCallError("material count exceeds preparation bound", code="http-too-large")
    return tuple(rows)


def _payload(
    artifacts: LocalArtifactStore, request: NativeReviewedExecutionRequest, item: _Material
) -> bytes:
    digest = "sha256:" + item.digest.split(":", 1)[1]
    payload = item.payload if item.payload is not None else _read_bound(artifacts, digest)
    if item.size is not None and len(payload) != item.size:
        raise WorkerCallError("material input size differs", code="transfer-size-mismatch")
    if item.role == "interpreter":
        identity = _parse(payload, NativeReviewedInterpreterIdentity)
        try:
            _require_interpreter_document(request, identity)
        except NativeReviewedPreparationError:
            raise WorkerCallError(
                "identity document differs", code="transfer-material-invalid"
            ) from None
    if item.role == "review":
        review = _parse(payload, NativeReviewedCodeReview)
        if (
            review.bundle_digest != request.code.bundle_digest
            or review.media_type != request.code.media_type
            or review.entrypoint != request.code.entrypoint
            or canonical_json(json.loads(payload)).encode() != payload
        ):
            raise WorkerCallError("review document differs", code="transfer-material-invalid")
    return payload


def _read_bound(artifacts: LocalArtifactStore, digest: str) -> bytes:
    try:
        with artifacts.open(digest) as handle:
            size = os.fstat(handle.fileno()).st_size
            if size > MAX_PUT_BYTES:
                raise WorkerCallError("material exceeds preparation bound", code="http-too-large")
            payload = handle.read(size + 1)
    except ArtifactNotFoundError:
        raise WorkerCallError("material is missing", code="artifact-missing") from None
    if len(payload) != size or "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
        raise WorkerCallError("material digest differs", code="transfer-digest-mismatch")
    return payload


def _parse[Model: BaseModel](payload: bytes, model: type[Model]) -> Model:
    try:
        return model.model_validate(json.loads(payload))
    except (ValueError, RecursionError, ValidationError):
        raise WorkerCallError(
            "material document is invalid", code="transfer-material-invalid"
        ) from None
