import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.events.models import validate_event_document
from llm_research_os.events.schema import SCHEMA_DIALECT, SCHEMA_ID, build_schema, schema_matches
from llm_research_os.spec.io import load_document

SCHEMA = Path(__file__).parents[1] / "schemas" / "research-event" / "v0alpha1.schema.json"
EXAMPLES = Path(__file__).parents[1] / "examples" / "events"
PROTOCOL = Path(__file__).parents[1] / "docs" / "protocols" / "research-event-v0alpha1.md"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _valid_document() -> dict[str, Any]:
    return load_document(EXAMPLES / "valid" / "minimal.json")


def test_event_schema_declares_external_contract() -> None:
    schema = build_schema()
    assert schema["$schema"] == SCHEMA_DIALECT
    assert schema["$id"] == SCHEMA_ID
    assert schema["properties"]["specversion"]["const"] == "1.0"
    assert schema["properties"]["sequencetype"]["const"] == "Integer"
    assert schema["properties"]["sequence"]["type"] == "string"
    assert schema["additionalProperties"] is False
    required = set(schema["required"])
    assert {
        "specversion",
        "id",
        "source",
        "type",
        "time",
        "subject",
        "dataschema",
        "datacontenttype",
        "data",
        "sequence",
        "sequencetype",
        "streamid",
        "streamversion",
    } <= required
    assert "correlationid" not in required
    assert "causationid" not in required
    evidence_refs = schema["$defs"]["ResearchEventData"]["properties"]["evidenceRefs"]
    assert evidence_refs["uniqueItems"] is True


def test_committed_event_schema_is_current() -> None:
    assert schema_matches(SCHEMA)


def test_committed_event_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_external_event_schema_accepts_valid_examples() -> None:
    validator = _validator()
    for path in sorted((EXAMPLES / "valid").glob("*.json")):
        validator.validate(load_document(path))


def test_protocol_normative_example_matches_minimal_conformance_event() -> None:
    example = json.dumps(
        load_document(EXAMPLES / "valid" / "minimal.json"),
        ensure_ascii=False,
        indent=2,
    )
    protocol = PROTOCOL.read_text(encoding="utf-8")
    assert example in protocol


def test_external_event_schema_rejects_unknown_specversion() -> None:
    document = load_document(EXAMPLES / "invalid" / "unknown-specversion.json")
    errors = list(_validator().iter_errors(document))
    assert errors


def test_external_event_schema_rejects_unknown_envelope_field() -> None:
    document = load_document(EXAMPLES / "invalid" / "unknown-envelope-field.json")
    errors = list(_validator().iter_errors(document))
    assert errors


def test_duplicate_evidence_refs_fail_json_schema() -> None:
    document = load_document(EXAMPLES / "invalid" / "duplicate-evidence-refs.json")
    errors = list(_validator().iter_errors(document))
    assert errors


def test_semantic_event_rules_are_enforced_beyond_json_schema() -> None:
    validator = _validator()
    embedded = load_document(EXAMPLES / "invalid" / "embedded-inline-content.json")
    validator.validate(embedded)
    with pytest.raises(ValidationError, match="must not embed file bytes or document bodies"):
        validate_event_document(embedded)


def test_schema_invalid_documents_are_rejected_by_the_model() -> None:
    validator = _validator()
    cases: list[tuple[str, dict[str, Any]]] = []

    python_names = _valid_document()
    data = python_names["data"]
    data["schema_version"] = data.pop("schemaVersion")
    data["project_id"] = data.pop("projectId")
    data["experiment_revision"] = data.pop("experimentRevision")
    data["evidence_refs"] = data.pop("evidenceRefs")
    cases.append(("python field names", python_names))

    numeric_sequence = _valid_document()
    numeric_sequence["sequence"] = 1
    cases.append(("numeric sequence", numeric_sequence))

    boolean_sequence = _valid_document()
    boolean_sequence["sequence"] = True
    cases.append(("boolean sequence", boolean_sequence))

    numeric_time = _valid_document()
    numeric_time["time"] = 1_724_241_600
    cases.append(("numeric time", numeric_time))

    string_streamversion = _valid_document()
    string_streamversion["streamversion"] = "0"
    cases.append(("string streamversion", string_streamversion))

    boolean_revision = _valid_document()
    boolean_revision["data"]["experimentRevision"] = True
    cases.append(("boolean experimentRevision", boolean_revision))

    percent_source = _valid_document()
    percent_source["source"] = "https://researchos.dev/projects/%zz"
    cases.append(("invalid percent-encoding", percent_source))

    sequence_zero = _valid_document()
    sequence_zero["sequence"] = "0"
    cases.append(("sequence zero", sequence_zero))

    naive_time = _valid_document()
    naive_time["time"] = "2026-08-21T12:00:00"
    cases.append(("naive time", naive_time))

    nul_id = _valid_document()
    nul_id["id"] = "evt\u0000hidden"
    cases.append(("NUL in id", nul_id))

    for name, document in cases:
        assert list(validator.iter_errors(document)), name
        with pytest.raises(ValidationError):
            validate_event_document(document)
