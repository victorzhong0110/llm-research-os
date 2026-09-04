from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.execution.request import (
    SIMULATION_REQUEST_API_VERSION,
    SIMULATION_REQUEST_SCHEMA_ID,
    load_simulation_request,
    validate_simulation_request_document,
)
from llm_research_os.execution.request_schema import (
    SCHEMA_ID,
    build_schema,
    schema_matches,
)
from llm_research_os.spec.io import SpecLoadError, load_document

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "simulation-request" / "v0alpha1.schema.json"
EXAMPLES = ROOT / "examples" / "simulation-requests"
PROTOCOL = ROOT / "docs" / "protocols" / "simulation-request-v0alpha1.md"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _valid_document() -> dict[str, Any]:
    return load_document(EXAMPLES / "valid" / "success.json")


def test_simulation_request_schema_declares_closed_external_contract() -> None:
    schema = build_schema()
    assert schema["$id"] == SCHEMA_ID == SIMULATION_REQUEST_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == SIMULATION_REQUEST_API_VERSION
    assert schema["properties"]["kind"]["const"] == "SimulationRequest"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "actor",
        "apiVersion",
        "attemptId",
        "authorization",
        "events",
        "kind",
        "runId",
        "source",
        "streamid",
        "subject",
        "workflowId",
    }
    events = schema["properties"]["events"]
    assert events["maxProperties"] == 13
    assert events["additionalProperties"] == {"$ref": "#/$defs/SimulationEventIdentityDocument"}
    assert set(events["propertyNames"]["enum"]) == {
        "attempt.cancelled",
        "attempt.failed",
        "attempt.queued",
        "attempt.started",
        "attempt.succeeded",
        "attempt.unknown",
        "evaluation.metric",
        "run.cancelled",
        "run.completed",
        "run.failed",
        "run.queued",
        "run.started",
        "training.step",
    }


def test_committed_simulation_request_schema_is_current_and_valid() -> None:
    assert schema_matches(SCHEMA)
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_schema_and_model_accept_metrics_request() -> None:
    document = load_document(EXAMPLES / "valid" / "success-with-metrics.json")
    _validator().validate(document)
    request = validate_simulation_request_document(document)
    assert "training.step" in request.events
    assert "evaluation.metric" in request.events


def test_schema_and_model_accept_valid_request() -> None:
    document = _valid_document()
    _validator().validate(document)
    request = validate_simulation_request_document(document)
    runtime = request.runtime_request()
    assert request.model_dump(mode="json", by_alias=True) == document
    assert request.run_id == "run.simulated"
    assert runtime.workflow_id == "workflow.simulation"
    assert runtime.attempt_id == "attempt.1"
    assert set(runtime.events) == {
        "run.queued",
        "run.started",
        "run.completed",
        "attempt.queued",
        "attempt.started",
        "attempt.succeeded",
    }
    assert runtime.authorization_event_id == "evt.authorization.example-minimal.1"
    assert runtime.authorization_sequence == "1"


def test_protocol_normative_example_matches_valid_request() -> None:
    rendered = json.dumps(_valid_document(), ensure_ascii=False, indent=2)
    assert rendered in PROTOCOL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name",
    (
        "python-field-names.json",
        "unknown-event-type.json",
        "invalid-time-offset.json",
    ),
)
def test_schema_invalid_examples_are_rejected_by_model(name: str) -> None:
    document = load_document(EXAMPLES / "invalid" / name)
    assert list(_validator().iter_errors(document)), name
    with pytest.raises(ValidationError):
        validate_simulation_request_document(document)


def test_duplicate_event_ids_are_a_semantic_model_rule() -> None:
    document = load_document(EXAMPLES / "invalid" / "duplicate-event-id.json")
    _validator().validate(document)
    with pytest.raises(ValidationError, match="event ids must be unique"):
        validate_simulation_request_document(document)


def test_request_rejects_coercion_unknown_fields_and_invalid_uri() -> None:
    cases: list[dict[str, Any]] = []

    numeric_run = _valid_document()
    numeric_run["runId"] = 1
    cases.append(numeric_run)

    boolean_actor = _valid_document()
    boolean_actor["actor"]["id"] = True
    cases.append(boolean_actor)

    unknown = _valid_document()
    unknown["secret-field"] = "sk-secret-value"
    cases.append(unknown)

    invalid_source = _valid_document()
    invalid_source["source"] = "a#b#c"
    cases.append(invalid_source)

    null_identity = _valid_document()
    null_identity["events"]["run.queued"] = None
    cases.append(null_identity)

    for document in cases:
        assert list(_validator().iter_errors(document))
        with pytest.raises(ValidationError):
            validate_simulation_request_document(document)


def test_validated_request_does_not_alias_decoded_document() -> None:
    document = _valid_document()
    request = validate_simulation_request_document(document)
    document["runId"] = "run.changed"
    document["events"]["run.queued"]["id"] = "evt.changed"
    runtime = request.runtime_request()
    assert request.run_id == "run.simulated"
    assert runtime.events["run.queued"].id == "evt.1.run.queued"
    with pytest.raises(TypeError):
        request.events["run.queued"] = request.events["run.started"]  # type: ignore[index]


def test_request_loader_rejects_symbolic_links(tmp_path: Path) -> None:
    link = tmp_path / "request.json"
    link.symlink_to(EXAMPLES / "valid" / "success.json")
    with pytest.raises(SpecLoadError, match="symbolic link"):
        load_simulation_request(link)


def test_request_loader_rejects_duplicate_keys_and_yaml_aliases(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"kind":"SimulationRequest","kind":"changed"}', encoding="utf-8")
    with pytest.raises(SpecLoadError, match="duplicate JSON object key"):
        load_simulation_request(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("actor: &actor\n  id: researcher.alice\ncopy: *actor\n", encoding="utf-8")
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_simulation_request(alias)
