from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.errors import BudgetExceededError
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.providers.compat import CompatHttpProvider
from llm_research_os.providers.compat_requests import (
    load_compat_generate_request,
    validate_compat_generate_request,
)
from llm_research_os.providers.control import ModelCallControl
from llm_research_os.providers.errors import (
    ModelCallError,
    ModelCapabilityError,
    ModelRequestError,
    ModelTransportError,
)
from llm_research_os.providers.models import ModelFixtureDocument
from llm_research_os.providers.provider import GenerateResult
from llm_research_os.providers.requests import load_model_fixture
from llm_research_os.providers.schema import openai_compat_generate_request_schema_matches
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventSequenceConflictError, EventStore

ROOT = Path(__file__).parents[1]
REQUESTS = ROOT / "examples" / "openai-compat-requests"
FIXTURE = ROOT / "examples" / "model-fixtures" / "valid" / "compat-local.json"
SCHEMA = ROOT / "schemas" / "openai-compat-generate-request" / "v0alpha1.schema.json"
LOCAL_REQUEST = REQUESTS / "valid" / "local.json"
REMOTE_REQUEST = REQUESTS / "valid" / "remote.json"
PROMPT_TOKEN = "HTTP_PROMPT_UNIQUE_TOKEN_bravo"
OUTPUT_TOKEN = "HTTP_OUTPUT_UNIQUE_TOKEN_zulu"
SECRET = "sk-test-not-a-real-secret-m14"
EVENT_KEYS = (
    "ai.call.started",
    "ai.call.completed",
    "ai.call.failed",
    "budget.reserved",
    "budget.consumed",
    "budget.exceeded",
    "budget.released",
)


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


def _retarget_events(document: dict[str, object], suffix: str) -> None:
    events = document["events"]
    assert isinstance(events, dict)
    for key in EVENT_KEYS:
        identity = events[key]
        assert isinstance(identity, dict)
        event_id = identity["id"]
        assert isinstance(event_id, str)
        identity["id"] = f"{event_id.rsplit('.', 1)[0]}.{suffix}"


def _remote_document(
    *,
    suffix: str,
    cap: str,
    reserve: str,
    consume: str,
) -> dict[str, object]:
    document = deepcopy(load_document(REMOTE_REQUEST))
    document["budgetCap"] = cap
    document["reserveAmount"] = reserve
    document["consumeAmount"] = consume
    document["callId"] = f"call.compat-remote.{suffix}"
    document["budgetId"] = f"budget.compat-remote.{suffix}"
    _retarget_events(document, suffix)
    return document


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
            "ai.call.started",
            "budget.consumed",
            "ai.call.completed",
        ]
        encoded = json.dumps(
            [item.event.model_dump(mode="json", by_alias=True) for item in events],
            ensure_ascii=False,
        )
        assert PROMPT_TOKEN not in encoded
        assert OUTPUT_TOKEN not in encoded
        assert SECRET not in encoded
        started = events[1].event
        completed = events[3].event
        assert started.data.payload["promptDigest"] == content_digest(fixture.prompt)
        assert completed.data.payload["outputDigest"] == content_digest({"text": OUTPUT_TOKEN})
        assert started.data.payload["local"] is True
        assert started.data.payload["costKnown"] is True
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
        assert first.consumed is None
        assert first.started.event.data.payload["costKnown"] is False
        second = validate_compat_generate_request(
            _remote_document(suffix="2", cap="1.00", reserve="1.00", consume="1.00")
        )
        with pytest.raises(BudgetExceededError):
            ModelCallControl(store, project_id=request.project_id).record_http_generate(
                second,
                fixture,
                provider,
            )
        types = [item.event.type for item in store.read_events(limit=20)]
        assert types[-1] == "budget.exceeded"
        assert types.count("ai.call.started") == 1
        assert types == [
            "budget.reserved",
            "ai.call.started",
            "ai.call.completed",
            "budget.exceeded",
        ]
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


def test_transport_error_releases_reservation_and_records_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEARCHOS_TEST_MODEL_KEY", SECRET)
    database = tmp_path / "research.db"
    request = validate_compat_generate_request(
        _remote_document(suffix="fail", cap="1.00", reserve="0.60", consume="0.60")
    )
    fixture = load_model_fixture(FIXTURE)

    def transport(url: str, payload: bytes, headers: dict[str, str]) -> dict[str, object]:
        raise ModelTransportError("model endpoint could not be reached", code="transport")

    provider = CompatHttpProvider(
        endpoint=request.endpoint,
        model_id=request.actor.model_id,
        secret=SECRET,
        transport=transport,
    )
    with EventStore(database) as store:
        with pytest.raises(ModelTransportError) as captured:
            ModelCallControl(store, project_id=request.project_id).record_http_generate(
                request,
                fixture,
                provider,
            )
        assert captured.value.code == "transport"
        types = [item.event.type for item in store.read_events(limit=10)]
        assert types == [
            "budget.reserved",
            "ai.call.started",
            "budget.released",
            "ai.call.failed",
        ]
        fold = BudgetControl(store, project_id=request.project_id).rebuild().fold
        assert fold.outstanding == 0
        assert fold.open == ()
        encoded = json.dumps(
            [
                item.event.model_dump(mode="json", by_alias=True)
                for item in store.read_events(limit=10)
            ],
            ensure_ascii=False,
        )
        assert SECRET not in encoded


def test_digest_mismatch_after_http_does_not_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEARCHOS_TEST_MODEL_KEY", SECRET)
    database = tmp_path / "research.db"
    request = validate_compat_generate_request(
        _remote_document(suffix="mismatch", cap="1.00", reserve="0.60", consume="0.60")
    )
    fixture = load_model_fixture(FIXTURE)

    class MismatchProvider(CompatHttpProvider):
        def generate_fixture(self, model_fixture: ModelFixtureDocument) -> GenerateResult:
            result = super().generate_fixture(model_fixture)
            return GenerateResult(
                prompt_digest="jcs-sha256:" + ("0" * 64),
                output_digest=result.output_digest,
                capabilities=result.capabilities,
                output_payload=result.output_payload,
            )

    provider = MismatchProvider(
        endpoint=request.endpoint,
        model_id=request.actor.model_id,
        secret=SECRET,
        transport=lambda url, payload, headers: _completion(OUTPUT_TOKEN),
    )
    with EventStore(database) as store:
        with pytest.raises(ModelCallError, match="prompt digest"):
            ModelCallControl(store, project_id=request.project_id).record_http_generate(
                request,
                fixture,
                provider,
            )
        types = [item.event.type for item in store.read_events(limit=10)]
        assert types == ["budget.reserved", "ai.call.started"]
        fold = BudgetControl(store, project_id=request.project_id).rebuild().fold
        assert str(fold.outstanding) == "0.60"


def test_concurrent_reservations_only_affordable_call_hits_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEARCHOS_TEST_MODEL_KEY", SECRET)
    database = tmp_path / "research.db"
    _init_store(database)
    fixture = load_model_fixture(FIXTURE)
    transports: list[str] = []
    lock = Lock()
    start = Barrier(2, timeout=5)

    def transport(url: str, payload: bytes, headers: dict[str, str]) -> dict[str, object]:
        with lock:
            transports.append(url)
        return _completion(OUTPUT_TOKEN)

    def run_one(suffix: str) -> str:
        request = validate_compat_generate_request(
            _remote_document(suffix=suffix, cap="1.00", reserve="0.60", consume="0.60")
        )
        provider = CompatHttpProvider(
            endpoint=request.endpoint,
            model_id=request.actor.model_id,
            secret=SECRET,
            transport=transport,
        )
        with EventStore(database, require_existing=True) as store:
            start.wait()
            try:
                ModelCallControl(store, project_id=request.project_id).record_http_generate(
                    request,
                    fixture,
                    provider,
                )
            except BudgetExceededError:
                return "exceeded"
            except EventSequenceConflictError:
                return "conflict"
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(run_one, ("a", "b")))
    assert outcomes.count("ok") == 1
    assert len(transports) == 1
    assert "exceeded" in outcomes or "conflict" in outcomes
