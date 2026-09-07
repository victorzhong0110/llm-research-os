"""Outbound Worker client for the loopback long-poll binding."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from http.client import HTTPConnection
from typing import Any
from urllib.parse import urlparse

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.binding import json_object, require_execution_digest
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick


@dataclass(frozen=True, slots=True)
class WorkerClient:
    base_url: str
    worker_id: str
    session: str
    grant_token: str

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
        parsed = urlparse(self.base_url)
        connection = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            connection.request(
                "POST",
                "/v0alpha1/artifacts",
                body=payload,
                headers={
                    "Authorization": f"Bearer {self.session}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(payload)),
                },
            )
            response = connection.getresponse()
            body = response.read()
        except OSError as exc:
            raise WorkerError("worker transport is unavailable", code="http-disconnect") from exc
        finally:
            connection.close()
        if response.status != 201:
            raise WorkerError("artifact upload failed", code="http-artifact-failed")
        document = json.loads(body.decode("utf-8"))
        digest = document.get("digest")
        if type(digest) is not str:
            raise WorkerError("artifact upload omitted digest", code="http-artifact-failed")
        return digest

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
        parsed = urlparse(self.base_url)
        payload = json.dumps(document, ensure_ascii=True).encode("utf-8")
        connection = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            connection.request(
                method,
                path,
                body=payload,
                headers={
                    "Authorization": f"Bearer {self.session}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                },
            )
            response = connection.getresponse()
            raw = response.read()
        except OSError as exc:
            raise WorkerError("worker transport is unavailable", code="http-disconnect") from exc
        finally:
            connection.close()
        if response.status == 204:
            return 204, None
        if not raw:
            return response.status, None
        decoded = json.loads(raw.decode("utf-8"))
        if type(decoded) is not dict:
            raise WorkerError("worker HTTP JSON must be an object", code="http-invalid")
        return response.status, decoded
