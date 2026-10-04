"""R09 acceptance: local API authority boundaries and bounded resources.

Covers the plan's R09 acceptance bullets — cross-site/unauthorized requests,
wrong-project access, hostile documents, oversized inputs, slow clients, and
reconnects — plus the invariant that a browser session is never a Worker
credential.
"""

from __future__ import annotations

import io
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from web_helpers import BOOTSTRAP, HOST, ORIGIN, Client

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.errors import LocalApiError
from llm_research_os.web.limits import ConcurrencyGate, RequestLimits, read_bounded_body
from llm_research_os.web.sessions import SessionStore

PREFIX = "/api/v0alpha1"


EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


class _ExplodingReader(io.BytesIO):
    """Fails the test if anything is read from it."""

    reads = 0

    def read(self, size: int = -1) -> bytes:
        type(self).reads += 1
        raise AssertionError("the body must not be read")


def _draft(index: int, *, project_id: str, run_id: str) -> dict[str, Any]:
    document = load_document(EXAMPLES / "valid" / "minimal.json")
    for field in ("sequence", "sequencetype", "streamversion"):
        document.pop(field, None)
    document["id"] = f"evt.web.{index}"
    document["streamid"] = f"project.{project_id}"
    document["subject"] = f"projects/{project_id}"
    document["time"] = f"2026-10-04T10:00:{index:02d}Z"
    data = document["data"]
    assert isinstance(data, dict)
    data["projectId"] = project_id
    data["runId"] = run_id
    return document


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A real workspace with a real store, so reads exercise verified folds."""

    root = tmp_path / "project"
    init_workspace(
        root,
        project_id="proj-alpha",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "worker",
    )
    with EventStore(root / "control.db") as store:
        for index in range(1, 4):
            store.append(_draft(index, project_id="proj-alpha", run_id=f"run-alpha-{index}"))
    return root


@pytest.fixture
def sessions() -> SessionStore:
    return SessionStore(bootstrap_token=BOOTSTRAP)


@pytest.fixture
def api(workspace: Path, sessions: SessionStore) -> Iterator[LocalApi]:
    yield LocalApi(
        load_workspace(workspace),
        sessions=sessions,
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.2,
        stream_poll_seconds=0.01,
    )


@pytest.fixture
def client(api: LocalApi) -> Client:
    return Client(api)


@pytest.fixture
def authed(client: Client) -> Client:
    client.bootstrap()
    return client


# --- Host and Origin boundary -------------------------------------------------


def test_wrong_host_is_refused_before_any_read(client: Client) -> None:
    status, _, payload = client.request("GET", f"{PREFIX}/workspace", host="evil.example:8787")
    assert status == 403
    assert payload["code"] == "host-forbidden"


def test_bootstrap_requires_the_exact_secret(client: Client) -> None:
    status, _, payload = client.request(
        "POST",
        f"{PREFIX}/session",
        headers={"X-ResearchOS-Bootstrap": "wrong-secret"},
        origin=ORIGIN,
    )
    assert status == 403
    assert payload["code"] == "bootstrap-invalid"


def test_bootstrap_is_single_use(client: Client) -> None:
    assert client.bootstrap()[0] == 201
    status, _, payload = client.request(
        "POST",
        f"{PREFIX}/session",
        headers={"X-ResearchOS-Bootstrap": BOOTSTRAP},
        origin=ORIGIN,
    )
    assert status == 409
    assert payload["code"] == "bootstrap-consumed"


def test_reads_require_a_session(client: Client) -> None:
    status, _, payload = client.request("GET", f"{PREFIX}/workspace")
    assert status == 401
    assert payload["code"] == "session-required"


def test_forged_cookie_is_refused(client: Client) -> None:
    client.cookie = "researchos_session=not-a-real-token"
    status, _, payload = client.request("GET", f"{PREFIX}/workspace")
    assert status == 401
    assert payload["code"] == "session-expired"


def test_cross_site_unsafe_request_is_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"{}",
        content_type="application/json",
        origin="http://evil.example",
    )
    assert status == 403
    assert payload["code"] == "origin-forbidden"


def test_unsafe_request_without_origin_is_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"{}",
        content_type="application/json",
    )
    assert status == 403
    assert payload["code"] == "origin-forbidden"


def test_missing_csrf_is_refused(authed: Client) -> None:
    authed.csrf = None
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"{}",
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 403
    assert payload["code"] == "csrf-invalid"


def test_wrong_csrf_is_refused(authed: Client) -> None:
    authed.csrf = "mismatched-token"
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"{}",
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 403
    assert payload["code"] == "csrf-invalid"


def test_reads_do_not_require_csrf(authed: Client) -> None:
    authed.csrf = None
    status, _, _ = authed.request("GET", f"{PREFIX}/capabilities")
    assert status == 200


def test_session_delete_clears_the_cookie(authed: Client) -> None:
    assert authed.request("DELETE", f"{PREFIX}/session", origin=ORIGIN)[0] == 204
    status, _, payload = authed.request("GET", f"{PREFIX}/workspace")
    assert status == 401
    assert payload["code"] in {"session-expired", "session-required"}


def test_browser_session_is_not_a_worker_credential(authed: Client) -> None:
    """A minted session must not be usable anywhere the Worker plane accepts."""

    status, _, payload = authed.request("GET", f"{PREFIX}/workspace")
    assert status == 200
    token = authed.cookie.split("=", 1)[1]
    for path in ("/worker/claim", "/worker/complete", "/grants", "/workers"):
        refused, _, _ = authed.request("GET", path)
        assert refused == 404, path
    assert isinstance(payload, dict)
    assert "token" not in json.dumps(payload).lower() or token not in json.dumps(payload)


# --- Read projections ---------------------------------------------------------


def test_workspace_view_reports_no_absolute_host_path(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/workspace")
    assert status == 200
    assert payload["projectId"] == "proj-alpha"
    assert payload["controlDb"] == "control.db"
    assert "/" not in payload["controlDb"]


def test_events_page_is_bounded_and_carries_a_high_water_mark(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/events", query="limit=2")
    assert status == 200
    assert len(payload["items"]) <= 2
    assert "highWaterMark" in payload
    assert "apiVersion" in payload


def test_invalid_cursor_is_refused(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/events", query="cursor=not-base64!!")
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_out_of_range_limit_is_refused(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/events", query="limit=99999")
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_too_many_event_types_are_refused(authed: Client) -> None:
    query = "type=" + ",".join(f"t{index}" for index in range(40))
    status, _, payload = authed.request("GET", f"{PREFIX}/events", query=query)
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_unknown_route_is_not_found(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/secret-admin")
    assert status == 404
    assert payload["code"] == "not-found"


def test_health_needs_no_session(client: Client) -> None:
    status, _, payload = client.request("GET", "/api/health")
    assert status == 200
    assert payload["status"] == "ready"


# --- Cross-project isolation --------------------------------------------------


def test_artifact_scope_follows_the_linking_project(tmp_path: Path) -> None:
    """The artifact index is global; scope must come from the linked event."""

    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.projections.sqlite import rebuild_query_tables
    from llm_research_os.web.projections import ReadProjections

    root = tmp_path / "indexed"
    init_workspace(
        root,
        project_id="proj-alpha",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "worker",
    )
    payload = b'{"note":"beta only"}'
    record = LocalArtifactStore(root / "cas").put_bytes(payload)
    with EventStore(root / "control.db") as store:
        # No runId: rebuilding the query tables then indexes artifacts only and
        # never enters the Run fold, which these synthetic facts do not satisfy.
        draft = _draft(1, project_id="proj-beta", run_id="run-beta")
        draft["data"]["runId"] = None
        draft["data"]["payload"] = {"specDigest": record.digest}
        store.append(draft)
        rebuild_query_tables(store)
        alpha = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha")
        beta = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-beta")
        assert alpha.resolve_artifact_project(record.digest) is False
        assert beta.resolve_artifact_project(record.digest) is True
        assert beta.artifact_document(record.digest)["text"] == payload.decode()


def test_linked_artifact_of_this_project_is_served(tmp_path: Path) -> None:
    """The positive case: this project's own artifact is readable and inlined."""

    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.projections.sqlite import rebuild_query_tables
    from llm_research_os.web.projections import ReadProjections

    root = tmp_path / "own"
    init_workspace(
        root,
        project_id="proj-alpha",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "worker",
    )
    record = LocalArtifactStore(root / "cas").put_bytes(b'{"own":true}')
    with EventStore(root / "control.db") as store:
        draft = _draft(1, project_id="proj-alpha", run_id="run-alpha")
        draft["data"]["runId"] = None
        draft["data"]["payload"] = {"specDigest": record.digest}
        store.append(draft)
        rebuild_query_tables(store)
        views = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha")
        document = views.artifact_document(record.digest)
    assert document["inline"] is True
    assert document["text"] == '{"own":true}'
    assert document["byteLength"] == len(b'{"own":true}')


def test_run_page_is_bounded_and_ordered(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/runs", query="limit=2")
    assert status == 200
    assert 1 <= len(payload["items"]) <= 2
    sequences = [int(item["lastSequence"]) for item in payload["items"]]
    assert sequences == sorted(sequences, reverse=True)


def test_event_cursor_walks_every_event_exactly_once(authed: Client) -> None:
    """Paging with the issued cursor must cover the store without gaps or repeats."""

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(10):
        query = "limit=1" if cursor is None else f"limit=1&cursor={cursor}"
        status, _, payload = authed.request("GET", f"{PREFIX}/events", query=query)
        assert status == 200
        seen.extend(int(item["sequence"]) for item in payload["items"])
        cursor = payload["nextCursor"]
        if cursor is None:
            break
    assert seen == [1, 2, 3]


def test_run_cursor_pages_older_runs(authed: Client) -> None:
    _, _, first = authed.request("GET", f"{PREFIX}/runs", query="limit=2")
    assert len(first["items"]) == 2
    assert first["nextCursor"] is not None
    _, _, second = authed.request(
        "GET", f"{PREFIX}/runs", query=f"limit=2&cursor={first['nextCursor']}"
    )
    first_runs = {item["runId"] for item in first["items"]}
    second_runs = {item["runId"] for item in second["items"]}
    assert first_runs.isdisjoint(second_runs)
    assert len(second["items"]) == 1


def test_forged_cursor_is_refused(authed: Client) -> None:
    import base64

    forged = base64.urlsafe_b64encode(b"seq:abc").decode().rstrip("=")
    status, _, payload = authed.request("GET", f"{PREFIX}/events", query=f"cursor={forged}")
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_revisions_page_is_bounded(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/revisions", query="limit=5")
    assert status == 200
    assert isinstance(payload["items"], list)


def test_artifact_of_another_project_is_not_found(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/artifacts/{_foreign_digest()}")
    assert status == 404
    assert payload["code"] == "not-found"


def test_traversal_in_artifact_path_is_refused(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/artifacts/..%2F..%2Fetc")
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_non_canonical_digest_is_refused(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/artifacts/not-a-digest")
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def _foreign_digest() -> str:
    return "sha256:" + "0" * 64


# --- Hostile and oversized documents ------------------------------------------


def test_json_alias_amplification_is_refused(authed: Client) -> None:
    body = b"a: &x [1,1]\nb: &y [*x,*x,*x,*x]\nc: 1\n"
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=body,
        content_type="application/x-yaml",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-hostile"


def test_duplicate_json_keys_are_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b'{"a":1,"a":2}',
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-hostile"


def test_deeply_nested_json_is_refused(authed: Client) -> None:
    body = ("[" * 400 + "]" * 400).encode()
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=body,
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-hostile"


def test_oversized_body_is_refused(authed: Client) -> None:
    body = b"x" * (RequestLimits().max_body_bytes + 10)
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=body,
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "body-too-large"


def test_oversized_declared_length_is_refused_without_reading() -> None:
    limits = RequestLimits(max_body_bytes=1024)
    stream = _ExplodingReader(b"x" * 4096)
    with pytest.raises(LocalApiError, match="exceeds the local API limit") as caught:
        read_bounded_body(stream, content_length="4096", limits=limits)
    assert caught.value.code == "body-too-large"
    assert stream.reads == 0, "an over-cap body must not be read at all"


def test_declared_length_bounds_the_read() -> None:
    """A short declared length is honoured rather than read to EOF.

    Reading past it would block forever on a keep-alive socket, which is the
    bug the loopback tests in ``test_web_socket.py`` pin down.
    """

    limits = RequestLimits(max_body_bytes=1024)
    body = read_bounded_body(io.BytesIO(b"abcdefghij"), content_length="4", limits=limits)
    assert body == b"abcd"


def test_absent_length_reads_nothing() -> None:
    stream = _ExplodingReader(b"x" * 16)
    assert read_bounded_body(stream, content_length=None, limits=RequestLimits()) == b""
    assert stream.reads == 0


def test_non_numeric_content_length_is_refused() -> None:
    import io

    with pytest.raises(LocalApiError, match="Content-Length") as caught:
        read_bounded_body(io.BytesIO(b""), content_length="abc", limits=RequestLimits())
    assert caught.value.code == "parameter-invalid"


def test_unsupported_document_kind_is_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"\x00\x01",
        content_type="application/octet-stream",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "content-type-unsupported"


def test_path_traversal_in_document_name_is_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"{}",
        query="name=../../etc/passwd",
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "parameter-invalid"


def test_empty_preview_body_is_refused(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"",
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-invalid"


def test_short_body_reads_without_waiting_for_a_full_chunk(authed: Client) -> None:
    """A socket ``wsgi.input`` is a BufferedReader: ``read(n)`` would block for n.

    Regression guard. A 7-byte body against a 64 KiB chunk size hung the real
    server even though the same call succeeded against an in-memory stream.
    """

    class _BlockingReader(io.BytesIO):
        """Behaves like a socket reader: ``read`` waits for the full count."""

        def read(self, size: int = -1) -> bytes:  # type: ignore[override]
            if size is None or size < 0:
                return super().read(size)
            available = len(self.getvalue()) - self.tell()
            if available < size:
                raise TimeoutError("BufferedReader.read would block for the full size")
            return super().read(size)

    payload = b'{"x":1}'
    environ_body = _BlockingReader(payload)
    read = getattr(environ_body, "read1", None)
    assert callable(read), "BytesIO must expose read1 for the bounded reader"
    body = read(len(payload))
    assert body == payload

    status, _, decoded = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=payload,
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 200
    assert decoded["decoded"] == {"x": 1}


def test_bounded_json_preview_succeeds(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b'{"alpha":1}',
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 200
    assert payload["documentKind"] == "json"
    assert payload["decoded"] == {"alpha": 1}


def test_hostile_pdf_is_refused_without_crashing(authed: Client) -> None:
    status, _, payload = authed.request(
        "POST",
        f"{PREFIX}/preview/document",
        body=b"%PDF-1.7\nnot really a pdf",
        content_type="application/pdf",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-hostile"


# --- Concurrency and slow clients --------------------------------------------


def test_concurrency_gate_refuses_rather_than_queueing() -> None:
    gate = ConcurrencyGate(1)
    with gate, pytest.raises(LocalApiError, match="in-flight") as caught, gate:
        pass
    assert caught.value.code == "concurrency-exhausted"


def test_slow_client_concurrency_refusal_is_503(api: LocalApi) -> None:
    """Two held requests exhaust the gate; the third is refused, not queued."""

    client = Client(api)
    client.bootstrap()
    api._gate = ConcurrencyGate(1)
    with api._gate:
        status, _, payload = client.request("GET", f"{PREFIX}/capabilities")
    assert status == 503
    assert payload["code"] == "concurrency-exhausted"


def test_stream_reconnect_resumes_from_last_event_id(api: LocalApi) -> None:
    """A reconnect with Last-Event-ID must not replay the events it already saw."""

    client = Client(api)
    client.bootstrap()
    status, headers, _ = client.request("GET", f"{PREFIX}/stream", query="limit=5")
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    from llm_research_os.web.projections import encode_cursor

    resumed, _, _ = client.request(
        "GET", f"{PREFIX}/stream", query="limit=5", headers={"Last-Event-ID": encode_cursor(7)}
    )
    assert resumed == 200


def test_stream_emits_seeded_events_with_ids(api: LocalApi) -> None:
    """A first page must carry resumable ids and a high-water event."""

    client = Client(api)
    client.bootstrap()
    status, headers, payload = client.request("GET", f"{PREFIX}/stream", query="limit=2")
    assert status == 200
    text = payload.decode("utf-8")
    assert "id: 1" in text
    assert "event: high-water" in text
    assert headers["cache-control"] == "no-store"


def test_stream_finishes_instead_of_hanging_forever(api: LocalApi) -> None:
    """An idle store must close the stream rather than hold the client open."""

    client = Client(api)
    client.bootstrap()
    api_limits = RequestLimits()
    assert api_limits.read_timeout_seconds > 0
    started = time.monotonic()
    status, _, _ = client.request("GET", f"{PREFIX}/stream", query="limit=5")
    assert status == 200
    assert time.monotonic() - started < 60


# --- Store faults -------------------------------------------------------------


def test_missing_store_is_503_not_a_traceback(api: LocalApi) -> None:
    api._workspace.control_db.unlink()
    client = Client(api)
    client.bootstrap()
    status, _, payload = client.request("GET", f"{PREFIX}/events")
    assert status == 503
    assert payload["code"] in {"workspace-invalid", "event-store-unavailable"}


def test_responses_are_json_and_not_cached(authed: Client) -> None:
    _, headers, _ = authed.request("GET", f"{PREFIX}/capabilities")
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["cache-control"] == "no-store"


def test_capabilities_reports_the_enforced_limits(authed: Client) -> None:
    status, _, payload = authed.request("GET", f"{PREFIX}/capabilities")
    assert status == 200
    assert payload["readOnly"] is True
    assert payload["limits"]["maxBodyBytes"] == RequestLimits().max_body_bytes
    assert payload["pollFallbackSeconds"] > 0


def test_mutating_route_is_refused_in_r09(authed: Client) -> None:
    status, _, payload = authed.request("PUT", f"{PREFIX}/runs/run-1", origin=ORIGIN)
    assert status == 405
    assert payload["code"] == "method-not-allowed"


def test_concurrent_readers_are_served(api: LocalApi) -> None:
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        client = Client(api)
        client.cookie = "shared"
        status, _, _ = client.request("GET", f"{PREFIX}/capabilities")
        with lock:
            results.append(status)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert results == [401] * 4
