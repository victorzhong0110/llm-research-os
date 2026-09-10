"""Outbound Worker client for loopback HTTP tests and loopback HTTPS isolation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import ssl
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.workers.binding import json_object, require_execution_digest
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_MPS_ENV,
    IMAGE_MEDIA_OCI_IMAGE,
    IMAGE_MEDIA_PYTHON_BRICK,
    WORKER_RUNTIME_GPU_OCI,
    WORKER_RUNTIME_MACOS_MPS,
    WORKER_RUNTIME_OCI_CONTAINER,
    WORKER_RUNTIME_PYTHON_SANDBOX,
)
from llm_research_os.workers.oci import execute_oci_python_brick
from llm_research_os.workers.sandbox import (
    MAX_SANDBOX_WALL_SECONDS,
    SandboxDisposition,
    execute_python_brick,
)
from llm_research_os.workers.supervise import (
    OBSERVED_STOP,
    UNOBSERVED,
    PendingComplete,
    drop_execution_identity,
    drop_pending_complete,
    load_execution_identity,
    load_pending_complete,
    observe_and_stop,
    save_pending_complete,
)
from llm_research_os.workers.tls import client_tls_context

_GRANT_HEADER = "X-ResearchOS-Grant"
_DEFAULT_RETRIES = 3
_WORKER_HTTP_TIMEOUT_ENV = "RESEARCHOS_WORKER_HTTP_TIMEOUT"
_DEFAULT_WORKER_HTTP_TIMEOUT = 10.0
_MAX_WORKER_HTTP_TIMEOUT = 300.0


def worker_http_timeout() -> float:
    """Socket timeout for Worker HTTP/HTTPS. Live checkpoint PUT may raise this."""

    raw = os.environ.get(_WORKER_HTTP_TIMEOUT_ENV, "10")
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_WORKER_HTTP_TIMEOUT
    if value < 1 or value > _MAX_WORKER_HTTP_TIMEOUT:
        return _DEFAULT_WORKER_HTTP_TIMEOUT
    return value


@dataclass(frozen=True, slots=True)
class WorkerClient:
    base_url: str
    worker_id: str
    session: str
    grant_token: str
    ca_path: Path | None = None
    tls_fingerprint: str | None = None
    retries: int = _DEFAULT_RETRIES
    identity_dir: Path | None = None
    timeout_seconds: int = MAX_SANDBOX_WALL_SECONDS
    mps_data_dir: Path | None = None
    mps_model_dir: Path | None = None
    mps_output_dir: Path | None = None
    mps_interpreter: Path | None = None
    gpu_data_dir: Path | None = None
    gpu_model_dir: Path | None = None
    gpu_output_dir: Path | None = None

    def poll(self) -> dict[str, Any] | None:
        status, payload = self._json(
            "POST",
            "/v0alpha1/work/poll",
            {"workerId": self.worker_id, "grantToken": self.grant_token, "waitSeconds": 0},
        )
        if status == 204:
            return None
        if status != 200 or payload is None:
            raise WorkerError("work poll failed", code="http-poll-failed")
        return payload

    def complete(
        self, *, lease_id: str, result_digest: str, artifact_digest: str
    ) -> dict[str, str]:
        status, payload = self._json(
            "POST",
            "/v0alpha1/work/complete",
            {
                "workerId": self.worker_id,
                "grantToken": self.grant_token,
                "leaseId": lease_id,
                "resultDigest": result_digest,
                "artifactDigest": artifact_digest,
            },
        )
        if status != 200 or payload is None:
            raise WorkerError("work complete failed", code="http-complete-failed")
        return {key: str(value) for key, value in payload.items()}

    def fail(self, *, lease_id: str, reason_code: str) -> dict[str, str]:
        status, payload = self._json(
            "POST",
            "/v0alpha1/work/fail",
            {
                "workerId": self.worker_id,
                "grantToken": self.grant_token,
                "leaseId": lease_id,
                "reasonCode": reason_code,
            },
        )
        if status != 200 or payload is None:
            raise WorkerError("work fail failed", code="http-fail-failed")
        return {key: str(value) for key, value in payload.items()}

    def heartbeat(self, *, lease_id: str) -> bool:
        status, payload = self._json(
            "POST",
            "/v0alpha1/work/heartbeat",
            {"workerId": self.worker_id, "leaseId": lease_id},
        )
        if status != 200 or payload is None:
            raise WorkerError("work heartbeat failed", code="http-heartbeat-failed")
        return payload.get("cancelRequested") is True

    def put_artifact(self, payload: bytes) -> str:
        status, body = self._raw(
            "POST",
            "/v0alpha1/artifacts",
            payload,
            content_type="application/octet-stream",
            grant=False,
        )
        if status != 201:
            raise WorkerError("artifact upload failed", code="http-artifact-failed")
        document = json.loads(body.decode("utf-8"))
        digest = document.get("digest") if type(document) is dict else None
        if type(digest) is not str:
            raise WorkerError("artifact upload omitted digest", code="http-artifact-failed")
        return digest

    def fetch_image(self, artifacts: LocalArtifactStore, image_digest: str) -> str:
        if DIGEST_PATTERN.fullmatch(image_digest) is None:
            raise WorkerError("image digest is invalid", code="http-invalid")
        try:
            artifacts.verify(image_digest)
            return image_digest
        except (ArtifactNotFoundError, ArtifactStoreError):
            pass
        hex_digest = image_digest.removeprefix("sha256:")
        status, payload = self._raw(
            "GET",
            f"/v0alpha1/artifacts/sha256/{hex_digest}",
            b"",
            content_type="application/octet-stream",
            grant=True,
        )
        if status == 401:
            raise WorkerError("artifact download was refused", code="http-artifact-denied")
        if status != 200:
            raise WorkerError("artifact download failed", code="http-artifact-failed")
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual != image_digest:
            raise WorkerError(
                "downloaded artifact digest does not match",
                code="artifact-integrity-mismatch",
            )
        return artifacts.put_bytes(payload).digest

    def run_once(self, artifacts: LocalArtifactStore) -> dict[str, str] | None:
        claimed = self.poll()
        if claimed is None:
            return None
        lease_id = claimed.get("leaseId")
        if claimed.get("resumed") is True:
            return self._resume_claimed(claimed)
        if claimed.get("cancelRequested") is True:
            raise WorkerError("original executor was not observed", code=UNOBSERVED)
        image_digest = claimed.get("imageDigest")
        config_digest = claimed.get("configDigest")
        runtime = claimed.get("runtime", WORKER_RUNTIME_PYTHON_SANDBOX)
        media = claimed.get("imageMediaType", IMAGE_MEDIA_PYTHON_BRICK)
        if type(image_digest) is not str or type(config_digest) is not str:
            raise WorkerError("poll omitted execution binding", code="http-invalid")
        if type(runtime) is not str or type(media) is not str:
            raise WorkerError("poll omitted execution binding", code="http-invalid")
        config = json_object(claimed.get("config", {}), field="config")
        inputs = json_object(claimed.get("inputs", {}), field="inputs")
        require_execution_digest(
            image_digest=image_digest,
            config=config,
            inputs=inputs,
            config_digest=config_digest,
            image_media_type=media,
            runtime=runtime,
        )
        if type(lease_id) is not str:
            raise WorkerError("poll omitted leaseId", code="http-invalid")

        def _cancel_requested() -> bool:
            try:
                return self.heartbeat(lease_id=lease_id)
            except WorkerError:
                return False

        if runtime == WORKER_RUNTIME_PYTHON_SANDBOX and media == IMAGE_MEDIA_PYTHON_BRICK:
            self.fetch_image(artifacts, image_digest)
            result = execute_python_brick(
                artifacts,
                image_digest,
                config=config,
                inputs=inputs,
                timeout_seconds=self.timeout_seconds,
                identity_dir=self.identity_dir,
                lease_id=lease_id,
                should_cancel=_cancel_requested,
            )
        elif runtime == WORKER_RUNTIME_OCI_CONTAINER and media == IMAGE_MEDIA_OCI_IMAGE:
            brick_digest = inputs.get("brickDigest")
            if type(brick_digest) is not str:
                raise WorkerError("OCI poll omitted brickDigest", code="http-invalid")
            self.fetch_image(artifacts, brick_digest)
            result = execute_oci_python_brick(
                artifacts,
                image_digest,
                config=config,
                inputs=inputs,
                identity_dir=self.identity_dir,
                lease_id=lease_id,
                should_cancel=_cancel_requested,
            )
        elif runtime == WORKER_RUNTIME_GPU_OCI and media == IMAGE_MEDIA_OCI_IMAGE:
            plan_artifact = inputs.get("planArtifactDigest")
            if type(plan_artifact) is not str:
                raise WorkerError("GPU poll omitted planArtifactDigest", code="http-invalid")
            self.fetch_image(artifacts, plan_artifact)
            gpu = importlib.import_module("llm_research_os.workers.gpu")
            result = gpu.run_gpu_training(
                artifacts,
                image_digest,
                config=config,
                inputs=inputs,
                advertised_accelerators=("cuda",),
                data_dir=self.gpu_data_dir,
                model_dir=self.gpu_model_dir,
                output_dir=self.gpu_output_dir,
                identity_dir=self.identity_dir,
                lease_id=lease_id,
                should_cancel=_cancel_requested,
            )
        elif runtime == WORKER_RUNTIME_MACOS_MPS and media == IMAGE_MEDIA_MPS_ENV:
            plan_artifact = inputs.get("planArtifactDigest")
            if type(plan_artifact) is not str:
                raise WorkerError("MPS poll omitted planArtifactDigest", code="http-invalid")
            self.fetch_image(artifacts, image_digest)
            self.fetch_image(artifacts, plan_artifact)
            mps = importlib.import_module("llm_research_os.workers.mps")
            result = mps.execute_mps_training(
                artifacts,
                image_digest,
                config=config,
                inputs=inputs,
                advertised_accelerators=("mps",),
                data_dir=self.mps_data_dir,
                model_dir=self.mps_model_dir,
                output_dir=self.mps_output_dir,
                interpreter=self.mps_interpreter,
                identity_dir=self.identity_dir,
                lease_id=lease_id,
                should_cancel=_cancel_requested,
                timeout_seconds=self.timeout_seconds,
            )
        else:
            raise WorkerError("poll runtime is not supported", code="runtime-mismatch")
        if result.disposition is SandboxDisposition.UNKNOWN:
            self._drop_identity(lease_id)
            raise WorkerError("sandbox outcome is unknown", code=result.reason_code)
        if result.disposition is not SandboxDisposition.SUCCEEDED or result.result_digest is None:
            with contextlib.suppress(WorkerError):
                self.fail(lease_id=lease_id, reason_code=result.reason_code)
            self._drop_identity(lease_id)
            raise WorkerError("sandbox brick failed", code=result.reason_code)
        if self.identity_dir is not None:
            drop_execution_identity(self.identity_dir, lease_id)
        artifact_digest = self.put_artifact(result.stdout)
        if self.identity_dir is not None:
            save_pending_complete(
                self.identity_dir,
                PendingComplete(
                    lease_id=lease_id,
                    result_digest=result.result_digest,
                    artifact_digest=artifact_digest,
                ),
            )
        completed = self.complete(
            lease_id=lease_id,
            result_digest=result.result_digest,
            artifact_digest=artifact_digest,
        )
        self._drop_identity(lease_id)
        return completed

    def _resume_claimed(self, claimed: dict[str, Any]) -> dict[str, str] | None:
        lease_id = claimed.get("leaseId")
        if type(lease_id) is not str:
            raise WorkerError(
                "claimed work must not be executed again",
                code="work-already-claimed",
            )
        pending = None
        if self.identity_dir is not None:
            pending = load_pending_complete(self.identity_dir, lease_id)
        if pending is not None:
            completed = self.complete(
                lease_id=lease_id,
                result_digest=pending.result_digest,
                artifact_digest=pending.artifact_digest,
            )
            self._drop_identity(lease_id)
            return completed
        identity = None
        if self.identity_dir is not None:
            identity = load_execution_identity(self.identity_dir, lease_id)
        if claimed.get("cancelRequested") is True:
            outcome = observe_and_stop(identity)
            if outcome == OBSERVED_STOP:
                with contextlib.suppress(WorkerError):
                    self.fail(lease_id=lease_id, reason_code="cancel-observed")
                self._drop_identity(lease_id)
                raise WorkerError("cancel was observed", code="cancel-observed")
            raise WorkerError("original executor was not observed", code=UNOBSERVED)
        raise WorkerError(
            "claimed work must not be executed again",
            code="work-already-claimed",
        )

    def _drop_identity(self, lease_id: str) -> None:
        if self.identity_dir is not None:
            drop_execution_identity(self.identity_dir, lease_id)
            drop_pending_complete(self.identity_dir, lease_id)

    def _json(
        self, method: str, path: str, document: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None]:
        payload = json.dumps(document, ensure_ascii=True).encode("utf-8")
        status, raw = self._raw(method, path, payload, content_type="application/json", grant=False)
        if status == 204:
            return 204, None
        if not raw:
            return status, None
        decoded = json.loads(raw.decode("utf-8"))
        if type(decoded) is not dict:
            raise WorkerError("worker HTTP JSON must be an object", code="http-invalid")
        return status, decoded

    def _raw(
        self,
        method: str,
        path: str,
        payload: bytes,
        *,
        content_type: str,
        grant: bool,
    ) -> tuple[int, bytes]:
        last: WorkerError | None = None
        attempts = self.retries if self.retries > 0 else 1
        for _ in range(attempts):
            try:
                return self._raw_once(method, path, payload, content_type=content_type, grant=grant)
            except WorkerError as exc:
                if exc.code != "http-disconnect":
                    raise
                last = exc
        if last is None:
            raise WorkerError("worker transport is unavailable", code="http-disconnect")
        raise last

    def _raw_once(
        self,
        method: str,
        path: str,
        payload: bytes,
        *,
        content_type: str,
        grant: bool,
    ) -> tuple[int, bytes]:
        parsed = urlparse(self.base_url)
        headers = {"Authorization": f"Bearer {self.session}"}
        body: bytes | None = payload
        if method == "GET":
            body = None
        else:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(payload))
        if grant:
            headers[_GRANT_HEADER] = self.grant_token
        connection = _connection(parsed, self.ca_path, self.tls_fingerprint)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            body = response.read()
        except (OSError, ssl.SSLError) as exc:
            raise WorkerError("worker transport is unavailable", code="http-disconnect") from exc
        finally:
            connection.close()
        return response.status, body


def _connection(
    parsed: Any,
    ca_path: Path | None,
    tls_fingerprint: str | None,
) -> HTTPConnection | HTTPSConnection:
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if parsed.scheme == "https":
        if ca_path is None or tls_fingerprint is None:
            raise WorkerError("HTTPS Worker client requires a pinned CA", code="tls-required")
        return HTTPSConnection(
            host,
            port,
            timeout=worker_http_timeout(),
            context=client_tls_context(ca_path, tls_fingerprint),
        )
    if parsed.scheme != "http":
        raise WorkerError("worker URL scheme is not supported", code="http-invalid")
    if ca_path is not None or tls_fingerprint is not None:
        raise WorkerError(
            "HTTP Worker client cannot carry TLS material",
            code="tls-scheme-mismatch",
        )
    return HTTPConnection(host, port, timeout=worker_http_timeout())
