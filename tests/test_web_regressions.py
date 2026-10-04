"""Real store/socket regressions from the R09 review."""

from __future__ import annotations

import http.client
import io
import json
import sqlite3
from pathlib import Path

import pytest
from test_web_api import _draft
from test_web_socket import BOOTSTRAP, Server
from web_helpers import HOST, ORIGIN, Client

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.errors import LocalApiError
from llm_research_os.web.limits import RequestLimits
from llm_research_os.web.projections import ReadProjections
from llm_research_os.web.sessions import SessionStore


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    init_workspace(
        root,
        project_id="proj-alpha",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "worker",
    )
    with EventStore(root / "control.db"):
        pass
    return root


def _append(
    store: EventStore, index: int, *, project: str = "proj-alpha", event_type: str | None = None
) -> None:
    draft = _draft(1, project_id=project, run_id="run-alpha")
    if event_type is not None:
        draft["type"] = event_type
        draft["data"]["payload"] = {"kind": event_type}
    draft["id"] = f"evt.regression.{index}"
    store.append(draft)


def test_run_page_above_storage_page_limit(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        for index in range(1001):
            _append(store, index)
        page = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha").run_page(
            cursor=None,
            limit=10,
        )
        assert page.items[0]["lastSequence"] == 1001
        assert page.high_water_mark == 1001


def test_filtered_page_finds_later_match_and_freezes_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        for index in range(1, 4):
            _append(store, index, event_type="run.completed" if index == 3 else "run.started")
        views = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha")
        filtered = views.event_page(cursor=None, limit=2, event_types=frozenset({"run.completed"}))
        assert [r["sequence"] for r in filtered.items] == [3]
        first = views.event_page(cursor=None, limit=2)
        _append(store, 4)
        second = views.event_page(cursor=first.next_cursor, limit=2)
        assert [r["sequence"] for r in second.items] == [3]
        assert second.high_water_mark == 3
        other = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-other")
        with pytest.raises(LocalApiError, match="cursor scope"):
            other.event_page(cursor=first.next_cursor, limit=2)


def test_foreign_project_prefix_does_not_starve_sse(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        for index in range(1, 102):
            _append(store, index, project="proj-alpha" if index == 101 else "proj-foreign")
    sessions = SessionStore(bootstrap_token="test-bootstrap-secret-value")
    api = LocalApi(
        load_workspace(root),
        sessions=sessions,
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.03,
        stream_poll_seconds=0.005,
    )
    client = Client(api)
    client.bootstrap()
    status, _, body = client.request("GET", "/api/v0alpha1/stream")
    assert status == 200
    assert b"id: 101" in body
    assert b"proj-foreign" not in body
    assert api._gate.active == 0


def test_sse_retains_gate_and_close_before_iteration_releases(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sessions = SessionStore(bootstrap_token="test-secret")
    session = sessions.exchange_bootstrap("test-secret")
    api = LocalApi(
        load_workspace(root),
        sessions=sessions,
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        limits=RequestLimits(max_concurrent_requests=1),
    )
    stream = api.wsgi(
        {
            "HTTP_HOST": HOST,
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/v0alpha1/stream",
            "HTTP_COOKIE": f"researchos_session={session.token}",
        },
        lambda *_: None,
    )
    assert api._gate.active == 1
    status, _, _ = Client(api).request("GET", "/api/health")
    assert status == 503
    stream.close()  # type: ignore[attr-defined]
    assert api._gate.active == 0
    assert Client(api).request("GET", "/api/health")[0] == 200


def test_production_server_answers_while_stream_open(tmp_path: Path) -> None:
    root = _root(tmp_path)
    server = Server(root)
    server.api._stream_idle_seconds = 0.6
    try:
        connection = server.client()
        connection.request(
            "POST",
            "/api/v0alpha1/session",
            headers={
                "Host": server.authority,
                "Origin": server.origin,
                "X-ResearchOS-Bootstrap": BOOTSTRAP,
            },
        )
        response = connection.getresponse()
        json.loads(response.read())
        cookie = str(response.getheader("set-cookie")).split(";", 1)[0]
        connection.close()
        stream = server.client()
        stream.request(
            "GET", "/api/v0alpha1/stream", headers={"Host": server.authority, "Cookie": cookie}
        )
        response = stream.getresponse()
        other = http.client.HTTPConnection("127.0.0.1", server.port, timeout=0.3)
        other.request("GET", "/api/health", headers={"Host": server.authority})
        assert other.getresponse().status == 200
        other.close()
        response.read()
        stream.close()
    finally:
        server.close()


def test_web_read_store_cannot_write_or_update_caches(tmp_path: Path) -> None:
    root = _root(tmp_path)
    api = LocalApi(
        load_workspace(root),
        sessions=SessionStore(),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
    )
    with api._open_store() as store:
        assert store._writable is False
        assert store.last_sequence() == 0


def test_pdf_preview_uses_real_isolated_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from llm_research_os.web.limits import extract_bounded_pdf

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 20 Td (bounded worker) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    monkeypatch.setattr(
        "pypdf.PdfReader", lambda *_a, **_k: pytest.fail("parsed PDF in API process")
    )
    result = extract_bounded_pdf(output.getvalue(), limits=RequestLimits())
    assert result["text"] == "bounded worker"


def test_sql_query_deadline_interrupts_work(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with (
        EventStore(root / "control.db", create=False) as store,
        pytest.raises(sqlite3.OperationalError, match="interrupted"),
        store.query_budget(0.001),
    ):
        store._connection.execute(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000) "
            "SELECT sum(x) FROM n"
        ).fetchone()


def test_trickling_headers_expire_and_release_handler(tmp_path: Path) -> None:
    import socket
    import threading
    import time
    from wsgiref.simple_server import make_server

    from llm_research_os.web.serve import BoundedWSGIServer, _QuietHandler

    class FastDeadline(_QuietHandler):
        request_deadline_seconds = 0.05

    root = _root(tmp_path)
    api = LocalApi(
        load_workspace(root),
        sessions=SessionStore(),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
    )
    server = make_server(
        "127.0.0.1", 0, api.wsgi, server_class=BoundedWSGIServer, handler_class=FastDeadline
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=1) as connection:
            connection.sendall(b"GET /api/health HTTP/1.1\r\nHost:")
            time.sleep(0.08)
            assert connection.recv(1) == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
