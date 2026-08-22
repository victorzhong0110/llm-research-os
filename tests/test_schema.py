import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from llm_research_os.spec.schema import SCHEMA_DIALECT, SCHEMA_ID, build_schema, schema_matches

SCHEMA = Path(__file__).parents[1] / "schemas" / "research-spec" / "v0alpha1.schema.json"
EXAMPLES = Path(__file__).parents[1] / "examples"


def test_schema_declares_external_contract() -> None:
    schema = build_schema()
    assert schema["$schema"] == SCHEMA_DIALECT
    assert schema["$id"] == SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == "researchos.dev/v0alpha1"
    assert schema["additionalProperties"] is False


def test_committed_schema_is_current() -> None:
    assert schema_matches(SCHEMA)


def test_committed_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_external_schema_accepts_valid_examples() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for path in sorted((EXAMPLES / "valid").glob("*.yaml")):
        validator.validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_external_schema_rejects_unknown_protocol_version() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    document = yaml.safe_load(
        (EXAMPLES / "invalid" / "unknown-api-version.yaml").read_text(encoding="utf-8")
    )
    errors = list(validator.iter_errors(document))
    assert errors
