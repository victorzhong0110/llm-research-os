"""Outbound Worker client for loopback HTTP tests and loopback HTTPS isolation."""

from __future__ import annotations

import contextlib
import hashlib
import json
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
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick
from llm_research_os.workers.tls import client_tls_context

_GRANT_HEADER = "X-ResearchOS-Grant"
_DEFAULT_RETRIES = 3


@dataclass(frozen=True, slots=True)
class WorkerClient:
    base_url: str
    worker_id: str
    session: str
    grant_token: str
    ca_path: Path | None = None
    tls_fingerprint: str | None = None
    retries: int = _DEFAULT_RETRIES

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
        if claimed.get("resumed") is True:
            raise WorkerError(
                "claimed work must not be executed again",
                code="work-already-claimed",
            )
        image_digest = claimed.get("imageDigest")
        config_digest = claimed.get("configDigest")
        if type(image_digest) is not str or type(config_digest) is not str:
            raise WorkerError("poll omitted execution binding", code="http-invalid")
        config = json_object(claimed.get("config", {}), field="config")
        inputs = json_object(claimed.get("inputs", {}), field="inputs")
        require_execution_digest(
            image_digest=image_digest,
            config=config,
            inputs=inputs,
            config_digest=config_digest,
        )
        self.fetch_image(artifacts, image_digest)
        result = execute_python_brick(
            artifacts,
            image_digest,
            config=config,
            inputs=inputs,
        )
        if result.disposition is SandboxDisposition.UNKNOWN:
            raise WorkerError("sandbox outcome is unknown", code=result.reason_code)
        if result.disposition is not SandboxDisposition.SUCCEEDED or result.result_digest is None:
            lease_id = claimed.get("leaseId")
            if type(lease_id) is str:
                with contextlib.suppress(WorkerError):
                    self.fail(lease_id=lease_id, reason_code=result.reason_code)
            raise WorkerError("sandbox brick failed", code=result.reason_code)
        artifact_digest = self.put_artifact(result.stdout)
        lease_id = claimed.get("leaseId")
        if type(lease_id) is not str:
            raise WorkerError("poll omitted leaseId", code="http-invalid")
        return self.complete(
            lease_id=lease_id,
            result_digest=result.result_digest,
            artifact_digest=artifact_digest,
        )

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
            timeout=10,
            context=client_tls_context(ca_path, tls_fingerprint),
        )
    if parsed.scheme != "http":
        raise WorkerError("worker URL scheme is not supported", code="http-invalid")
    if ca_path is not None or tls_fingerprint is not None:
        raise WorkerError(
            "HTTP Worker client cannot carry TLS material",
            code="tls-scheme-mismatch",
        )
    return HTTPConnection(host, port, timeout=10)
