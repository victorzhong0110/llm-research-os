from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from llm_research_os.budget.errors import BudgetExceededError
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.providers.compat import CompatHttpProvider
from llm_research_os.providers.compat_requests import (
    load_compat_generate_request,
    validate_compat_generate_request,
)
from llm_research_os.providers.control import ModelCallControl
from llm_research_os.providers.errors import ModelCapabilityError, ModelRequestError
from llm_research_os.providers.requests import load_model_fixture
from llm_research_os.providers.schema import openai_compat_generate_request_schema_matches
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
REQUESTS = ROOT / "examples" / "openai-compat-requests"
FIXTURE = ROOT / "examples" / "model-fixtures" / "valid" / "compat-local.json"
SCHEMA = ROOT / "schemas" / "openai-compat-generate-request" / "v0alpha1.schema.json"
LOCAL_REQUEST = REQUESTS / "valid" / "local.json"
REMOTE_REQUEST = REQUESTS / "valid" / "remote.json"
PROMPT_TOKEN = "HTTP_PROMPT_UNIQUE_TOKEN_bravo"
OUTPUT_TOKEN = "HTTP_OUTPUT_UNIQUE_TOKEN_zulu"
SECRET = "sk-test-not-a-real-secret-m14"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _init_store(path: Path) -> None:
    with EventStore(path) as store:
        assert store.last_sequence() == 0


def _completion(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


class _CompletionHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        payload = json.dumps(_completion(OUTPUT_TOKEN)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def _serve() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CompletionHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/v1"


def _request_with_endpoint(source: Path, destination: Path, endpoint: str) -> None:
    document = load_document(source)
    document["endpoint"] = endpoint
    destination.write_text(json.dumps(document), encoding="utf-8")


def test_committed_compat_schema_is_current() -> None:
    assert openai_compat_generate_request_schema_matches(SCHEMA)
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "path",
    sorted((REQUESTS / "valid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_compat_examples(path: Path) -> None:
    document = load_document(path)
    _validator().validate(document)
    load_compat_generate_request(path)


@pytest.mark.parametrize(
    "path",
    sorted((REQUESTS / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_compat_examples(path: Path) -> None:
    document = load_document(path)
    schema_error = False
    try:
        _validator().validate(document)
    except JsonSchemaValidationError:
        schema_error = True
    model_error = False
    try:
        load_compat_generate_request(path)
    except ModelRequestError:
        model_error = True
    assert schema_error or model_error


def test_loopback_generate_records_budget_and_digest_facts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    server, endpoint = _serve()
    try:
        request_path = tmp_path / "local.json"
        _request_with_endpoint(LOCAL_REQUEST, request_path, endpoint)
        assert (
            main(
                [
                    "models",
                    "generate",
                    str(request_path),
                    str(database),
                    "--fixture",
                    str(FIXTURE),
                    "--format",
                    "json",
                ]
            )
            == 0
        )
    finally:
        server.shutdown()
    fixture = load_model_fixture(FIXTURE)
    with EventStore(database, require_existing=True) as store:
        events = store.read_events(limit=10)
        assert [item.event.type for item in events] == [
            "budget.reserved",
            "budget.consumed",
            "ai.call.started",
            "ai.call.completed",
        ]
        encoded = json.dumps(
            [item.event.model_dump(mode="json", by_alias=True) for item in events],
            ensure_ascii=False,
        )
        assert PROMPT_TOKEN not in encoded
        assert OUTPUT_TOKEN not in encoded
        assert SECRET not in encoded
        started = events[2].event
        completed = events[3].event
        assert started.data.payload["promptDigest"] == content_digest(fixture.prompt)
        assert completed.data.payload["outputDigest"] == content_digest({"text": OUTPUT_TOKEN})
        assert started.data.payload["local"] is True
        assert started.data.payload["dataLeavesMachine"] is False
        assert events[0].event.data.payload["amount"] == "0.00"


def test_remote_requires_secret_and_does_not_connect(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert (
        main(
            [
                "models",
                "generate",
                str(REMOTE_REQUEST),
                str(database),
                "--fixture",
                str(FIXTURE),
                "--format",
                "json",
            ]
        )
        == 1
    )
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == 0


def test_injected_remote_transport_redacts_secret_and_enforces_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEARCHOS_TEST_MODEL_KEY", SECRET)
    database = tmp_path / "research.db"
    first_document = load_document(REMOTE_REQUEST)
    first_document["budgetCap"] = "1.00"
    request = validate_compat_generate_request(first_document)
    fixture = load_model_fixture(FIXTURE)
    seen_headers: dict[str, str] = {}

    def transport(url: str, payload: bytes, headers: dict[str, str]) -> dict[str, object]:
        seen_headers.update(headers)
        assert url.startswith("https://example.invalid/")
        assert SECRET.encode() not in payload
        return _completion(OUTPUT_TOKEN)

    provider = CompatHttpProvider(
        endpoint=request.endpoint,
        model_id=request.actor.model_id,
        secret=SECRET,
        transport=transport,
    )
    with EventStore(database) as store:
        first = ModelCallControl(store, project_id=request.project_id).record_http_generate(
            request,
            fixture,
            provider,
        )
        encoded = json.dumps(
            first.completed.event.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
        )
        assert SECRET not in encoded
        assert seen_headers["Authorization"] == f"Bearer {SECRET}"
        second_document = load_document(REMOTE_REQUEST)
        second_document["budgetCap"] = "1.00"
        second_document["callId"] = "call.compat-remote.2"
        second_document["budgetId"] = "budget.compat-remote.2"
        second_document["events"]["ai.call.started"]["id"] = "evt.compat.remote.started.2"
        second_document["events"]["ai.call.completed"]["id"] = "evt.compat.remote.completed.2"
        second_document["events"]["budget.reserved"]["id"] = "evt.budget.remote.reserved.2"
        second_document["events"]["budget.consumed"]["id"] = "evt.budget.remote.consumed.2"
        second_document["events"]["budget.exceeded"]["id"] = "evt.budget.remote.exceeded.2"
        second = validate_compat_generate_request(second_document)
        with pytest.raises(BudgetExceededError):
            ModelCallControl(store, project_id=request.project_id).record_http_generate(
                second,
                fixture,
                provider,
            )
            types = [item.event.type for item in store.read_events(limit=20)]
            assert types[-1] == "budget.exceeded"
            assert types.count("ai.call.started") == 1
            exceeded = json.dumps(store.read_events(limit=20)[-1].event.model_dump(mode="json"))
            assert SECRET not in exceeded


def test_tools_capability_writes_no_events(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    document = load_document(LOCAL_REQUEST)
    document["requestedCapabilities"] = ["generate", "tools"]
    request = validate_compat_generate_request(document)
    fixture = load_model_fixture(FIXTURE)
    provider = CompatHttpProvider(
        endpoint=request.endpoint,
        model_id=request.actor.model_id,
        transport=lambda url, payload, headers: _completion(OUTPUT_TOKEN),
    )
    with EventStore(database) as store:
        with pytest.raises(ModelCapabilityError, match="not allowed"):
            ModelCallControl(store, project_id=request.project_id).record_http_generate(
                request,
                fixture,
                provider,
            )
        assert store.last_sequence() == 0
