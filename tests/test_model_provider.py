from __future__ import annotations

import builtins
import importlib
import json
import socket
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.events.models import validate_event_document
from llm_research_os.providers.capabilities import ModelCapability
from llm_research_os.providers.control import ModelCallControl
from llm_research_os.providers.errors import (
    ModelCapabilityError,
    ModelPayloadError,
    ModelRequestError,
)
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.models import INLINE_MODEL_KEYS, parse_ai_call_payload
from llm_research_os.providers.provider import GenerateRequest
from llm_research_os.providers.requests import (
    load_model_fixture,
    load_model_generate_request,
)
from llm_research_os.providers.schema import (
    build_model_generate_request_schema,
    model_fixture_schema_matches,
    model_generate_request_schema_matches,
)
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "examples" / "model-fixtures"
REQUESTS = ROOT / "examples" / "model-generate-requests"
FIXTURE_SCHEMA = ROOT / "schemas" / "model-fixture" / "v0alpha1.schema.json"
REQUEST_SCHEMA = ROOT / "schemas" / "model-generate-request" / "v0alpha1.schema.json"
VALID_FIXTURE = FIXTURES / "valid" / "generate-json.json"
VALID_REQUEST = REQUESTS / "valid" / "generate.json"
TOOLS_REQUEST = REQUESTS / "valid" / "tools-not-allowed.json"
PROMPT_TOKEN = "MOCK_PROMPT_UNIQUE_TOKEN_alpha"
OUTPUT_TOKEN = "MOCK_OUTPUT_UNIQUE_TOKEN_omega"


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _init_store(path: Path) -> None:
    with EventStore(path) as store:
        assert store.last_sequence() == 0


def test_committed_model_schemas_are_current() -> None:
    assert model_fixture_schema_matches(FIXTURE_SCHEMA)
    assert model_generate_request_schema_matches(REQUEST_SCHEMA)
    for path in (FIXTURE_SCHEMA, REQUEST_SCHEMA):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_generate_request_schema_requires_both_call_events() -> None:
    schema = build_model_generate_request_schema()
    events = schema["properties"]["events"]
    assert events["minProperties"] == 2
    assert events["maxProperties"] == 2
    assert set(events["required"]) == {"ai.call.started", "ai.call.completed"}


@pytest.mark.parametrize(
    "path",
    sorted((REQUESTS / "valid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_model_generate_examples(path: Path) -> None:
    document = load_document(path)
    _validator(REQUEST_SCHEMA).validate(document)
    load_model_generate_request(path)


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURES / "valid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_model_fixture_examples(path: Path) -> None:
    document = load_document(path)
    _validator(FIXTURE_SCHEMA).validate(document)
    load_model_fixture(path)


@pytest.mark.parametrize(
    "path",
    sorted((REQUESTS / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_model_generate_examples(path: Path) -> None:
    document = load_document(path)
    schema_error = False
    try:
        _validator(REQUEST_SCHEMA).validate(document)
    except JsonSchemaValidationError:
        schema_error = True
    model_error = False
    try:
        load_model_generate_request(path)
    except ModelRequestError:
        model_error = True
    assert schema_error or model_error


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURES / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_model_fixture_examples(path: Path) -> None:
    document = load_document(path)
    schema_error = False
    try:
        _validator(FIXTURE_SCHEMA).validate(document)
    except JsonSchemaValidationError:
        schema_error = True
    model_error = False
    try:
        load_model_fixture(path)
    except ModelRequestError:
        model_error = True
    assert schema_error or model_error


def test_mock_generate_records_digests_not_fixture_text(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert (
        main(
            [
                "models",
                "generate",
                str(VALID_REQUEST),
                str(database),
                "--fixture",
                str(VALID_FIXTURE),
                "--format",
                "json",
            ]
        )
        == 0
    )
    fixture = load_model_fixture(VALID_FIXTURE)
    with EventStore(database, require_existing=True) as store:
        events = store.read_events(limit=10)
        assert [item.event.type for item in events] == ["ai.call.started", "ai.call.completed"]
        started = events[0].event
        completed = events[1].event
        encoded = json.dumps(
            [item.event.model_dump(mode="json", by_alias=True) for item in events],
            ensure_ascii=False,
        )
        assert PROMPT_TOKEN not in encoded
        assert OUTPUT_TOKEN not in encoded
        for key in INLINE_MODEL_KEYS:
            assert key not in started.data.payload
            assert key not in completed.data.payload
        assert started.data.payload["promptDigest"] == content_digest(fixture.prompt)
        assert completed.data.payload["outputDigest"] == content_digest(fixture.output)
        parse_ai_call_payload(started)
        parse_ai_call_payload(completed)


def test_mock_generate_with_artifacts_shares_jcs_hex(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    assert (
        main(
            [
                "models",
                "generate",
                str(VALID_REQUEST),
                str(database),
                "--fixture",
                str(VALID_FIXTURE),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    fixture = load_model_fixture(VALID_FIXTURE)
    with EventStore(database, require_existing=True) as store:
        completed = store.read_events(limit=10)[1].event
        prompt_artifact = completed.data.payload["promptArtifact"]
        output_artifact = completed.data.payload["outputArtifact"]
        assert prompt_artifact == content_digest(fixture.prompt).replace("jcs-sha256:", "sha256:")
        assert output_artifact == content_digest(fixture.output).replace("jcs-sha256:", "sha256:")
        LocalArtifactStore(artifacts).verify(prompt_artifact)
        LocalArtifactStore(artifacts).verify(output_artifact)


def test_disallowed_capability_writes_no_events(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    assert (
        main(
            [
                "models",
                "generate",
                str(TOOLS_REQUEST),
                str(database),
                "--fixture",
                str(VALID_FIXTURE),
                "--format",
                "json",
            ]
        )
        == 1
    )
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == 0


def test_provider_refuses_tools_without_faking_them() -> None:
    fixture = load_model_fixture(VALID_FIXTURE)
    provider = DeterministicMockProvider({fixture.id: fixture})
    with pytest.raises(ModelCapabilityError, match="not allowed") as info:
        provider.generate(
            GenerateRequest(
                fixture_id=fixture.id,
                requested=frozenset({ModelCapability.GENERATE, ModelCapability.TOOLS}),
            )
        )
    assert info.value.code == "capability-not-allowed"


def test_duplicate_call_id_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    argv = [
        "models",
        "generate",
        str(VALID_REQUEST),
        str(database),
        "--fixture",
        str(VALID_FIXTURE),
        "--format",
        "json",
    ]
    assert main(argv) == 0
    assert main(argv) == 1
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == 2


def test_inline_prompt_key_on_stored_event_fails_rebuild(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    request = load_model_generate_request(VALID_REQUEST)
    fixture = load_model_fixture(VALID_FIXTURE)
    provider = DeterministicMockProvider({fixture.id: fixture})
    with EventStore(database) as store:
        result = ModelCallControl(store, project_id=request.project_id).record_generate(
            request,
            fixture,
            provider,
        )
        hostile = result.started.event.model_dump(mode="json", by_alias=True)
        hostile["id"] = "evt.call.hostile.1"
        del hostile["sequence"]
        del hostile["sequencetype"]
        del hostile["streamversion"]
        hostile["data"]["payload"]["prompt"] = PROMPT_TOKEN
        store.append(hostile)
        with pytest.raises(ModelPayloadError, match="must not embed"):
            ModelCallControl(store, project_id=request.project_id).rebuild()


def test_side_effect_tripwires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"model provider side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    database = tmp_path / "research.db"
    _init_store(database)
    assert (
        main(
            [
                "models",
                "generate",
                str(VALID_REQUEST),
                str(database),
                "--fixture",
                str(VALID_FIXTURE),
            ]
        )
        == 0
    )


def test_mock_modules_have_no_network_imports() -> None:
    for module_name in (
        "llm_research_os.providers.mock",
        "llm_research_os.providers.provider",
        "llm_research_os.providers.control",
    ):
        module = importlib.import_module(module_name)
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        for forbidden in (
            "urllib",
            "http.client",
            "httpx",
            "openai",
            "subprocess",
            "socket",
            "datetime.now",
            "cuda",
            "mps",
        ):
            assert forbidden not in source, module_name


def test_validate_event_document_accepts_recorded_call(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _init_store(database)
    main(
        [
            "models",
            "generate",
            str(VALID_REQUEST),
            str(database),
            "--fixture",
            str(VALID_FIXTURE),
        ]
    )
    with EventStore(database, require_existing=True) as store:
        for item in store.read_events(limit=10):
            validate_event_document(item.event.model_dump(mode="json", by_alias=True))
