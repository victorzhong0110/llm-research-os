"""Map composition is revision-bound and cannot create execution facts."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError
from web_helpers import BOOTSTRAP, HOST, ORIGIN, Client

from llm_research_os.application.workspace import init_workspace
from llm_research_os.cli import main
from llm_research_os.dashboard.models import DashboardWrite
from llm_research_os.dashboard.store import DashboardError, DashboardStore, read_write_request
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore


def workspace(tmp_path):
    return init_workspace(
        tmp_path,
        project_id="demo",
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )


def payload(revision=0, request_id="request-1", author="human"):
    return {
        "projectId": "demo",
        "requestId": request_id,
        "expectedRevision": revision,
        "author": "operator",
        "authorKind": author,
        "state": {
            "components": [
                {
                    "id": "group",
                    "type": "group",
                    "title": "Research",
                    "position": {"x": 0, "y": 0, "width": 800, "height": 600},
                },
                {
                    "id": "pinned",
                    "type": "note",
                    "title": "Question",
                    "parentId": "group",
                    "pinned": True,
                    "position": {"x": 20, "y": 60},
                },
            ]
        },
    }


def request(**kwargs):
    return DashboardWrite.model_validate_json(json.dumps(payload(**kwargs)))


def test_read_does_not_create_stores(tmp_path):
    ws = workspace(tmp_path)
    assert DashboardStore(ws).read().revision == 0
    assert not (tmp_path / "dashboard.sqlite").exists()
    assert not ws.control_db.exists()
    assert not ws.receipt_db.exists()


def test_revision_replay_conflict_restart_and_restore(tmp_path):
    ws = workspace(tmp_path)
    store = DashboardStore(ws)
    saved = store.write(request())
    assert saved.revision == 1
    assert DashboardStore(ws).read() == saved
    assert store.write(request()) == saved
    with pytest.raises(DashboardError, match="revision conflict"):
        store.write(request(request_id="different"))
    changed = payload()
    changed["author"] = "other"
    with pytest.raises(DashboardError, match="identity reused"):
        store.write(DashboardWrite.model_validate_json(json.dumps(changed)))
    assert store.read(0).state.components == ()
    with pytest.raises(DashboardError, match="unavailable"):
        store.read(99)
    for i in range(1, 32):
        store.write(request(revision=i, request_id=f"next-{i}"))
    with pytest.raises(DashboardError, match="unavailable"):
        store.read(1)
    restored = store.write(
        DashboardWrite(
            projectId="demo",
            requestId="restore",
            expectedRevision=32,
            author="operator",
            authorKind="human",
            state=saved.state,
        )
    )
    assert restored.revision == 33
    assert not ws.control_db.exists()
    assert not ws.receipt_db.exists()


def test_two_clients_exactly_one_wins(tmp_path):
    store = DashboardStore(workspace(tmp_path))

    def write(i):
        try:
            return store.write(request(request_id=f"client-{i}")).revision
        except DashboardError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(write, (1, 2)))
    assert sorted(str(item) for item in result) == ["1", "conflict"]


@pytest.mark.parametrize("change", ["move", "remove", "unpin", "rebind", "ancestor"])
def test_agent_cannot_displace_pin(tmp_path, change):
    store = DashboardStore(workspace(tmp_path))
    store.write(request())
    data = payload(revision=1, request_id="agent-1", author="agent")
    nodes = data["state"]["components"]
    if change == "move":
        nodes[1]["position"]["x"] = 100
    elif change == "remove":
        nodes.pop()
    elif change == "unpin":
        nodes[1]["pinned"] = False
    elif change == "rebind":
        nodes[1]["binding"] = {"source": "runs"}
    else:
        nodes[0]["position"]["x"] = 100
    with pytest.raises(ValueError, match="pin"):
        store.write(DashboardWrite.model_validate_json(json.dumps(data)))
    assert store.read().revision == 1
    data["authorKind"] = "human"
    assert store.write(DashboardWrite.model_validate_json(json.dumps(data))).revision == 2


@pytest.mark.parametrize(
    "change", ["cycle", "dangling", "duplicate", "bounds", "nan", "url", "css", "code"]
)
def test_invalid_maps_refused(change):
    data = payload()
    nodes = data["state"]["components"]
    if change == "cycle":
        nodes[0]["parentId"] = "group"
    elif change == "dangling":
        nodes[1]["parentId"] = "missing"
    elif change == "duplicate":
        nodes[1]["id"] = "group"
    elif change == "bounds":
        nodes[1]["position"]["width"] = 2000
    elif change == "nan":
        nodes[1]["position"]["x"] = float("nan")
    elif change == "url":
        nodes[1]["binding"] = {"source": "telemetry", "url": "http://localhost/private"}
    elif change == "css":
        data["state"]["appearance"] = {"background": "url(https://example.com)"}
    else:
        nodes[1]["type"] = "script"
    with pytest.raises(ValidationError):
        DashboardWrite.model_validate_json(json.dumps(data))


def test_cli_and_unsafe_storage(tmp_path, capsys):
    ws = workspace(tmp_path)
    assert main(["dashboard", "show", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 0
    source = tmp_path / "write.json"
    source.write_text(json.dumps(payload()))
    assert main(["dashboard", "apply", "--root", str(tmp_path), str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 1
    source.write_text('{"a":1,"a":2}')
    with pytest.raises(DashboardError, match="duplicate"):
        read_write_request(source)
    source.write_bytes(b" " * 1048577)
    with pytest.raises(DashboardError, match="limit"):
        read_write_request(source)
    (tmp_path / "dashboard.sqlite").unlink()
    (tmp_path / "dashboard.sqlite").symlink_to(source)
    with pytest.raises(DashboardError, match="unsafe"):
        DashboardStore(ws)


def test_api_auth_revision_and_fresh_workspace(tmp_path):
    ws = workspace(tmp_path)
    app = LocalApi(
        ws,
        sessions=SessionStore(bootstrap_token=BOOTSTRAP),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
    )
    client = Client(app)
    assert client.request("GET", "/api/v0alpha1/dashboard")[0] == 401
    assert client.bootstrap()[0] == 201
    assert client.request("GET", "/api/v0alpha1/workspace")[2]["highWaterMark"] == 0
    assert client.request("GET", "/api/v0alpha1/dashboard")[2]["revision"] == 0
    raw = json.dumps(payload()).encode()

    def post():
        return client.request(
            "POST",
            "/api/v0alpha1/dashboard",
            body=raw,
            content_type="application/json",
            origin=ORIGIN,
        )

    csrf = client.csrf
    client.csrf = None
    assert post()[0] == 403
    client.csrf = csrf
    assert post()[2]["revision"] == 1
    assert post()[2]["revision"] == 1
    assert client.request("GET", "/api/v0alpha1/dashboard", query="revision=0")[2]["revision"] == 0
    assert client.request("GET", "/api/v0alpha1/dashboard", query="revision=oops")[0] == 400
    assert client.request("DELETE", "/api/v0alpha1/dashboard", origin=ORIGIN)[0] == 405
    assert not ws.control_db.exists()
