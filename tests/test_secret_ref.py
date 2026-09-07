from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.secrets import (
    REDACTED,
    SECRET_REF_API_VERSION,
    SecretBackend,
    SecretRef,
    SecretResolutionError,
    message_without_secrets,
    redact_object,
    resolve_secret,
)
from llm_research_os.secrets.schema import SCHEMA_ID, build_schema, schema_matches
from llm_research_os.spec.io import load_document

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "secret-ref" / "v0alpha1.schema.json"
EXAMPLES = ROOT / "examples" / "secret-refs"
PROTOCOL = ROOT / "docs" / "protocols" / "secret-ref-v0alpha1.md"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_secret_ref_schema_declares_closed_external_contract() -> None:
    schema = build_schema()
    assert schema["$id"] == SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == SECRET_REF_API_VERSION
    assert schema["properties"]["kind"]["const"] == "SecretRef"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"apiVersion", "backend", "kind", "name"}


def test_committed_secret_ref_schema_is_current_and_valid() -> None:
    assert schema_matches(SCHEMA)
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_schema_and_model_accept_valid_secret_ref() -> None:
    document = load_document(EXAMPLES / "valid" / "env.json")
    _validator().validate(document)
    ref = SecretRef.model_validate(document)
    assert ref.backend is SecretBackend.ENV
    assert ref.name == "OPENAI_API_KEY"


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_secret_ref_examples(path: Path) -> None:
    document = load_document(path)
    assert list(_validator().iter_errors(document))
    with pytest.raises(ValidationError):
        SecretRef.model_validate(document)


def test_protocol_normative_example_matches_env_secret_ref() -> None:
    example = json.dumps(
        load_document(EXAMPLES / "valid" / "env.json"),
        ensure_ascii=False,
        indent=2,
    )
    protocol = PROTOCOL.read_text(encoding="utf-8")
    assert example in protocol


def test_resolve_env_secret_and_errors_do_not_echo_values() -> None:
    ref = SecretRef.model_validate(load_document(EXAMPLES / "valid" / "env.json"))
    secret = "sk-not-a-real-secret"
    assert resolve_secret(ref, environ={"OPENAI_API_KEY": secret}) == secret
    with pytest.raises(SecretResolutionError, match="secret is not available") as missing:
        resolve_secret(ref, environ={})
    assert secret not in str(missing.value)
    file_ref = SecretRef.model_validate(
        {**load_document(EXAMPLES / "valid" / "env.json"), "backend": "file"}
    )
    with pytest.raises(SecretResolutionError, match="not supported") as unsupported:
        resolve_secret(file_ref, environ={"OPENAI_API_KEY": secret})
    assert secret not in str(unsupported.value)


def test_redaction_strips_secret_keys_and_known_values() -> None:
    secret = "sk-not-a-real-secret"
    payload: dict[str, Any] = {
        "token": secret,
        "nested": {"apiKey": secret, "ok": "visible"},
        "note": f"bearer {secret}",
    }
    redacted = redact_object(payload, secret_values=(secret,))
    assert redacted == {
        "token": REDACTED,
        "nested": {"apiKey": REDACTED, "ok": "visible"},
        "note": f"bearer {REDACTED}",
    }
    assert secret not in json.dumps(redacted)
    assert message_without_secrets(f"failed: {secret}", secret) == f"failed: {REDACTED}"
