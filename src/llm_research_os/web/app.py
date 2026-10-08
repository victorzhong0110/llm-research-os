"""The local API as a standard-library WSGI application.

TM-083. The R09 plan named optional FastAPI/ASGI. This is a deliberate
deviation: the local workbench is a single-user loopback read surface, and
routing it on ``wsgiref`` keeps the installed core free of a web framework and
its transitive dependencies. The external contract is unchanged — versioned
JSON, structured errors, same-origin sessions, bounded projections, and
resumable SSE with a polling fallback.

The module holds no authority: it serves verified reads and bounded previews.
Mutating browser commands are R11 and reuse the same shared services.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationCommand
from llm_research_os.application.service import ApplicationService
from llm_research_os.application.workspace import Workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.events.models import CLOUD_EVENTS_INTEGER_MAX
from llm_research_os.storage import EventStore
from llm_research_os.web.assets import AssetError
from llm_research_os.web.assets import load as load_asset
from llm_research_os.web.contracts import CommandReceipt, ResearchLedgerView
from llm_research_os.web.errors import LOCAL_API_VERSION, LocalApiError, bad_request, not_found
from llm_research_os.web.inspection import safe_document
from llm_research_os.web.limits import (
    ConcurrencyGate,
    RequestLimits,
    bounded_document,
    decode_bounded_json,
    document_kind,
    json_bytes,
    read_bounded_body,
)
from llm_research_os.web.projections import (
    ReadProjections,
    decode_cursor,
    encode_cursor,
    parse_limit,
)
from llm_research_os.web.sessions import (
    BOOTSTRAP_HEADER_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    BrowserSession,
    SessionStore,
    check_host,
    check_origin,
    parse_cookies,
    session_cookie_header,
)

API_PREFIX: Final = "/api/v0alpha1"
DEFAULT_SSE_IDLE_SECONDS: Final = 20.0
DEFAULT_SSE_POLL_SECONDS: Final = 0.5
MAX_STREAM_EVENTS: Final = 200

_REASON: Final[dict[int, str]] = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

Headers = list[tuple[str, str]]
Response = tuple[int, Headers, bytes]
Stream = tuple[int, Headers, Iterable[bytes]]


class LocalApi:
    """One workspace's bounded read surface."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        sessions: SessionStore,
        allowed_hosts: frozenset[str],
        allowed_origin: str,
        limits: RequestLimits | None = None,
        stream_idle_seconds: float = DEFAULT_SSE_IDLE_SECONDS,
        stream_poll_seconds: float = DEFAULT_SSE_POLL_SECONDS,
    ) -> None:
        self._workspace = workspace
        self._sessions = sessions
        self._limits = limits or RequestLimits()
        self._allowed_hosts = allowed_hosts
        self._allowed_origin = allowed_origin
        self._gate = ConcurrencyGate(self._limits.max_concurrent_requests)
        self._stream_idle_seconds = stream_idle_seconds
        self._stream_poll_seconds = stream_poll_seconds

    @property
    def limits(self) -> RequestLimits:
        return self._limits

    def wsgi(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        """The WSGI entrypoint. Never raises; every fault becomes a safe body."""

        try:
            self._gate.__enter__()
        except LocalApiError as exc:
            error_status, error_headers, error_body = self._error(exc)
            start_response(
                f"{error_status} {_REASON.get(error_status, 'Status')}",
                [*error_headers, ("Content-Length", str(len(error_body)))],
            )
            return [error_body]
        try:
            status, headers, body = self._dispatch(environ)
        except LocalApiError as exc:
            status, headers, body = self._error(exc)
        except ApplicationError:
            status, headers, body = self._error(
                LocalApiError(
                    "workspace-invalid",
                    "The workspace could not answer this request.",
                    status=503,
                )
            )
        except Exception:
            status, headers, body = self._error(
                LocalApiError("internal-error", "The request could not be completed.", status=500)
            )
        if isinstance(body, bytes):
            self._gate.__exit__(None, None, None)
            start_response(
                f"{status} {_REASON.get(status, 'Status')}",
                [*headers, ("Content-Length", str(len(body)))],
            )
            return [body]
        # SSE streams yield bytes chunks; the total length is unknown up front.
        try:
            start_response(f"{status} {_REASON.get(status, 'Status')}", headers)
        except Exception:
            self._gate.__exit__(None, None, None)
            raise
        return _GatedStream(body, self._gate)

    def _error(self, exc: LocalApiError) -> Response:
        return exc.status, _json_headers(), json_bytes(exc.document())

    def _json(
        self, document: dict[str, Any], *, status: int = 200, extra: Headers | None = None
    ) -> Response:
        return (
            status,
            [*_json_headers(), *(extra or [])],
            json_bytes({"apiVersion": LOCAL_API_VERSION, **document}),
        )

    def _dispatch(self, environ: dict[str, Any]) -> Response | Stream:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "")) or "/"
        check_host(environ, allowed_hosts=self._allowed_hosts)

        if path == "/api/health" and method == "GET":
            return self._json({"kind": "Health", "status": "ready"})
        if not path.startswith(API_PREFIX):
            return self._asset(environ, path, method)

        check_origin(environ, method=method, allowed_origin=self._allowed_origin)
        route = path[len(API_PREFIX) :]
        cookies = parse_cookies(environ.get("HTTP_COOKIE"))

        if route == "/session":
            return self._session(environ, method, cookies)

        session = self._sessions.authenticate(cookies.get(SESSION_COOKIE_NAME))
        csrf_header = environ.get(_header_key(CSRF_HEADER_NAME))
        self._sessions.check_csrf(
            session, csrf_header if isinstance(csrf_header, str) else None, method=method
        )
        if route == "/stream":
            if method != "GET":
                raise LocalApiError("method-not-allowed", "Stream with GET.", status=405)
            return self._stream(resume=_resume(environ, _query(environ)))
        if route == "/commands":
            if method != "POST":
                raise LocalApiError("method-not-allowed", "Submit a command with POST.", status=405)
            return self._command(environ)
        if route == "/preview/document":
            if method != "POST":
                raise LocalApiError(
                    "method-not-allowed", "Preview a document with POST.", status=405
                )
            return self._preview(environ, _query(environ))
        if method != "GET":
            raise LocalApiError(
                "method-not-allowed",
                "The R09 local API is read-only; mutating browser commands arrive with R11.",
                status=405,
            )
        return self._read(environ, route, session)

    def _asset(self, environ: dict[str, Any], path: str, method: str) -> Response | Stream:
        """Serve the built workbench bundle.

        The session check stays in front of every API route but not in front of
        the bundle itself: the operator has to be able to load the page in order
        to exchange the bootstrap secret for a session.
        """

        if method not in {"GET", "HEAD"}:
            raise LocalApiError(
                "method-not-allowed", "The workbench bundle is read-only.", status=405
            )
        try:
            asset = load_asset(path)
        except AssetError as exc:
            if exc.code == "asset-missing":
                raise not_found("No such workbench resource.") from exc
            raise bad_request(
                "parameter-invalid", "The requested asset path is not valid."
            ) from exc
        headers: Headers = [
            ("Content-Type", asset.content_type),
            ("ETag", asset.etag),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if asset.immutable:
            headers.append(("Cache-Control", "public, max-age=31536000, immutable"))
        else:
            # The index must not be cached, or a rebuilt bundle stays invisible.
            headers.append(("Cache-Control", "no-store"))
        if_none = environ.get("HTTP_IF_NONE_MATCH")
        if if_none is not None and if_none == asset.etag:
            return 304, headers, b""
        return 200, headers, asset.body

    def _session(self, environ: dict[str, Any], method: str, cookies: dict[str, str]) -> Response:
        if method == "POST":
            presented = environ.get(_header_key(BOOTSTRAP_HEADER_NAME))
            session = self._sessions.exchange_bootstrap(
                presented if isinstance(presented, str) else None
            )
            return self._json(
                {"kind": "BrowserSession", **session.document()},
                status=201,
                extra=[("Set-Cookie", session_cookie_header(session))],
            )
        if method == "DELETE":
            token = cookies.get(SESSION_COOKIE_NAME)
            if token:
                self._sessions.forget(token)
            return 204, [("Set-Cookie", f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0")], b""
        if method != "GET":
            raise LocalApiError(
                "method-not-allowed", "Use POST or DELETE for sessions.", status=405
            )
        session = self._sessions.authenticate(cookies.get(SESSION_COOKIE_NAME))
        return self._json({"kind": "BrowserSession", **session.document()})

    def _read(
        self, environ: dict[str, Any], route: str, session: BrowserSession
    ) -> Response | Stream:
        query = _query(environ)
        if route == "/capabilities":
            return self._json(
                {
                    "kind": "Capabilities",
                    "readOnly": True,
                    "limits": self._limits.document(),
                    "session": session.document(),
                    "pollFallbackSeconds": self._stream_poll_seconds,
                }
            )
        with self._open_store() as store, store.query_budget():
            views = ReadProjections(
                store, LocalArtifactStore(self._workspace.cas_root), self._workspace.project_id
            )
            if route == "/workspace":
                return self._json(
                    {
                        "kind": "WorkspaceView",
                        **self._workspace.describe(),
                        "highWaterMark": store.last_sequence(),
                    }
                )
            if route == "/research":
                return self._research()
            if route == "/events":
                page = views.event_page(
                    cursor=query.get("cursor"),
                    limit=parse_limit(query.get("limit")),
                    event_types=_event_types(query.get("type")),
                    run_id=query.get("runId"),
                )
                return self._json(page.document("EventPage"))
            if route == "/revisions":
                page = views.revision_page(
                    cursor=query.get("cursor"), limit=parse_limit(query.get("limit"))
                )
                return self._json(page.document("RevisionPage"))
            if route == "/runs":
                page = views.run_page(
                    cursor=query.get("cursor"), limit=parse_limit(query.get("limit"))
                )
                return self._json(page.document("RunPage"))
            if route.startswith("/inspect/artifacts/"):
                try:
                    via = json.loads(query.get("via", "[]"))
                except (ValueError, RecursionError) as exc:
                    raise bad_request("parameter-invalid", "The lineage path is invalid.") from exc
                if (
                    not isinstance(via, list)
                    or len(via) > 8
                    or any(type(v) is not str for v in via)
                ):
                    raise bad_request("parameter-invalid", "The lineage path is invalid.")
                return self._json(
                    {
                        "kind": "InspectionView",
                        **views.artifact_inspection(
                            route[len("/inspect/artifacts/") :],
                            tuple(via),
                        ),
                    }
                )
            for prefix, inspect in (
                ("/inspect/events/", views.event_document),
                ("/inspect/revisions/", views.revision_document),
            ):
                if route.startswith(prefix):
                    return self._json({"kind": "InspectionView", **inspect(route[len(prefix) :])})
            if route == "/artifacts/" or route.startswith("/artifacts/"):
                digest = route[len("/artifacts/") :]
                if not digest or "/" in digest:
                    raise not_found("No such local API resource.")
                return self._json({"kind": "ArtifactView", **views.artifact_document(digest)})
        raise not_found("No such local API resource.")

    def _open_store(self) -> EventStore:
        """Open the existing control store read-only; never create or migrate one."""

        if not self._workspace.control_db.exists():
            raise LocalApiError(
                "workspace-invalid", "The workspace event store does not exist.", status=503
            )
        return EventStore(self._workspace.control_db, create=False)

    def _command(self, environ: dict[str, Any]) -> Response:
        """Execute one caller-owned application command.

        The browser supplies the command identity. The shared service owns the
        durable receipt, so a double-click, a retransmission or a second window
        replays the first receipt instead of appending a second fact. The
        browser cannot mint authority: it dispatches commands that a human
        already authored, and every receipt reports a request rather than an
        observed process outcome.
        """

        payload = read_bounded_body(
            environ["wsgi.input"],
            content_length=environ.get("CONTENT_LENGTH"),
            limits=self._limits,
        )
        if not payload:
            raise bad_request("document-invalid", "Send one application command document.")
        document = decode_bounded_json(payload, limits=self._limits)
        try:
            command = ApplicationCommand.model_validate(document)
        except ValidationError as exc:
            raise bad_request(
                "document-invalid", "The command document failed validation."
            ) from exc
        self._check_command_paths(command)
        try:
            receipt = ApplicationService.open(self._workspace.root).execute(command)
        except ApplicationError as exc:
            raise LocalApiError(
                "command-refused",
                "The command was refused by the shared service.",
                status=409,
            ) from exc
        # Validated against the same contract the browser types are generated
        # from, so a shape drift fails here rather than in the client.
        try:
            document = CommandReceipt.model_validate(receipt).model_dump(mode="json", by_alias=True)
        except ValidationError as exc:
            raise LocalApiError(
                "internal-error", "The command receipt did not match its contract.", status=500
            ) from exc
        document["result"] = safe_document(document["result"])
        document["resultDigest"] = content_digest(document["result"])
        return self._json(document)

    def _check_command_paths(self, command: ApplicationCommand) -> None:
        """Browser inputs are operator-staged workspace files, never arbitrary host reads."""
        if command.operation.kind not in {
            "plan.preflight",
            "run.show",
            "native.start",
            "native.restore",
            "native.observe",
            "native.inspect",
            "backup.verify",
            "backup.restore",
            "run.cancel",
            "authorization.revoke",
            "research.draft",
            "research.submit",
            "research.record",
            "evidence.import",
            "model.inspect",
            "model.observe",
            "model.generate",
            "research.budget",
            "proposal.validate",
            "proposal.submit",
            "research.decision",
            "evaluation.run",
            "evaluation.compare",
            "conclusion.record",
        }:
            raise LocalApiError(
                "command-refused", "This command is not exposed to the browser.", status=409
            )
        root = self._workspace.root.resolve()
        operation = command.operation.model_dump(mode="json", by_alias=True)
        for key in ("document", "request", "old", "new", "registry"):
            value = operation.get(key)
            if isinstance(value, dict):
                continue  # Inline typed research documents are not host paths.
            paths = value if isinstance(value, list) else ([] if value is None else [value])
            for name in paths:
                path = Path(name)
                if not path.is_absolute():
                    raise LocalApiError(
                        "command-refused", "Stage inputs inside the workspace.", status=409
                    )
                try:
                    relative = path.relative_to(root)
                    current = root
                    for part in relative.parts:
                        current = current / part
                        if current.is_symlink():
                            raise ValueError("symlink")
                    path.resolve(strict=True).relative_to(root)
                except (ValueError, OSError):
                    raise LocalApiError(
                        "command-refused", "Stage inputs inside the workspace.", status=409
                    ) from None

    def _preview(self, environ: dict[str, Any], query: dict[str, str]) -> Response:
        payload = read_bounded_body(
            environ["wsgi.input"],
            content_length=environ.get("CONTENT_LENGTH"),
            limits=self._limits,
        )
        if not payload:
            raise bad_request("document-invalid", "Send a bounded document to preview.")
        kind = document_kind(environ.get("CONTENT_TYPE"), query.get("name"))
        document = bounded_document(payload, kind=kind, limits=self._limits)
        decoded: dict[str, Any] = (
            {"characters": document["characters"]} if kind == "pdf" else document
        )
        return self._json(
            {
                "kind": "DocumentPreview",
                "documentKind": kind,
                "byteLength": len(payload),
                "decoded": decoded,
            }
        )

    def _research(self) -> Response:
        """Bounded research ledger for this project.

        Read-only. The ledger is a fold of proposal, dissent, decision and
        question facts, so the browser sees the same disagreements a CLI replay
        would, and records nothing by rendering it.
        """

        service = ApplicationService.open(self._workspace.root)
        try:
            with self._open_store() as store:
                ledger: dict[str, Any] = service.read_research_ledger(store)
        except ApplicationError as exc:
            raise LocalApiError(
                "command-refused", "The research ledger could not be read.", status=409
            ) from exc
        limit = 50
        document = {
            "kind": "ResearchLedgerView",
            "projectId": str(ledger["projectId"]),
            "lastSequence": int(ledger["lastSequence"]),
            "decisionCount": int(ledger["decisionCount"]),
            "openQuestionCount": int(ledger["openQuestionCount"]),
            "answeredQuestionCount": int(ledger["answeredQuestionCount"]),
            "rationaleCharacters": int(ledger["rationaleCharacters"]),
            "overriddenDissentCount": int(ledger["overriddenDissentCount"]),
            "proposals": list(ledger["proposals"])[:limit],
            "dissents": list(ledger["dissents"])[:limit],
            "decisions": list(ledger["decisions"])[:limit],
            "questions": list(ledger["questions"])[:limit],
            "withheld": {
                key: max(0, len(ledger[key]) - limit)
                for key in ("proposals", "dissents", "decisions", "questions")
            },
        }
        # Validated against the same contract the browser types come from.
        try:
            body = ResearchLedgerView.model_validate(document).model_dump(
                mode="json", by_alias=True
            )
        except ValidationError as exc:
            raise LocalApiError(
                "internal-error", "The research ledger did not match its contract.", status=500
            ) from exc
        return self._json(body)

    def _stream(self, *, resume: int) -> Stream:
        """Resumable SSE. ``Last-Event-ID`` or ``?cursor=`` resumes without a gap.

        The body is a generator, so it cannot borrow the request's store: that
        connection is closed before the first byte is written. Each poll opens
        its own verified read instead.
        """

        workspace = self._workspace

        def body() -> Iterable[bytes]:
            cursor = resume
            emitted = 0
            deadline = time.monotonic() + self._stream_idle_seconds
            yield b": open\n\n"
            while emitted < MAX_STREAM_EVENTS and time.monotonic() < deadline:
                with self._open_store() as store, store.query_budget():
                    page = ReadProjections(
                        store,
                        LocalArtifactStore(workspace.cas_root),
                        workspace.project_id,
                    ).event_page(cursor=encode_cursor(cursor), limit=100)
                if page.items:
                    for item in page.items:
                        if emitted >= MAX_STREAM_EVENTS:
                            break
                        sequence = int(item["sequence"])
                        yield b"id: " + str(sequence).encode("ascii") + b"\n"
                        yield b"data: " + json_bytes(item) + b"\n\n"
                        cursor = sequence
                        emitted += 1
                    yield (
                        b"event: high-water\ndata: "
                        + json_bytes({"highWaterMark": page.high_water_mark})
                        + b"\n\n"
                    )
                    deadline = time.monotonic() + self._stream_idle_seconds
                    continue
                time.sleep(self._stream_poll_seconds)
            yield b"event: idle\ndata: " + json_bytes({"lastSequence": cursor}) + b"\n\n"

        return (
            200,
            [
                ("Content-Type", "text/event-stream; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("X-Accel-Buffering", "no"),
            ],
            body(),
        )


class _GatedStream:
    """Retain a concurrency slot until exhausted or closed, even before first next."""

    def __init__(self, body: Iterable[bytes], gate: ConcurrencyGate) -> None:
        self._body = iter(body)
        self._gate = gate
        self._closed = False

    def __iter__(self) -> _GatedStream:
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        try:
            return next(self._body)
        except StopIteration:
            self.close()
            raise
        except Exception:
            self.close()
            # Headers are already committed; send only a fixed stream error.
            return b'event: error\ndata: {"code":"event-store-unavailable"}\n\n'

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                close = getattr(self._body, "close", None)
                if callable(close):
                    close()
            finally:
                self._gate.__exit__(None, None, None)


def _header_key(name: str) -> str:
    """Derive the WSGI environ key from the header name so the two cannot drift."""

    return "HTTP_" + name.upper().replace("-", "_")


def _json_headers() -> Headers:
    return [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]


def _resume(environ: dict[str, Any], query: dict[str, str]) -> int:
    header = environ.get("HTTP_LAST_EVENT_ID")
    if isinstance(header, str) and header.strip():
        return _stream_cursor(header.strip())
    return _stream_cursor(query.get("cursor"))


def _stream_cursor(raw: str | None) -> int:
    # EventSource echoes the decimal id emitted on the wire, not a page token.
    if raw and raw.isascii() and raw.isdigit():
        if len(raw) > 10 or int(raw) > CLOUD_EVENTS_INTEGER_MAX:
            raise bad_request("parameter-invalid", "The stream sequence is out of bounds.")
        return int(raw)
    return decode_cursor(raw)


def _event_types(raw: str | None) -> frozenset[str] | None:
    if not raw:
        return None
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    if not parts or len(parts) > 32:
        raise bad_request("parameter-invalid", "Send at most 32 event types.")
    return frozenset(parts)


def _query(environ: dict[str, Any]) -> dict[str, str]:
    try:
        parsed = parse_qs(
            environ.get("QUERY_STRING") or "", keep_blank_values=True, max_num_fields=32
        )
    except ValueError as exc:
        raise bad_request("parameter-invalid", "The query has too many fields.") from exc
    return {key: values[0] for key, values in parsed.items() if values}
