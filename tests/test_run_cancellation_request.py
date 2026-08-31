from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.events.models import validate_event_document
from llm_research_os.runs import (
    AttemptCancellationTarget,
    RunCancellationRequestDocument,
    RunCancellationTarget,
    load_run_cancellation_request,
    validate_run_cancellation_request_document,
)
from llm_research_os.runs.cancellation_schema import build_schema, canonical_schema
from llm_research_os.spec.io import SpecLoadError, load_document

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "run-cancellation-requests"
SCHEMA = ROOT / "schemas" / "run-cancellation-request" / "v0alpha1.schema.json"


def _document(name: str = "run.json") -> dict[str, Any]:
    return load_document(EXAMPLES / "valid" / name)


def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_valid_examples_match_model_and_committed_schema() -> None:
    validator = _schema_validator()
    for path in sorted((EXAMPLES / "valid").glob("*.json")):
        document = load_document(path)
        validated = validate_run_cancellation_request_document(document)
        validator.validate(document)
        validator.validate(validated.model_dump(mode="json", by_alias=True))
        if path.name == "run.json":
            assert isinstance(validated.target, RunCancellationTarget)
        else:
            assert isinstance(validated.target, AttemptCancellationTarget)


def test_invalid_examples_are_rejected_by_model_and_schema() -> None:
    validator = _schema_validator()
    for path in sorted((EXAMPLES / "invalid").glob("*.json")):
        document = load_document(path)
        with pytest.raises(ValidationError):
            validate_run_cancellation_request_document(document)
        assert list(validator.iter_errors(document)), path.name


def test_generated_schema_is_deterministic_and_current() -> None:
    assert json.loads(canonical_schema()) == build_schema()
    assert SCHEMA.read_text(encoding="utf-8") == canonical_schema()
    schema = build_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/run-cancellation-request/v0alpha1.schema.json")


@pytest.mark.parametrize(
    ("alias", "python_name"),
    [
        ("apiVersion", "api_version"),
        ("projectId", "project_id"),
        ("experimentRevision", "experiment_revision"),
        ("runId", "run_id"),
        ("reasonCode", "reason_code"),
        ("streamid", "stream_id"),
        ("evidenceRefs", "evidence_refs"),
    ],
)
def test_python_field_names_are_rejected(alias: str, python_name: str) -> None:
    document = _document()
    document[python_name] = document.pop(alias)
    with pytest.raises(ValidationError):
        validate_run_cancellation_request_document(document)


def test_nested_python_field_name_and_explicit_null_are_rejected() -> None:
    attempt = _document("attempt.json")
    attempt["target"]["attempt_id"] = attempt["target"].pop("attemptId")
    with pytest.raises(ValidationError):
        validate_run_cancellation_request_document(attempt)

    for path in (("event", "id"), ("actor", "id"), (None, "reasonCode")):
        document = _document()
        parent = document if path[0] is None else document[path[0]]
        parent[path[1]] = None
        with pytest.raises(ValidationError):
            validate_run_cancellation_request_document(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experimentRevision", "1"),
        ("experimentRevision", True),
        ("projectId", 7),
        ("reasonCode", False),
        ("streamid", 9),
    ],
)
def test_scalar_coercion_is_rejected(field: str, value: object) -> None:
    document = _document()
    document[field] = value
    with pytest.raises(ValidationError):
        validate_run_cancellation_request_document(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "a#b#c"),
        ("source", "http://["),
        ("source", "foo[bar"),
    ],
)
def test_invalid_uri_reference_is_rejected(field: str, value: str) -> None:
    document = _document()
    document[field] = value
    with pytest.raises(ValidationError):
        validate_run_cancellation_request_document(document)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-30T12:00:01",
        "2026-08-30T12:00:01+00:60",
        "2026-02-30T12:00:01Z",
    ],
)
def test_invalid_rfc3339_event_time_is_rejected(value: str) -> None:
    document = _document()
    document["event"]["time"] = value
    with pytest.raises(ValidationError):
        validate_run_cancellation_request_document(document)


def test_request_isolated_from_mutable_input_and_builds_valid_run_draft() -> None:
    document = _document()
    document["evidenceRefs"] = ["evidence.note.1"]
    validated = RunCancellationRequestDocument.model_validate(document)
    document["evidenceRefs"].append("evidence.note.2")
    document["actor"]["id"] = "attacker.changed"
    draft = validated.event_draft()
    assert draft["type"] == "run.cancel.requested"
    assert draft["data"]["actor"] == {"id": "researcher.alice"}
    assert draft["data"]["evidenceRefs"] == ["evidence.note.1"]
    complete = {
        **draft,
        "sequence": "1",
        "sequencetype": "Integer",
        "streamversion": 0,
    }
    assert validate_event_document(complete).type == "run.cancel.requested"


def test_non_json_evidence_container_is_rejected() -> None:
    document = _document()
    document["evidenceRefs"] = ("evidence.note.1",)
    with pytest.raises(ValidationError, match="JSON array"):
        validate_run_cancellation_request_document(document)


def test_attempt_target_builds_only_attempt_cancel_request() -> None:
    validated = validate_run_cancellation_request_document(_document("attempt.json"))
    draft = validated.event_draft()
    assert draft["type"] == "attempt.cancel.requested"
    assert draft["data"]["attemptId"] == "attempt.1"
    assert "blockId" not in draft["data"]
    assert "sequence" not in draft
    assert "streamversion" not in draft


def test_loader_rejects_duplicate_keys_yaml_aliases_and_symlinks(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"apiVersion":"researchos.dev/v0alpha1","apiVersion":"other"}',
        encoding="utf-8",
    )
    alias = tmp_path / "alias.yaml"
    alias.write_text("base: &base {kind: run}\ntarget: *base\n", encoding="utf-8")
    link = tmp_path / "request.json"
    link.symlink_to(EXAMPLES / "valid" / "run.json")
    for path in (duplicate, alias, link):
        with pytest.raises(SpecLoadError):
            load_run_cancellation_request(path)
