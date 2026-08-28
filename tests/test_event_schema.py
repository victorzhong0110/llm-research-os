import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.events.schema import SCHEMA_DIALECT, SCHEMA_ID, build_schema, schema_matches
from llm_research_os.spec.io import load_document

SCHEMA = Path(__file__).parents[1] / "schemas" / "research-event" / "v0alpha1.schema.json"
EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


def test_event_schema_declares_external_contract() -> None:
    schema = build_schema()
    assert schema["$schema"] == SCHEMA_DIALECT
    assert schema["$id"] == SCHEMA_ID
    assert schema["properties"]["specversion"]["const"] == "1.0"
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
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for path in sorted((EXAMPLES / "valid").glob("*.json")):
        validator.validate(load_document(path))


def test_external_event_schema_rejects_unknown_specversion() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    document = load_document(EXAMPLES / "invalid" / "unknown-specversion.json")
    errors = list(validator.iter_errors(document))
    assert errors


def test_external_event_schema_rejects_unknown_envelope_field() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    document = load_document(EXAMPLES / "invalid" / "unknown-envelope-field.json")
    errors = list(validator.iter_errors(document))
    assert errors


def test_duplicate_evidence_refs_fail_json_schema() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    document = load_document(EXAMPLES / "invalid" / "duplicate-evidence-refs.json")
    errors = list(validator.iter_errors(document))
    assert errors


def test_semantic_event_rules_are_enforced_beyond_json_schema() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    embedded = load_document(EXAMPLES / "invalid" / "embedded-inline-content.json")
    validator.validate(embedded)
    with pytest.raises(ValidationError, match="must not embed file bytes or document bodies"):
        from llm_research_os.events.models import ResearchEvent

        ResearchEvent.model_validate(embedded)
