"""Loopback server entrypoint for the local API.

Binds 127.0.0.1 only. The one-time bootstrap secret is printed to the operator's
own terminal, never written to disk, and never accepted from a URL query.
"""

from __future__ import annotations

import socket
import sys
import threading
from contextlib import suppress
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Final
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import load_workspace
from llm_research_os.web.app import LocalApi
from llm_research_os.web.limits import RequestLimits
from llm_research_os.web.sessions import SessionStore

LOOPBACK_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8787
MAX_PORT: Final = 65535
SOCKET_TIMEOUT_SECONDS: Final = 10.0


class BoundedWSGIServer(ThreadingMixIn, WSGIServer):
    """Bound socket handlers before creating threads; no unbounded queue."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _QuietHandler(WSGIRequestHandler):
    """Suppress the default stderr access log; it echoes request paths.

    The socket timeout is the slow-client bound. Without it a client that opens
    a connection and then stops sending holds a request thread and the bounded
    concurrency slot with it, which is exactly the denial the R09 limits exist
    to prevent.
    """

    timeout = SOCKET_TIMEOUT_SECONDS
    request_deadline_seconds = 30.0

    def log_message(self, format: str, *args: Any) -> None:
        return

    def handle(self) -> None:
        try:
            self.request.settimeout(SOCKET_TIMEOUT_SECONDS)
        except OSError:
            return
        timer = threading.Timer(self.request_deadline_seconds, self._expire_request)
        timer.daemon = True
        timer.start()
        try:
            super().handle()
        finally:
            timer.cancel()

    def _expire_request(self) -> None:
        with suppress(OSError):
            self.request.shutdown(socket.SHUT_RDWR)


def build_api(
    root: Path,
    *,
    host: str = LOOPBACK_HOST,
    port: int = DEFAULT_PORT,
    sessions: SessionStore | None = None,
    limits: RequestLimits | None = None,
) -> LocalApi:
    """Construct the WSGI app and its exact allowed authority set."""

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("the local API only binds a loopback address")
    if not 1 <= port <= MAX_PORT:
        raise ValueError(f"port must be in 1..{MAX_PORT}")
    workspace = load_workspace(root)
    authority = f"{host}:{port}"
    return LocalApi(
        workspace,
        sessions=sessions or SessionStore(),
        allowed_hosts=frozenset({authority, f"{host}:{DEFAULT_PORT}"}),
        allowed_origin=f"http://{authority}",
        limits=limits,
    )


def serve(root: Path, *, host: str = LOOPBACK_HOST, port: int = DEFAULT_PORT) -> int:
    """Run the local API until interrupted. Prints the bootstrap URL once."""

    try:
        sessions = SessionStore()
        api = build_api(root, host=host, port=port, sessions=sessions)
    except (ApplicationError, ValueError, OSError):
        print(
            '{"code":"workspace-invalid","message":"the workspace could not be opened"}',
            file=sys.stderr,
        )
        return 2
    try:
        server = make_server(
            host, port, api.wsgi, handler_class=_QuietHandler, server_class=BoundedWSGIServer
        )
    except OSError:
        print(
            '{"code":"listener-unavailable","message":"the local listener could not start"}',
            file=sys.stderr,
        )
        return 2
    bound = server.server_address[0]
    bound_host = bound[0] if isinstance(bound, tuple) else host
    bound_port = bound[1] if isinstance(bound, tuple) and isinstance(bound[1], int) else port
    print(f"researchos local API listening on http://{bound_host}:{bound_port}")
    print(
        "Open once in your browser, then the secret is spent:\n"
        f"  http://{bound_host}:{bound_port}/#bootstrap={sessions.bootstrap_token}"
    )
    sys.stdout.flush()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


def port_is_free(host: str, port: int) -> bool:
    """Report whether the loopback port can be bound; used by the doctor path."""

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True
