"""Review regressions for immutable, scoped workbench inspection."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from jsonschema import Draft202012Validator
from test_run_control import _draft, _queued_draft, _started_draft
from test_web_regressions import _append, _root
from web_helpers import BOOTSTRAP, HOST, ORIGIN, Client

from llm_research_os.application.workspace import load_workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.runs.control import RunControl
from llm_research_os.spec.io import load_spec
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.inspection import graph_document, references, safe_document
from llm_research_os.web.projections import ReadProjections
from llm_research_os.web.schema import build_schema, schema_matches
from llm_research_os.web.sessions import SessionStore

ROOT = Path(__file__).parents[1]
PREFIX = "/api/v0alpha1"


def _client(root: Path) -> Client:
    client = Client(
        LocalApi(
            load_workspace(root),
            sessions=SessionStore(bootstrap_token=BOOTSTRAP),
            allowed_hosts=frozenset({HOST}),
            allowed_origin=ORIGIN,
        )
    )
    assert client.bootstrap()[0] == 201
    return client


def test_detail_page_filters_run_before_limit_and_preserves_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        for i in range(1, 252):
            _append(store, i)
        store.append(_queued_draft(project="proj-alpha", run="run-late"))
    client = _client(root)
    status, _, result = client.request("GET", PREFIX + "/events", query="runId=run-late&limit=1")
    assert status == 200
    assert [r["runId"] for r in result["items"]] == ["run-late"]
    assert result["highWaterMark"] == 252
    with EventStore(root / "control.db") as store:
        store.append(_started_draft(project="proj-alpha", run="run-late"))
    _, _, next_page = client.request(
        "GET",
        PREFIX + "/events",
        query=urlencode({"runId": "run-late", "limit": 1, "cursor": result["nextCursor"]}),
    )
    assert next_page["items"] == []
    assert next_page["highWaterMark"] == 252
    assert (
        client.request(
            "GET",
            PREFIX + "/events",
            query=urlencode({"runId": "run-alpha", "cursor": result["nextCursor"]}),
        )[0]
        == 400
    )


def test_real_control_cancellation_request_is_not_running_or_observed_stop(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        control = RunControl(store, project_id="proj-alpha", run_id="run-late")
        control.append(_queued_draft(project="proj-alpha", run="run-late"))
        control.append(_started_draft(project="proj-alpha", run="run-late"))
        control.append(
            _draft(
                "run.cancel.requested",
                {"reasonCode": "review-cancel"},
                event_id="evt.cancel",
                project="proj-alpha",
                run="run-late",
            )
        )
        assert control.rebuild().snapshot.cancellation_requested
        view = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha")
        assert view.run_page(cursor=None).items[0]["observation"] == "cancel-requested"


def test_event_inspection_and_artifact_links_resolve_without_cross_project_access(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    artifacts = LocalArtifactStore(root / "cas")
    payload = {"metric": {"loss": 0.25}, "token": "do-not-return", "path": "/private/host/code"}
    obj = artifacts.put_bytes(json.dumps(payload).encode())
    with EventStore(root / "control.db") as store:
        first = _draft(
            "decision.recorded",
            {"resultDigest": obj.digest},
            event_id="decision.real",
            project="proj-alpha",
            run="run-late",
        )
        store.append(first)
        store.append(
            _draft(
                "run.reviewed",
                {
                    "decisionEventId": "decision.real",
                    "authorizationSequence": "1",
                    "token": "event-secret",
                    "codePath": "/private/code",
                },
                event_id="review.real",
                project="proj-alpha",
                run="run-late",
            )
        )
        store.append(
            _draft(
                "decision.recorded",
                {},
                event_id="foreign.private",
                project="proj-foreign",
                run="run-other",
            )
        )
    client = _client(root)
    status, _, record = client.request("GET", PREFIX + "/inspect/events/review.real")
    assert status == 200
    Draft202012Validator(build_schema()).validate(record)
    assert {link["target"] for link in record["links"]} == {"decision.real", "1"}
    body = json.dumps(record)
    assert "event-secret" not in body and "/private/code" not in body
    assert client.request("GET", PREFIX + "/inspect/events/foreign.private")[0] == 404
    status, _, record = client.request("GET", PREFIX + "/inspect/events/decision.real")
    assert status == 200 and record["links"][0]["target"] == obj.digest
    status, _, inspected = client.request("GET", PREFIX + "/inspect/artifacts/" + obj.digest)
    assert status == 200
    assert inspected["document"]["content"]["metric"]["loss"] == 0.25
    assert "do-not-return" not in json.dumps(inspected)
    assert "/private/host/code" not in json.dumps(inspected)
    Draft202012Validator(build_schema()).validate(inspected)


def test_stored_spec_has_actual_dependency_topology_and_immutable_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    spec = load_spec(ROOT / "examples/valid/minimal.yaml")
    document = spec.model_dump(mode="json", by_alias=True)
    graph = document["workflows"][0]["graph"]
    node = dict(graph["nodes"][0])
    node["id"] = "second"
    graph["nodes"].append(node)
    graph["edges"] = [{"source": graph["nodes"][0]["id"], "target": "second"}]
    text = json.dumps(document)
    obj = LocalArtifactStore(root / "cas").put_bytes(text.encode())
    with EventStore(root / "control.db") as store:
        store.append(
            _draft(
                "plan.authorization.evaluated",
                {"specDigest": obj.digest},
                event_id="evt.spec.ref",
                project="proj-alpha",
                run="run-late",
            )
        )
    client = _client(root)
    status, _, inspected = client.request("GET", PREFIX + "/inspect/artifacts/" + obj.digest)
    assert status == 200
    topology = inspected["document"]["graph"]
    assert topology["source"] == "ResearchSpec"
    assert topology["graphs"][0]["edges"] == graph["edges"]
    assert topology["graphs"][0]["unsupported"] is False
    assert LocalArtifactStore(root / "cas").verify(obj.digest).digest == obj.digest
    assert client.request("GET", PREFIX + "/inspect/revisions/" + obj.digest)[0] == 200


def test_nested_graph_is_explicitly_unsupported() -> None:
    spec = load_spec(ROOT / "examples/valid/bounded-loop.yaml")
    topology = graph_document(spec.model_dump_json(by_alias=True))
    assert topology["source"] == "ResearchSpec"
    assert any(graph["unsupported"] for graph in topology["graphs"])
    assert graph_document('{"graph":{"nodes":[]}}')["source"] == "unsupported"


def test_reference_bound_and_redaction_preserve_metric_values() -> None:
    assert len(references({"resultDigests": ["sha256:" + f"{i:064x}" for i in range(150)]})) == 100
    assert safe_document({"loss": 0.0, "nested": [{"api_key": "hidden"}]}) == {
        "loss": 0.0,
        "nested": [{"api_key": "[redacted]"}],
    }


@pytest.mark.parametrize("identity", ["0", "9007199254740992", "x" * 256])
def test_event_identity_bounds_are_structured(tmp_path: Path, identity: str) -> None:
    client = _client(_root(tmp_path))
    status, _, body = client.request("GET", PREFIX + "/inspect/events/" + identity)
    assert status == 400 and body["code"] == "parameter-invalid"


def test_published_response_schema_is_current_and_closed() -> None:
    assert schema_matches(ROOT / "schemas/local-api-response/v0alpha1.schema.json")
    validator = Draft202012Validator(build_schema())
    validator.check_schema(build_schema())
    assert not validator.is_valid(
        {
            "apiVersion": "researchos.dev/local-api/v0alpha1",
            "kind": "InspectionView",
            "identity": "evt.1",
            "document": {},
            "links": [],
            "immutable": False,
        }
    )


def test_lineage_proof_opens_nested_config_but_refuses_unrelated_object(tmp_path: Path) -> None:
    root = _root(tmp_path)
    artifacts = LocalArtifactStore(root / "cas")
    config = artifacts.put_bytes(b'{"seed":0}')
    private = artifacts.put_bytes(b'{"private":true}')
    result = artifacts.put_bytes(json.dumps({"configDigest": config.digest}).encode())
    with EventStore(root / "control.db") as store:
        store.append(
            _draft(
                "custom.fixture",
                {"resultDigest": result.digest},
                event_id="evt.root",
                project="proj-alpha",
                run="run-late",
            )
        )
    client = _client(root)
    assert client.request("GET", PREFIX + "/inspect/artifacts/" + config.digest)[0] == 404
    query = urlencode({"via": json.dumps([result.digest])})
    status, _, value = client.request(
        "GET", PREFIX + "/inspect/artifacts/" + config.digest, query=query
    )
    assert status == 200 and value["document"]["content"]["seed"] == 0
    assert (
        client.request("GET", PREFIX + "/inspect/artifacts/" + private.digest, query=query)[0]
        == 404
    )
    assert (
        client.request(
            "GET",
            PREFIX + "/inspect/artifacts/" + config.digest,
            query=urlencode({"via": json.dumps([result.digest] * 2)}),
        )[0]
        == 400
    )
    assert (
        client.request(
            "GET",
            PREFIX + "/inspect/artifacts/" + config.digest,
            query=urlencode({"via": json.dumps([private.digest])}),
        )[0]
        == 404
    )


def test_large_and_binary_artifact_reads_have_explicit_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    artifacts = LocalArtifactStore(root / "cas")
    large = artifacts.put_bytes(b"x" * 262145)
    binary = artifacts.put_bytes(b"\xff\xfe")
    with EventStore(root / "control.db") as store:
        store.append(
            _draft(
                "custom.fixture",
                {"large": large.digest, "binary": binary.digest},
                event_id="evt.root",
                project="proj-alpha",
                run="run-late",
            )
        )
    monkeypatch.setattr(
        LocalArtifactStore, "verify", lambda *_a, **_k: pytest.fail("unbounded hash read")
    )
    client = _client(root)
    _, _, body = client.request("GET", PREFIX + "/artifacts/" + large.digest)
    assert body["inline"] is False and body["verification"] == "not-inlined"
    _, _, body = client.request("GET", PREFIX + "/artifacts/" + binary.digest)
    assert body["inline"] is False and body["verification"] == "verified"


def test_plan_graph_uses_the_existing_compiler() -> None:
    from llm_research_os.blocks.registry import build_registry
    from llm_research_os.execution import TrustedKernel

    report = TrustedKernel(build_registry()).dry_run(
        load_spec(ROOT / "examples/valid/minimal.yaml")
    )
    assert report.plan is not None
    graph = graph_document(report.plan.model_dump_json(by_alias=True))
    assert graph["source"] == "ExecutionPlan"
    assert graph["graphs"][0]["nodes"] == [
        {"id": "workflow/workflow.simulation/simulate", "kind": "task"}
    ]


@pytest.mark.parametrize(
    "query", ["via=invalid", "via=null", "via=%5B1%5D", "via=" + "%5B%22x%22%5D" * 9]
)
def test_lineage_parameter_errors_are_closed(tmp_path: Path, query: str) -> None:
    client = _client(_root(tmp_path))
    status, _, body = client.request(
        "GET", PREFIX + "/inspect/artifacts/sha256:" + "1" * 64, query=query
    )
    assert status == 400 and body["code"] == "parameter-invalid"


def test_poisoned_artifact_link_cache_cannot_grant_project_visibility(tmp_path: Path) -> None:
    from llm_research_os.projections.sqlite import rebuild_query_tables

    root = _root(tmp_path)
    obj = LocalArtifactStore(root / "cas").put_bytes(b"private-other-project")
    with EventStore(root / "control.db") as store:
        store.append(
            _draft("custom.fixture", {}, event_id="evt.own", project="proj-alpha", run="run-late")
        )
        store.append(
            _draft(
                "custom.fixture",
                {"resultDigest": obj.digest},
                event_id="evt.other",
                project="proj-foreign",
                run="run-other",
            )
        )
        rebuild_query_tables(store)
        store._connection.execute(
            "INSERT INTO artifact_links(digest,event_sequence,role) VALUES(?,1,'result')",
            (obj.digest,),
        )
    assert _client(root).request("GET", PREFIX + "/artifacts/" + obj.digest)[0] == 404


def test_revision_page_reads_new_verified_facts_without_rebuilding_cache(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        store.append(_queued_draft(project="proj-alpha", run="run-late"))
        assert store.list_spec_revisions() == ()
    status, _, page = _client(root).request("GET", PREFIX + "/revisions")
    assert status == 200 and len(page["items"]) == 1
    assert page["items"][0]["firstSeenSequence"] == 1


def test_actual_read_responses_match_published_wire_schema(tmp_path: Path) -> None:
    client = _client(_root(tmp_path))
    validator = Draft202012Validator(build_schema())
    for path in [
        "/api/health",
        *[
            PREFIX + p
            for p in ["/session", "/capabilities", "/workspace", "/events", "/revisions", "/runs"]
        ],
    ]:
        status, _, body = client.request("GET", path)
        assert status == 200
        validator.validate(body)


def test_run_observation_uses_cursor_snapshot_after_new_cancellation(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        store.append(_queued_draft(event_id="evt.first", project="proj-alpha", run="run-first"))
        store.append(_queued_draft(event_id="evt.second", project="proj-alpha", run="run-second"))
        views = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-alpha")
        first = views.run_page(cursor=None, limit=1)
        control = RunControl(store, project_id="proj-alpha", run_id="run-first")
        control.append(_started_draft(project="proj-alpha", run="run-first"))
        control.append(
            _draft(
                "run.cancel.requested",
                {"reasonCode": "review-cancel"},
                event_id="evt.cancel",
                project="proj-alpha",
                run="run-first",
            )
        )
        second = views.run_page(cursor=first.next_cursor, limit=1)
        assert second.high_water_mark == 2
        assert second.items[0]["runId"] == "run-first"
        assert second.items[0]["observation"] == "queued"


def test_sse_accepts_the_decimal_id_it_emits_on_reconnect(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        _append(store, 1)
        _append(store, 2)
    api = LocalApi(
        load_workspace(root),
        sessions=SessionStore(bootstrap_token=BOOTSTRAP),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.01,
        stream_poll_seconds=0.001,
    )
    client = Client(api)
    client.bootstrap()
    status, _, body = client.request("GET", PREFIX + "/stream", headers={"Last-Event-ID": "1"})
    assert status == 200 and b"id: 2\n" in body and b"id: 1\n" not in body
    assert (
        client.request("GET", PREFIX + "/stream", headers={"Last-Event-ID": "2147483648"})[0] == 400
    )


def test_sse_event_cap_holds_after_partial_poll_and_new_facts(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with EventStore(root / "control.db") as store:
        for i in range(1, 51):
            _append(store, i)
    api = LocalApi(
        load_workspace(root),
        sessions=SessionStore(),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.01,
        stream_poll_seconds=0.001,
    )
    _, _, stream = api._stream(resume=0)
    chunks = iter(stream)
    first = [next(chunks)]
    for _ in range(101):
        first.append(next(chunks))
    assert b"high-water" in first[-1]
    with EventStore(root / "control.db") as store:
        for i in range(51, 251):
            _append(store, i)
    body = b"".join([*first, *chunks])
    assert body.count(b"id: ") == 200
    assert b'"lastSequence":200' in body


@pytest.mark.parametrize(
    "query", ["limit=%C2%B2", "limit=" + "1" * 50, "&".join("x=1" for _ in range(33))]
)
def test_invalid_query_bounds_are_parameter_errors(tmp_path: Path, query: str) -> None:
    status, _, body = _client(_root(tmp_path)).request("GET", PREFIX + "/events", query=query)
    assert status == 400 and body["code"] == "parameter-invalid"
