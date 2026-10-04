"""R09 local API over a real loopback socket.

The WSGI-caller tests in ``test_web_api.py`` cover the middleware order with an
in-memory stream. They cannot catch a hang that only appears when ``wsgi.input``
is a real ``BufferedReader`` over a keep-alive socket. That is exactly what
happened: a request body smaller than the read chunk blocked forever, and CI
would not have seen it. These tests bind an ephemeral loopback port and speak
HTTP/1.1 to the real server.
"""

from __future__ import annotations

import http.client
import io
import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.limits import read_bounded_body
from llm_research_os.web.serve import BoundedWSGIServer
from llm_research_os.web.sessions import SessionStore

BOOTSTRAP = "socket-bootstrap-secret"
REQUEST_TIMEOUT = 10.0


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Server:
    """A real loopback HTTP server around the WSGI app."""

    def __init__(self, root: Path) -> None:
        self.port = _free_port()
        self.authority = f"127.0.0.1:{self.port}"
        self.origin = f"http://{self.authority}"
        self.api = LocalApi(
            load_workspace(root),
            sessions=SessionStore(bootstrap_token=BOOTSTRAP),
            allowed_hosts=frozenset({self.authority}),
            allowed_origin=self.origin,
            stream_idle_seconds=0.2,
            stream_poll_seconds=0.01,
        )
        self._server = make_server(
            "127.0.0.1",
            self.port,
            self.api.wsgi,
            handler_class=_Quiet,
            server_class=BoundedWSGIServer,
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def client(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=REQUEST_TIMEOUT)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    root = tmp_path / "socket-project"
    init_workspace(
        root,
        project_id="proj-socket",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "socket-worker",
    )
    with EventStore(root / "control.db"):
        pass
    instance = Server(root)
    try:
        yield instance
    finally:
        instance.close()


def _authenticate(server: Server) -> tuple[http.client.HTTPConnection, str]:
    connection = server.client()
    connection.request(
        "POST",
        "/api/v0alpha1/session",
        headers={
            "Host": server.authority,
            "X-ResearchOS-Bootstrap": BOOTSTRAP,
            "Origin": server.origin,
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 201
    cookie = str(response.getheader("set-cookie")).split(";", 1)[0]
    return connection, f"{cookie}; {payload['csrfHeader']}: {payload['csrfToken']}"


def test_health_answers_over_a_real_socket(server: Server) -> None:
    connection = server.client()
    connection.request("GET", "/api/health", headers={"Host": server.authority})
    response = connection.getresponse()
    assert response.status == 200
    assert json.loads(response.read().decode("utf-8"))["status"] == "ready"
    connection.close()


def test_small_post_body_does_not_hang(server: Server) -> None:
    """Regression: a 7-byte body against a 64 KiB read chunk must return promptly.

    Reading to EOF blocks on a keep-alive connection, and a socket
    ``BufferedReader.read(n)`` blocks for the full count. Both hang here.
    """

    connection, auth = _authenticate(server)
    connection.request(
        "POST",
        "/api/v0alpha1/preview/document?name=a.json",
        body=b'{"x":1}',
        headers={
            "Host": server.authority,
            "Content-Type": "application/json",
            "Origin": server.origin,
            "Cookie": auth.split("; ", 1)[0],
            "X-ResearchOS-CSRF": auth.split(": ", 1)[1],
        },
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert body["decoded"] == {"x": 1}
    connection.close()


def test_body_at_the_chunk_boundary_does_not_hang(server: Server) -> None:
    connection, auth = _authenticate(server)
    payload = b'{"k":"' + b"a" * 65_500 + b'"}'
    connection.request(
        "POST",
        "/api/v0alpha1/preview/document?name=a.json",
        body=payload,
        headers={
            "Host": server.authority,
            "Content-Type": "application/json",
            "Origin": server.origin,
            "Cookie": auth.split("; ", 1)[0],
            "X-ResearchOS-CSRF": auth.split(": ", 1)[1],
        },
    )
    response = connection.getresponse()
    response.read()
    assert response.status == 200
    connection.close()


def test_missing_body_is_refused_without_hanging(server: Server) -> None:
    connection, auth = _authenticate(server)
    connection.request(
        "POST",
        "/api/v0alpha1/preview/document?name=a.json",
        headers={
            "Host": server.authority,
            "Content-Type": "application/json",
            "Origin": server.origin,
            "Cookie": auth.split("; ", 1)[0],
            "X-ResearchOS-CSRF": auth.split(": ", 1)[1],
        },
    )
    response = connection.getresponse()
    assert response.status == 400
    assert json.loads(response.read().decode("utf-8"))["code"] == "document-invalid"
    connection.close()


def test_reads_work_over_a_real_socket(server: Server) -> None:
    connection, auth = _authenticate(server)
    cookie = auth.split("; ", 1)[0]
    connection.request(
        "GET",
        "/api/v0alpha1/capabilities",
        headers={"Host": server.authority, "Cookie": cookie},
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload["readOnly"] is True
    connection.close()


def test_stream_closes_over_a_real_socket(server: Server) -> None:
    connection, auth = _authenticate(server)
    cookie = auth.split("; ", 1)[0]
    connection.request(
        "GET",
        "/api/v0alpha1/stream",
        headers={"Host": server.authority, "Cookie": cookie},
    )
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("content-type", "").startswith("text/event-stream")
    payload = response.read().decode("utf-8")
    assert "event: idle" in payload
    connection.close()


def test_bounded_reader_stops_at_the_declared_length() -> None:
    """A stream that blocks after the declared bytes must still be released."""

    class _SocketLike(io.BytesIO):
        def read(self, size: int = -1) -> bytes:  # type: ignore[override]
            available = len(self.getvalue()) - self.tell()
            if available < size:
                raise TimeoutError("read past the declared body would block")
            return super().read(size)

    from llm_research_os.web.limits import RequestLimits

    payload = b'{"x":1}'
    body = read_bounded_body(
        _SocketLike(payload),
        content_length=str(len(payload)),
        limits=RequestLimits(),
    )
    assert body == payload


def test_absent_content_length_means_no_body() -> None:
    from llm_research_os.web.limits import RequestLimits

    assert (
        read_bounded_body(io.BytesIO(b"ignored"), content_length=None, limits=RequestLimits())
        == b""
    )
    assert (
        read_bounded_body(io.BytesIO(b"ignored"), content_length="  ", limits=RequestLimits())
        == b""
    )


def test_truncated_body_is_refused() -> None:
    from llm_research_os.web.errors import LocalApiError
    from llm_research_os.web.limits import RequestLimits

    with pytest.raises(LocalApiError, match="ended before Content-Length") as caught:
        read_bounded_body(io.BytesIO(b"ab"), content_length="10", limits=RequestLimits())
    assert caught.value.code == "document-invalid"
