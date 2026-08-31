from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.artifacts import ArtifactObjectReport, ArtifactRecord
from llm_research_os.artifacts.schema import build_schema, canonical_schema

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "artifact-object-report" / "v0alpha1.schema.json"
DIGEST = "sha256:" + "ab" * 32
STORAGE_KEY = f"objects/sha256/{DIGEST[7:9]}/{DIGEST[9:]}"


def _document() -> dict[str, object]:
    return {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ArtifactObjectReport",
        "operation": "put",
        "digest": DIGEST,
        "sizeBytes": 7,
        "storageKey": STORAGE_KEY,
    }


def test_generated_schema_is_deterministic_current_and_structurally_strict() -> None:
    assert json.loads(canonical_schema()) == build_schema()
    assert SCHEMA.read_text(encoding="utf-8") == canonical_schema()
    schema = build_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/artifact-object-report/v0alpha1.schema.json")
    validator = Draft202012Validator(schema)
    validator.validate(_document())
    for mutate in (
        lambda value: value.__setitem__("unknown", True),
        lambda value: value.__setitem__("operation", "open"),
        lambda value: value.__setitem__("digest", "sha256:ABC"),
        lambda value: value.__setitem__("sizeBytes", -1),
        lambda value: value.__setitem__("storageKey", "../../escape"),
    ):
        document = _document()
        mutate(document)
        assert list(validator.iter_errors(document))


def test_report_semantics_reject_mismatched_storage_key_and_are_frozen() -> None:
    report = ArtifactObjectReport.model_validate(_document())
    assert report.storage_key == STORAGE_KEY
    with pytest.raises(ValidationError, match="storageKey does not match digest"):
        ArtifactObjectReport.model_validate({**_document(), "storageKey": STORAGE_KEY[:-1] + "0"})
    with pytest.raises(ValidationError):
        ArtifactObjectReport.model_validate({**_document(), "sizeBytes": True})
    with pytest.raises((FrozenInstanceError, ValidationError)):
        report.operation = "verify"  # type: ignore[misc]


def test_external_model_and_schema_accept_the_same_strict_field_surface() -> None:
    validator = Draft202012Validator(build_schema())
    invalid_documents = (
        {**_document(), "digest": f" {DIGEST}"},
        {**_document(), "digest": f"{DIGEST} "},
        {
            "api_version": "researchos.dev/v0alpha1",
            "kind": "ArtifactObjectReport",
            "operation": "put",
            "digest": DIGEST,
            "size_bytes": 7,
            "storage_key": STORAGE_KEY,
        },
    )
    for document in invalid_documents:
        assert list(validator.iter_errors(document))
        with pytest.raises(ValidationError):
            ArtifactObjectReport.model_validate(document)


def test_record_conversion_never_includes_source_or_root_paths() -> None:
    report = ArtifactObjectReport.from_record(
        ArtifactRecord(digest=DIGEST, size_bytes=7, storage_key=STORAGE_KEY),
        operation="verify",
    )
    payload = report.model_dump(mode="json", by_alias=True)
    assert payload == {**_document(), "operation": "verify"}
    assert "source" not in payload
    assert "root" not in payload
