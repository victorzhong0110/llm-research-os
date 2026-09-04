import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.runs.models import (
    MAX_ATTEMPTS,
    RUN_SNAPSHOT_API_VERSION,
    RUN_SNAPSHOT_SCHEMA_ID,
    validate_run_snapshot_document,
)
from llm_research_os.runs.schema import (
    SCHEMA_DIALECT,
    SCHEMA_ID,
    _forbid_null_optional_digest,
    build_schema,
    schema_matches,
)
from llm_research_os.spec.io import load_document

SCHEMA = Path(__file__).parents[1] / "schemas" / "run-state" / "v0alpha1.schema.json"
EXAMPLES = Path(__file__).parents[1] / "examples" / "run-state"
PROTOCOL = Path(__file__).parents[1] / "docs" / "protocols" / "run-attempt-state-v0alpha1.md"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _valid_snapshot() -> dict[str, Any]:
    path = EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json"
    return load_document(path)["snapshot"]


def test_run_state_schema_declares_external_contract() -> None:
    schema = build_schema()
    assert schema["$schema"] == SCHEMA_DIALECT
    assert schema["$id"] == SCHEMA_ID == RUN_SNAPSHOT_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == RUN_SNAPSHOT_API_VERSION
    assert schema["properties"]["kind"]["const"] == "RunSnapshot"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["attempts"]["maxItems"] == MAX_ATTEMPTS
    assert schema["properties"]["maxAttempts"]["maximum"] == MAX_ATTEMPTS
    digests = schema["$defs"]["RunDigests"]
    assert set(digests["required"]) == {"plan", "registry", "spec"}
    assert "decisionDigest" not in digests["required"]
    assert digests["properties"]["decisionDigest"]["type"] == "string"
    assert "anyOf" not in digests["properties"]["decisionDigest"]
    assert "consumedAuthorization" not in schema["required"]
    consumed = schema["properties"]["consumedAuthorization"]
    assert consumed == {"$ref": "#/$defs/ConsumedAuthorization"}
    assert "ConsumedAuthorization" in schema["$defs"]


def test_committed_run_state_schema_is_current() -> None:
    assert schema_matches(SCHEMA)


def test_forbid_null_optional_digest_fails_closed_on_unexpected_shape() -> None:
    with pytest.raises(ValueError, match="missing"):
        _forbid_null_optional_digest({}, "RunDigests", "decisionDigest")
    with pytest.raises(ValueError, match="anyOf"):
        _forbid_null_optional_digest(
            {"$defs": {"RunDigests": {"properties": {"decisionDigest": {"type": "string"}}}}},
            "RunDigests",
            "decisionDigest",
        )
    with pytest.raises(ValueError, match="string alternative"):
        _forbid_null_optional_digest(
            {
                "$defs": {
                    "RunDigests": {
                        "properties": {
                            "decisionDigest": {
                                "anyOf": [
                                    {"$ref": "#/$defs/ConsumedAuthorization"},
                                    {"type": "null"},
                                ]
                            }
                        }
                    }
                }
            },
            "RunDigests",
            "decisionDigest",
        )


def test_committed_run_state_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_external_run_state_schema_accepts_valid_snapshots() -> None:
    validator = _validator()
    for path in sorted((EXAMPLES / "valid").glob("*.json")):
        snapshot = load_document(path)["snapshot"]
        validator.validate(snapshot)
        validate_run_snapshot_document(snapshot)


def test_protocol_normative_example_matches_single_attempt_snapshot() -> None:
    snapshot = json.dumps(_valid_snapshot(), ensure_ascii=False, indent=2)
    protocol = PROTOCOL.read_text(encoding="utf-8")
    assert snapshot in protocol


def test_schema_invalid_snapshots_are_rejected_by_the_model() -> None:
    validator = _validator()
    cases: list[tuple[str, dict[str, Any]]] = []

    python_names = _valid_snapshot()
    python_names["project_id"] = python_names.pop("projectId")
    python_names["run_id"] = python_names.pop("runId")
    cases.append(("python field names", python_names))

    unknown = _valid_snapshot()
    unknown["surprise"] = True
    cases.append(("unknown field", unknown))

    boolean_sequence = _valid_snapshot()
    boolean_sequence["lastSequence"] = True
    cases.append(("boolean lastSequence", boolean_sequence))

    trimmed = _valid_snapshot()
    trimmed["runId"] = " run.example"
    cases.append(("trimmed runId", trimmed))

    null_decision = _valid_snapshot()
    null_decision["digests"]["decisionDigest"] = None
    cases.append(("null decisionDigest", null_decision))

    null_citation = _valid_snapshot()
    null_citation["consumedAuthorization"] = None
    cases.append(("null consumedAuthorization", null_citation))

    for name, document in cases:
        assert list(validator.iter_errors(document)), name
        with pytest.raises(ValidationError):
            validate_run_snapshot_document(document)


def test_schema_does_not_encode_cross_field_status_invariants() -> None:
    document = _valid_snapshot()
    document["status"] = "failed"
    _validator().validate(document)
    with pytest.raises(ValidationError):
        validate_run_snapshot_document(document)
