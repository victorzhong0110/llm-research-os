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


def test_agent_inbox_scope_reply_and_apply(tmp_path):
    from llm_research_os.dashboard.agents import AgentAsk, AgentInbox, AgentReply

    ws = workspace(tmp_path)
    store = DashboardStore(ws)
    saved = store.write(request())
    inbox = AgentInbox(ws)
    ask = AgentAsk(
        projectId="demo",
        requestId="ask-1",
        expectedRevision=1,
        scope=("pinned",),
        prompt="Explain this question",
    )
    task = inbox.ask(ask)
    assert inbox.ask(ask) == task
    assert inbox.list_tasks().tasks == (task,)
    assert task.snapshot == saved
    with pytest.raises(DashboardError, match="identity reused"):
        inbox.ask(ask.model_copy(update={"prompt": "different"}))
    with pytest.raises(DashboardError, match="revision conflict"):
        inbox.ask(ask.model_copy(update={"request_id": "ask-stale", "expected_revision": 8}))
    with pytest.raises(DashboardError, match="invalid Agent scope"):
        inbox.ask(ask.model_copy(update={"request_id": "bad-scope", "scope": ("missing",)}))
    data = payload(revision=1, request_id="agent-proposal", author="agent")
    data["scope"] = ["pinned"]
    data["state"]["components"][1]["body"] = "A scoped explanation"
    proposal = DashboardWrite.model_validate_json(json.dumps(data))
    reply = AgentReply(
        requestId="ask-1", author="my-agent", message="Added context", proposal=proposal
    )
    answered = inbox.reply(reply)
    assert inbox.reply(reply) == answered
    assert store.read() == saved
    assert inbox.list_tasks().tasks[0].reply == reply
    with pytest.raises(DashboardError, match="already recorded"):
        inbox.reply(reply.model_copy(update={"message": "different"}))
    applied = store.write(proposal)
    assert applied.revision == 2
    assert applied.state.components[1].body == "A scoped explanation"
    assert not ws.control_db.exists()


def test_agent_scope_rejects_unrelated_and_stale_changes(tmp_path):
    store = DashboardStore(workspace(tmp_path))
    store.write(request())
    data = payload(revision=1, request_id="out-of-scope", author="agent")
    data["scope"] = ["pinned"]
    data["state"]["components"][0]["title"] = "Unrelated edit"
    with pytest.raises(ValueError, match="frozen scope"):
        store.write(DashboardWrite.model_validate_json(json.dumps(data)))
    data["state"]["components"][0]["title"] = "Research"
    data["state"]["appearance"] = {"skin": "paper"}
    with pytest.raises(ValueError, match="global appearance"):
        store.write(DashboardWrite.model_validate_json(json.dumps(data)))


def test_timestamped_observations_are_not_run_facts(tmp_path):
    from datetime import UTC, datetime, timedelta

    from llm_research_os.dashboard.observations import Observation, ObservationStore

    ws = workspace(tmp_path)
    store = ObservationStore(ws)
    assert not store.observations().observations
    now = datetime.now(UTC)
    value = {
        "projectId": "demo",
        "sourceId": "compute-1",
        "entityId": "host-1",
        "category": "resource",
        "title": "GPU observations",
        "reporter": "test collector",
        "provenance": "synthetic fixture only",
        "origin": "synthetic",
        "status": "unknown",
        "observedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=5)).isoformat(),
        "metrics": [
            {
                "name": "GPU utilization",
                "value": 30.5,
                "unit": "%",
                "meaning": "observed",
                "history": [
                    {"at": (now - timedelta(seconds=20)).isoformat(), "value": 20.0},
                    {"at": now.isoformat(), "value": 30.5},
                ],
            }
        ],
    }
    observation = Observation.model_validate_json(json.dumps(value))
    assert store.observe(observation) == observation
    assert store.observe(observation) == observation
    assert ObservationStore(ws).observations().observations == (observation,)
    with pytest.raises(DashboardError, match="advance source time"):
        store.observe(observation.model_copy(update={"status": "up"}))
    with pytest.raises(DashboardError, match="foreign"):
        store.observe(observation.model_copy(update={"project_id": "other"}))
    value["observedAt"] = (now + timedelta(hours=1)).isoformat()
    value["expiresAt"] = (now + timedelta(hours=2)).isoformat()
    with pytest.raises(ValidationError, match="future observation"):
        Observation.model_validate_json(json.dumps(value))
    value["observedAt"] = now.isoformat()
    value["explanation"] = "Unsupported anonymous analysis"
    with pytest.raises(ValidationError, match="attributed author"):
        Observation.model_validate_json(json.dumps(value))
    value["explanationAuthor"] = "test-agent"
    value["metrics"][0]["history"].reverse()
    with pytest.raises(ValidationError, match="strictly ordered"):
        Observation.model_validate_json(json.dumps(value))
    assert not ws.control_db.exists()
    assert not ws.receipt_db.exists()


def test_agent_and_observation_routes_share_session_boundary(tmp_path):
    from llm_research_os.dashboard.agents import AgentInbox

    ws = workspace(tmp_path)
    DashboardStore(ws).write(request())
    client = Client(
        LocalApi(
            ws,
            sessions=SessionStore(bootstrap_token=BOOTSTRAP),
            allowed_hosts=frozenset({HOST}),
            allowed_origin=ORIGIN,
        )
    )
    assert client.request("GET", "/api/v0alpha1/dashboard/observations")[0] == 401
    client.bootstrap()
    assert client.request("GET", "/api/v0alpha1/dashboard/observations")[2]["observations"] == []
    raw = json.dumps(
        {
            "kind": "DashboardAgentAsk",
            "projectId": "demo",
            "requestId": "api-ask",
            "expectedRevision": 1,
            "scope": ["pinned"],
            "prompt": "Explain this",
        }
    ).encode()
    status, _, body = client.request(
        "POST",
        "/api/v0alpha1/dashboard/agents",
        origin=ORIGIN,
        content_type="application/json",
        body=raw,
    )
    assert status == 200
    assert body["snapshot"]["revision"] == 1
    assert len(AgentInbox(ws).list_tasks().tasks) == 1
    assert client.request("GET", "/api/v0alpha1/dashboard/agents")[2]["tasks"][0]["request"][
        "scope"
    ] == ["pinned"]
    assert (
        client.request(
            "POST",
            "/api/v0alpha1/dashboard/agents",
            origin="https://foreign.invalid",
            content_type="application/json",
            body=raw,
        )[0]
        == 403
    )
    assert client.request("POST", "/api/v0alpha1/dashboard/observations", origin=ORIGIN)[0] == 405


def test_published_dashboard_examples():
    from jsonschema import Draft202012Validator

    from llm_research_os.dashboard.schema import build_schema

    validator = Draft202012Validator(build_schema())
    root = Path(__file__).parents[1] / "examples/dashboard"
    validator.validate(json.loads((root / "valid/write.json").read_text()))
    for path in (root / "valid").glob("*.json"):
        validator.validate(json.loads(path.read_text()))
    with pytest.raises(ValidationError, match="parent"):
        DashboardWrite.model_validate_json((root / "invalid/missing-parent.json").read_bytes())


def test_published_activity_examples():
    from jsonschema import Draft202012Validator

    from llm_research_os.web.contracts import ActivitySnapshot
    from llm_research_os.web.schema import build_schema

    root = Path(__file__).parents[1] / "examples/dashboard/activity"
    valid = json.loads((root / "valid.json").read_text())
    validator = Draft202012Validator(build_schema())
    validator.validate(valid)
    ActivitySnapshot.model_validate_json(json.dumps(valid))
    invalid = (root / "invalid.json").read_bytes()
    assert not validator.is_valid(json.loads(invalid))
    with pytest.raises(ValidationError, match="highWaterMark"):
        ActivitySnapshot.model_validate_json(invalid)


@pytest.mark.parametrize("command", ["apply", "observe", "reply"])
@pytest.mark.parametrize("nested", [False, True])
def test_cli_duplicate_keys_are_refused_before_storage(
    tmp_path, capsys, monkeypatch, command, nested
):
    from llm_research_os.dashboard.agents import AgentInbox
    from llm_research_os.dashboard.observations import ObservationStore

    workspace(tmp_path)
    names = {"apply": "write", "observe": "observation", "reply": "agent-reply"}
    source = Path(__file__).parents[1] / "examples/dashboard/valid" / f"{names[command]}.json"
    body = json.loads(source.read_text())
    if nested:
        if command == "reply":
            body["proposal"] = payload()
        if command == "observe":
            raw = json.dumps(body).replace('"value": 23.0', '"value": 1, "value": 23.0')
        else:
            raw = json.dumps(body).replace('"state": {', '"state": {"components": [],')
    else:
        key = "sourceId" if command == "observe" else "requestId"
        raw = json.dumps(body).replace('"' + key + '":', '"' + key + '": "other", "' + key + '":')
    target = tmp_path / "request.json"
    target.write_text(raw)

    def must_not_write(*args, **kwargs):
        pytest.fail("ambiguous input reached storage")

    monkeypatch.setattr(DashboardStore, "write", must_not_write)
    monkeypatch.setattr(ObservationStore, "observe", must_not_write)
    monkeypatch.setattr(AgentInbox, "reply", must_not_write)
    assert main(["dashboard", command, "--root", str(tmp_path), str(target)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "DashboardError"
    assert not (tmp_path / "dashboard.sqlite").exists()


@pytest.mark.parametrize("command", ["apply", "observe", "reply"])
@pytest.mark.parametrize("source_kind", ["fifo", "directory", "symlink"])
def test_cli_refuses_special_files_without_blocking(tmp_path, command, source_kind):
    import os
    import subprocess
    import sys

    workspace(tmp_path)
    source = tmp_path / "input.json"
    if source_kind == "fifo":
        try:
            os.mkfifo(source)
        except PermissionError:
            pytest.skip("container forbids FIFO creation; real FIFO exercised by Linux/macOS CI")
    elif source_kind == "directory":
        source.mkdir()
    else:
        regular = tmp_path / "regular.json"
        regular.write_text(json.dumps(payload()))
        source.symlink_to(regular)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "dashboard",
            command,
            "--root",
            str(tmp_path),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"] == "dashboard-refused"
    assert not (tmp_path / "dashboard.sqlite").exists()
