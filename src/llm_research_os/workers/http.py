"""Loopback HTTP tests stay in-process. Isolated Workers use loopback HTTPS (ADR-0044)."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from llm_research_os.artifacts.errors import (
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreError,
)
from llm_research_os.artifacts.store import (
    CHUNK_SIZE,
    MAX_PUT_BYTES,
    MAX_WORKER_PUT_BYTES,
    LocalArtifactStore,
    parse_artifact_digest,
)
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.bind import require_worker_bind_host
from llm_research_os.workers.errors import WorkerError, WorkerGrantError
from llm_research_os.workers.models import WORKER_RUNTIME_NATIVE_REVIEWED
from llm_research_os.workers.native_claim import (
    NativeControllerContext,
    claim_native,
    is_native_claim,
)
from llm_research_os.workers.plane import DEFAULT_LEASE_SECONDS, Clock, WorkerPlane
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
        native_context: NativeControllerContext | None = None,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._hmac_key = hmac_key
        self._project_id = project_id
        self._source = source
        self._experiment_revision = experiment_revision
        self._clock: Clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._tls = tls
        self._native_context = native_context
        handler = _handler_for(self)
        require_worker_bind_host(host, tls=tls is not None)
        self._httpd = _ReusableLoopbackServer((host, port), handler)
        bound_host, bound_port = self._httpd.server_address[:2]
        require_worker_bind_host(str(bound_host), tls=tls is not None)
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
            lease_seconds=_lease_seconds(),
        )


def _lease_seconds() -> int:
    raw = os.environ.get("RESEARCHOS_LEASE_SECONDS", str(DEFAULT_LEASE_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LEASE_SECONDS
    if value < 1 or value > 3600:
        return DEFAULT_LEASE_SECONDS
    return value


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
                if path == "/v0alpha1/native/inputs":
                    self._native_input()
                    return
                if path == "/v0alpha1/native/materials":
                    self._native_request(materials=True)
                    return
                if path == "/v0alpha1/native/request":
                    self._native_request()
                    return
                if path == "/v0alpha1/native/outputs":
                    self._native_output()
                    return
                if path == "/v0alpha1/work/poll":
                    self._poll()
                    return
                if path == "/v0alpha1/work/identity":
                    self._identity()
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
            except ArtifactNotFoundError:
                self._error(404, WorkerError("input is missing", code="artifact-missing"))
                return
            except WorkerError as exc:
                self._error(400, exc)
                return
            except (
                ArtifactPathError,
                ArtifactStoreError,
                OSError,
                RecursionError,
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
            self.connection.settimeout(10)
            body = json.loads(self._raw_body(limit=4096))
            if type(body) is not dict:
                raise WorkerError("poll body must be an object", code="http-invalid")
            worker_id = _require_str(body, "workerId")
            token = _require_str(body, "grantToken")
            _require_session(server, worker_id, self.headers.get("Authorization"))
            if body.get("waitSeconds", 0) not in {0, 1, 2}:
                raise WorkerError("waitSeconds must be 0, 1, or 2", code="http-invalid")
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                if is_native_claim(plane, worker_id=worker_id, grant_token=token):
                    if server._tls is None:
                        raise WorkerError("native dispatch requires TLS", code="tls-required")
                    if (
                        self.path != "/v0alpha1/work/poll"
                        or set(body) != {"workerId", "grantToken", "waitSeconds"}
                        or type(body["waitSeconds"]) is not int
                        or body["waitSeconds"] != 0
                        or any(
                            len(self.headers.get_all(name, [])) != 1
                            for name in ("Authorization", "Content-Length", "Content-Type")
                        )
                        or self.headers.get("Content-Type") != _JSON
                        or self.headers.get_all("Transfer-Encoding")
                        or self.headers.get_all("Content-Encoding")
                    ):
                        raise WorkerError("invalid native poll request", code="http-invalid")
                    from llm_research_os.workers.native_output import output_lock

                    with output_lock(server._database):
                        claimed = claim_native(
                            plane,
                            context=server._native_context,
                            worker_id=worker_id,
                            grant_token=token,
                        )
                else:
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

        def _identity(self) -> None:
            body = self._json_body()
            worker_id = _require_str(body, "workerId")
            _require_session(server, worker_id, self.headers.get("Authorization"))
            with EventStore(server._database, require_existing=True) as store:
                worker = server._plane(store).rebuild().worker(worker_id)
            if worker is None:
                raise WorkerGrantError("Worker is not registered", code="unknown-worker")
            self._write(200, {"workerId": worker_id, "registered": True, "runtime": worker.runtime})

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
                    require_native_output_transport=True,
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

        def _native_input(self) -> None:
            if server._tls is None:
                raise WorkerError("native transfer requires TLS", code="tls-required")
            self.connection.settimeout(10)
            worker_id = _session_worker(server, self.headers.get("Authorization"))
            token = self.headers.get(_GRANT_HEADER)
            if not token:
                raise WorkerGrantError("grant token is missing", code="grant-token-missing")
            raw = self._raw_body(limit=4096)
            body = json.loads(raw)
            if type(body) is not dict or set(body) != {"digest", "sizeBytes"}:
                raise WorkerError("invalid native input request", code="http-invalid")
            digest = parse_artifact_digest(_require_str(body, "digest"))
            size = body["sizeBytes"]
            if type(size) is not int or not 0 <= size <= MAX_WORKER_PUT_BYTES:
                raise WorkerError("invalid transfer size", code="http-too-large")
            with EventStore(server._database, require_existing=True) as store:
                payload = server._plane(store).authorize_native_input_fetch(
                    worker_id=worker_id,
                    grant_token=token,
                    digest=digest,
                    size_bytes=size,
                )
            if payload is None:
                with server._artifacts.open(digest) as handle:
                    payload = _read_capped(handle, size)
            if len(payload) != size:
                raise WorkerError("input size does not match", code="transfer-size-mismatch")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            self.wfile.write(payload)

        def _native_request(self, *, materials: bool = False) -> None:
            from llm_research_os.canonical import canonical_json
            from llm_research_os.execution.native_reviewed import request_digest
            from llm_research_os.execution.native_reviewed_documents import (
                MAX_REVIEWED_REQUEST_BYTES,
            )

            if server._tls is None:
                raise WorkerError("native request requires TLS", code="tls-required")
            self.connection.settimeout(10)
            expected_path = (
                "/v0alpha1/native/materials" if materials else "/v0alpha1/native/request"
            )
            if (
                self.path != expected_path
                or any(
                    len(self.headers.get_all(name, [])) != 1
                    for name in ("Authorization", _GRANT_HEADER, "Content-Length", "Content-Type")
                )
                or self.headers.get_all("Transfer-Encoding")
                or self.headers.get_all("Content-Encoding")
            ):
                raise WorkerError("invalid native request headers", code="http-invalid")
            if self.headers.get("Content-Type") != "application/json":
                raise WorkerError("invalid native request media type", code="http-invalid")
            worker_id = _session_worker(server, self.headers.get("Authorization"))
            token = self.headers.get(_GRANT_HEADER)
            if not token or json.loads(self._raw_body(limit=4096)) != {}:
                raise WorkerError("native request body must be empty", code="http-invalid")
            with EventStore(server._database, require_existing=True) as store:
                plane = server._plane(store)
                if materials:
                    from llm_research_os.canonical import content_digest
                    from llm_research_os.workers.native_material import material_index

                    index = material_index(plane, worker_id=worker_id, grant_token=token)
                    document = index.model_dump(mode="json", by_alias=True, exclude_none=True)
                    digest = content_digest(document)
                else:
                    request = plane.native_reviewed_request(worker_id=worker_id, grant_token=token)
                    document = request.model_dump(mode="json", by_alias=True, exclude_none=True)
                    digest = request_digest(request)
            payload = canonical_json(document).encode()
            if len(payload) > MAX_REVIEWED_REQUEST_BYTES:
                raise WorkerError("native request exceeds its bound", code="http-too-large")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "X-ResearchOS-Material-Index" if materials else "X-ResearchOS-Request", digest
            )
            self.end_headers()
            self.wfile.write(payload)

        def _native_output(self) -> None:
            from llm_research_os.workers.native_output import complete_native_output, output_lock

            if server._tls is None:
                raise WorkerError("native transfer requires TLS", code="tls-required")
            self.connection.settimeout(10)
            if self.path != "/v0alpha1/native/outputs":
                raise WorkerError("native output path is invalid", code="http-invalid")
            worker_id = _session_worker(server, self.headers.get("Authorization"))
            token = self.headers.get(_GRANT_HEADER)
            lease = self.headers.get("X-ResearchOS-Lease")
            digest = parse_artifact_digest(self.headers.get("X-ResearchOS-Artifact"))
            lengths = self.headers.get_all("Content-Length", [])
            if (
                any(
                    len(self.headers.get_all(name, [])) != 1
                    for name in (
                        "Authorization",
                        _GRANT_HEADER,
                        "X-ResearchOS-Lease",
                        "X-ResearchOS-Artifact",
                        "Content-Type",
                    )
                )
                or self.headers.get("Content-Type") != "application/json"
                or not token
                or not lease
                or len(lengths) != 1
                or self.headers.get_all("Transfer-Encoding")
                or self.headers.get_all("Content-Encoding")
            ):
                raise WorkerError("invalid native output headers", code="http-invalid")
            try:
                size = int(lengths[0])
            except ValueError:
                raise WorkerError("invalid native output size", code="http-invalid") from None
            with EventStore(server._database, require_existing=True) as store:
                server._plane(store).authorize_native_output(
                    worker_id=worker_id,
                    grant_token=token,
                    lease_id=lease,
                    digest=digest,
                    size_bytes=size,
                )
            payload = self._raw_body(limit=size)
            if len(payload) != size:
                raise WorkerError("native output interrupted", code="transfer-size-mismatch")
            with (
                output_lock(server._database),
                EventStore(server._database, require_existing=True) as store,
            ):
                receipt = complete_native_output(
                    server._plane(store),
                    worker_id=worker_id,
                    grant_token=token,
                    lease_id=lease,
                    digest=digest,
                    payload=payload,
                )
            self._write(200, receipt)

        def _put_artifact(self) -> None:
            header = self.headers.get("Authorization")
            if type(header) is not str or not header.startswith("Bearer "):
                raise WorkerGrantError("worker session is missing", code="worker-session-missing")
            worker_id = verify_worker_session(server._hmac_key, header.removeprefix("Bearer "))
            with EventStore(server._database, require_existing=True) as store:
                worker = server._plane(store).rebuild().worker(worker_id)
                if worker is not None and worker.runtime == WORKER_RUNTIME_NATIVE_REVIEWED:
                    raise WorkerError(
                        "native output transport is required", code="native-output-required"
                    )
            payload = self._raw_body(limit=MAX_WORKER_PUT_BYTES)
            record = server._artifacts.put_bytes(payload, limit=MAX_WORKER_PUT_BYTES)
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
                payload = _read_capped(handle, MAX_WORKER_PUT_BYTES)
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

        def _raw_body(self, *, limit: int = MAX_PUT_BYTES) -> bytes:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                raise WorkerError("Content-Length is invalid", code="http-invalid") from None
            if length < 0 or length > limit:
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


def _read_capped(handle: BinaryIO, limit: int) -> bytes:
    """Read until EOF without allocating ``limit`` bytes up front."""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = handle.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise WorkerError("artifact exceeds the put limit", code="http-too-large")
        chunks.append(chunk)
    return b"".join(chunks)


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
