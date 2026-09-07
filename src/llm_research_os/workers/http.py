"""Loopback HTTP tests stay in-process. Isolated Workers use loopback HTTPS (ADR-0044)."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from llm_research_os.artifacts.errors import (
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreError,
)
from llm_research_os.artifacts.store import MAX_PUT_BYTES, LocalArtifactStore, parse_artifact_digest
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.errors import WorkerError, WorkerGrantError
from llm_research_os.workers.plane import Clock, WorkerPlane
from llm_research_os.workers.tls import TlsMaterial
from llm_research_os.workers.tokens import issue_worker_session, verify_worker_session

_JSON = "application/json"
_GRANT_HEADER = "X-ResearchOS-Grant"
_ARTIFACT_PATH = re.compile(r"^/v0alpha1/artifacts/sha256/([0-9a-f]{64})$")


class _ReusableLoopbackServer(ThreadingHTTPServer):
    """SO_REUSEADDR so a control-plane process can restart on the same port."""

    allow_reuse_address = True


class LoopbackWorkerServer:
    """Worker-initiated long poll on loopback. Non-loopback binds fail closed (TM-009)."""

    def __init__(
        self,
        database: Path,
        artifacts: LocalArtifactStore,
        *,
        hmac_key: bytes,
        project_id: str,
        source: str,
        host: str = "127.0.0.1",
        port: int = 0,
        experiment_revision: int = 1,
        clock: Clock | None = None,
        tls: TlsMaterial | None = None,
    ) -> None:
        _require_loopback_host(host)
        self._database = database
        self._artifacts = artifacts
        self._hmac_key = hmac_key
        self._project_id = project_id
        self._source = source
        self._experiment_revision = experiment_revision
        self._clock: Clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._tls = tls
        handler = _handler_for(self)
        self._httpd = _ReusableLoopbackServer((host, port), handler)
        bound_host, bound_port = self._httpd.server_address[:2]
        _require_loopback_host(str(bound_host))
        self.host = str(bound_host)
        self.port = int(bound_port)
        if tls is not None:
            self._httpd.socket = tls.server_context().wrap_socket(
                self._httpd.socket,
                server_side=True,
            )
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self._tls is not None else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def start(self) -> None:
        if self._thread is not None:
            raise WorkerError("loopback worker server is already running", code="server-started")
        thread = threading.Thread(target=self._httpd.serve_forever, name="researchos-worker-http")
        thread.daemon = True
        thread.start()
        self._thread = thread

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def close_listener(self) -> None:
        self._httpd.server_close()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def session_for(self, worker_id: str) -> str:
        return issue_worker_session(self._hmac_key, worker_id=worker_id)

    def _plane(self, store: EventStore) -> WorkerPlane:
        return WorkerPlane(
            store,
            artifacts=self._artifacts,
            hmac_key=self._hmac_key,
            project_id=self._project_id,
            source=self._source,
            experiment_revision=self._experiment_revision,
            clock=self._clock,
        )


def _require_loopback_host(host: str) -> None:
    try:
        ip = ip_address(host)
    except ValueError:
        raise WorkerError(
            "worker server host must be a loopback IP",
            code="bind-not-loopback",
        ) from None
    if not ip.is_loopback:
        raise WorkerError("worker server host must be a loopback IP", code="bind-not-loopback")


def _handler_for(server: LoopbackWorkerServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            try:
                self._get_artifact()
            except WorkerGrantError as exc:
                self._error(401, exc)
            except ArtifactNotFoundError as exc:
                self._error(404, WorkerError(str(exc), code="artifact-missing"))
            except WorkerError as exc:
                status = 404 if exc.code == "http-not-found" else 400
                self._error(status, exc)
            except (ArtifactPathError, ArtifactStoreError, OSError, ValueError):
                self._error(
                    400,
                    WorkerError("worker HTTP request is invalid", code="http-invalid"),
                )

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/v0alpha1/work/poll":
                    self._poll()
                    return
                if path == "/v0alpha1/work/heartbeat":
                    self._heartbeat()
                    return
                if path == "/v0alpha1/work/complete":
                    self._complete()
                    return
                if path == "/v0alpha1/work/fail":
                    self._fail()
                    return
                if path == "/v0alpha1/artifacts":
                    self._put_artifact()
                    return
            except WorkerGrantError as exc:
                self._error(401, exc)
                return
            except WorkerError as exc:
                self._error(400, exc)
                return
            except (
                ArtifactPathError,
                ArtifactStoreError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ):
                self._error(
                    400,
                    WorkerError("worker HTTP request is invalid", code="http-invalid"),
                )
                return
            self._error(404, WorkerError("unknown worker path", code="http-not-found"))

        def _poll(self) -> None:
            body = self._json_body()
            worker_id = _require_str(body, "workerId")
            token = _require_str(body, "grantToken")
            _require_session(server, worker_id, self.headers.get("Authorization"))
            if body.get("waitSeconds", 0) not in {0, 1, 2}:
                raise WorkerError("waitSeconds must be 0, 1, or 2", code="http-invalid")
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                claimed = plane.poll(worker_id=worker_id, grant_token=token)
            if claimed is None:
                self._write(204, None)
                return
            self._write(
                200,
                {
                    "leaseId": claimed.lease_id,
                    "taskId": claimed.task_id,
                    "runId": claimed.run_id,
                    "attemptId": claimed.attempt_id,
                    "imageDigest": claimed.image_digest,
                    "configDigest": claimed.config_digest,
                    "config": claimed.config,
                    "inputs": claimed.inputs,
                    "runtime": claimed.runtime,
                    "imageMediaType": claimed.image_media_type,
                    "expiresAt": claimed.expires_at,
                    "resumed": claimed.resumed,
                    "cancelRequested": claimed.cancel_requested,
                },
            )

        def _heartbeat(self) -> None:
            body = self._json_body()
            worker_id = _require_str(body, "workerId")
            lease_id = _require_str(body, "leaseId")
            session = _require_session(server, worker_id, self.headers.get("Authorization"))
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                before = store.last_sequence()
                cancel_requested = plane.heartbeat(
                    worker_id=worker_id, session=session, lease_id=lease_id
                )
                after = store.last_sequence()
            if after != before:
                raise WorkerError("heartbeat must not append facts", code="heartbeat-on-log")
            self._write(200, {"cancelRequested": cancel_requested})

        def _complete(self) -> None:
            body = self._json_body()
            worker_id = _require_str(body, "workerId")
            token = _require_str(body, "grantToken")
            lease_id = _require_str(body, "leaseId")
            result_digest = _require_str(body, "resultDigest")
            artifact_digest = _require_str(body, "artifactDigest")
            _require_session(server, worker_id, self.headers.get("Authorization"))
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                stored = plane.complete(
                    worker_id=worker_id,
                    grant_token=token,
                    lease_id=lease_id,
                    result_digest=result_digest,
                    artifact_digest=artifact_digest,
                )
            self._write(
                200,
                {
                    "eventId": stored.event.id,
                    "type": stored.event.type,
                    "sequence": stored.sequence,
                },
            )

        def _fail(self) -> None:
            body = self._json_body()
            worker_id = _require_str(body, "workerId")
            token = _require_str(body, "grantToken")
            lease_id = _require_str(body, "leaseId")
            reason_code = _require_str(body, "reasonCode")
            _require_session(server, worker_id, self.headers.get("Authorization"))
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                stored = plane.fail(
                    worker_id=worker_id,
                    grant_token=token,
                    lease_id=lease_id,
                    reason_code=reason_code,
                )
            self._write(
                200,
                {
                    "eventId": stored.event.id,
                    "type": stored.event.type,
                    "sequence": stored.sequence,
                },
            )

        def _put_artifact(self) -> None:
            header = self.headers.get("Authorization")
            if type(header) is not str or not header.startswith("Bearer "):
                raise WorkerGrantError("worker session is missing", code="worker-session-missing")
            verify_worker_session(server._hmac_key, header.removeprefix("Bearer "))
            payload = self._raw_body()
            record = server._artifacts.put_bytes(payload)
            self._write(201, {"digest": record.digest, "sizeBytes": record.size_bytes})

        def _get_artifact(self) -> None:
            path = urlparse(self.path).path
            matched = _ARTIFACT_PATH.fullmatch(path)
            if matched is None:
                raise WorkerError("unknown worker path", code="http-not-found")
            digest = parse_artifact_digest(f"sha256:{matched.group(1)}")
            worker_id = _session_worker(server, self.headers.get("Authorization"))
            grant_token = self.headers.get(_GRANT_HEADER)
            if type(grant_token) is not str or grant_token == "":
                raise WorkerGrantError("grant token is missing", code="grant-token-missing")
            with EventStore(server._database, require_existing=True) as store:
                server._plane(store).authorize_image_fetch(
                    worker_id=worker_id,
                    grant_token=grant_token,
                    image_digest=digest,
                )
            with server._artifacts.open(digest) as handle:
                payload = handle.read(MAX_PUT_BYTES + 1)
            if len(payload) > MAX_PUT_BYTES:
                raise WorkerError("artifact exceeds the put limit", code="http-too-large")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json_body(self) -> dict[str, Any]:
            raw = self._raw_body()
            document = json.loads(raw.decode("utf-8"))
            if type(document) is not dict:
                raise WorkerError("JSON body must be an object", code="http-invalid")
            return document

        def _raw_body(self) -> bytes:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                raise WorkerError("Content-Length is invalid", code="http-invalid") from None
            if length < 0 or length > MAX_PUT_BYTES:
                raise WorkerError("request body exceeds the put limit", code="http-too-large")
            return self.rfile.read(length)

        def _write(self, status: int, payload: dict[str, object] | None) -> None:
            if payload is None:
                self.send_response(status)
                self.end_headers()
                return
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", _JSON)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, exc: WorkerError) -> None:
            self._write(status, {"code": exc.code, "error": type(exc).__name__})

    return Handler


def _require_session(server: LoopbackWorkerServer, worker_id: str, header: str | None) -> str:
    token = _session_token(header)
    session_worker = verify_worker_session(server._hmac_key, token)
    if session_worker != worker_id:
        raise WorkerGrantError("worker session does not match", code="worker-session-mismatch")
    return token


def _session_worker(server: LoopbackWorkerServer, header: str | None) -> str:
    return verify_worker_session(server._hmac_key, _session_token(header))


def _session_token(header: str | None) -> str:
    if type(header) is not str or not header.startswith("Bearer "):
        raise WorkerGrantError("worker session is missing", code="worker-session-missing")
    return header.removeprefix("Bearer ")


def _require_str(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if type(value) is not str or value == "":
        raise WorkerError(f"{key} is required", code="http-invalid")
    return value
