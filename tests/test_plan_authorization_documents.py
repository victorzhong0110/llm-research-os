from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    PLAN_AUTHORIZATION_API_VERSION,
    PLAN_AUTHORIZATION_REPORT_SCHEMA_ID,
    PLAN_AUTHORIZATION_REQUEST_SCHEMA_ID,
    PlanAuthorizationReport,
    PlanAuthorizationStatus,
    TrustedKernel,
    authorize_plan,
    load_plan_authorization_request,
    validate_plan_authorization_request_document,
)
from llm_research_os.execution.authorization_documents import AuthorizationDigest
from llm_research_os.execution.authorization_report_schema import (
    build_schema as build_report_schema,
)
from llm_research_os.execution.authorization_report_schema import (
    canonical_schema as canonical_report_schema,
)
from llm_research_os.execution.authorization_request_schema import (
    build_schema as build_request_schema,
)
from llm_research_os.execution.authorization_request_schema import (
    canonical_schema as canonical_request_schema,
)
from llm_research_os.spec.io import SpecLoadError, load_document, load_spec

AUTHORIZATION_DIGEST = TypeAdapter(AuthorizationDigest)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "plan-authorization-requests"
REQUEST_SCHEMA = ROOT / "schemas" / "plan-authorization-request" / "v0alpha1.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "plan-authorization-report" / "v0alpha1.schema.json"
PROTOCOL = ROOT / "docs" / "protocols" / "plan-authorization-v0alpha1.md"


def _valid_document() -> dict[str, Any]:
    return load_document(EXAMPLES / "valid" / "minimal.json")


def _authorized_report() -> PlanAuthorizationReport:
    request = validate_plan_authorization_request_document(_valid_document())
    dry_run = TrustedKernel(build_registry()).dry_run(
        load_spec(ROOT / "examples" / "valid" / "minimal.yaml")
    )
    return PlanAuthorizationReport.from_result(authorize_plan(dry_run, request.policy()))


def test_request_schema_is_closed_strict_and_versioned() -> None:
    schema = build_request_schema()
    assert schema["$id"] == PLAN_AUTHORIZATION_REQUEST_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == PLAN_AUTHORIZATION_API_VERSION
    assert schema["properties"]["kind"]["const"] == "PlanAuthorizationRequest"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "apiVersion",
        "kind",
        "specDigest",
        "registryDigest",
        "planDigest",
        "grantedCapabilities",
        "grantedPermissions",
        "requirementDecisions",
    }
    assert schema["properties"]["grantedCapabilities"]["uniqueItems"] is True
    assert schema["properties"]["grantedPermissions"]["uniqueItems"] is True
    assert schema["properties"]["requirementDecisions"]["maxItems"] == 10_000


def test_committed_schemas_are_current_and_valid_draft_2020_12() -> None:
    assert REQUEST_SCHEMA.read_text(encoding="utf-8") == canonical_request_schema()
    assert REPORT_SCHEMA.read_text(encoding="utf-8") == canonical_report_schema()
    assert build_report_schema()["$id"] == PLAN_AUTHORIZATION_REPORT_SCHEMA_ID
    for schema in (build_request_schema(), build_report_schema()):
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_valid_request_round_trips_to_an_isolated_policy() -> None:
    document = _valid_document()
    request = validate_plan_authorization_request_document(document)
    policy = request.policy()
    assert request.model_dump(mode="json", by_alias=True) == document
    assert policy.spec_digest == document["specDigest"]
    assert policy.registry_digest == document["registryDigest"]
    assert policy.plan_digest == document["planDigest"]
    assert policy.granted_capabilities == ("simulate",)
    assert policy.granted_permissions == ()
    assert policy.requirement_decisions == ()
    document["grantedCapabilities"][0] = "changed"
    assert policy.granted_capabilities == ("simulate",)


def test_protocol_normative_request_matches_committed_example() -> None:
    rendered = json.dumps(_valid_document(), ensure_ascii=False, indent=2)
    assert rendered in PROTOCOL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name",
    (
        "duplicate-capability.json",
        "invalid-digest.json",
        "python-field-names.json",
        "unknown-field.json",
    ),
)
def test_invalid_examples_are_rejected_by_schema_and_model(name: str) -> None:
    document = load_document(EXAMPLES / "invalid" / name)
    validator = Draft202012Validator(build_request_schema())
    assert list(validator.iter_errors(document)), name
    with pytest.raises(ValidationError):
        validate_plan_authorization_request_document(document)


def test_duplicate_requirement_decision_ids_are_rejected_semantically() -> None:
    document = _valid_document()
    document["requirementDecisions"] = [
        {"requirementId": "approval:/workflow/example/review", "decision": "approved"},
        {"requirementId": "approval:/workflow/example/review", "decision": "denied"},
    ]
    Draft202012Validator(build_request_schema()).validate(document)
    with pytest.raises(ValidationError, match="requirementId entries must be unique"):
        validate_plan_authorization_request_document(document)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("grantedCapabilities", ("simulate",)),
        ("grantedPermissions", "read.private"),
        ("requirementDecisions", None),
    ),
)
def test_request_collections_must_be_json_arrays(field: str, value: object) -> None:
    document = _valid_document()
    document[field] = value
    with pytest.raises(ValidationError, match="JSON arrays"):
        validate_plan_authorization_request_document(document)


def test_request_rejects_coercion_and_whitespace_repair() -> None:
    cases = []
    numeric = _valid_document()
    numeric["grantedCapabilities"] = [1]
    cases.append(numeric)
    whitespace = _valid_document()
    whitespace["grantedCapabilities"] = [" simulate"]
    cases.append(whitespace)
    boolean = _valid_document()
    boolean["requirementDecisions"] = [
        {"requirementId": "approval:/workflow/example/review", "decision": True}
    ]
    cases.append(boolean)
    for document in cases:
        assert list(Draft202012Validator(build_request_schema()).iter_errors(document))
        with pytest.raises(ValidationError):
            validate_plan_authorization_request_document(document)


def test_request_loader_rejects_symlinks_duplicate_keys_and_yaml_aliases(
    tmp_path: Path,
) -> None:
    link = tmp_path / "request.json"
    link.symlink_to(EXAMPLES / "valid" / "minimal.json")
    with pytest.raises(SpecLoadError, match="symbolic link"):
        load_plan_authorization_request(link)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"kind":"PlanAuthorizationRequest","kind":"changed"}',
        encoding="utf-8",
    )
    with pytest.raises(SpecLoadError, match="duplicate JSON object key"):
        load_plan_authorization_request(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("grants: &grants\n  - simulate\ncopy: *grants\n", encoding="utf-8")
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_plan_authorization_request(alias)


def test_authorized_report_is_schema_valid_normalized_and_explicitly_noncredential() -> None:
    report = _authorized_report()
    payload = report.model_dump(mode="json", by_alias=True)
    Draft202012Validator(build_report_schema()).validate(payload)
    assert PlanAuthorizationReport.model_validate(payload) == report
    assert payload["apiVersion"] == PLAN_AUTHORIZATION_API_VERSION
    assert payload["kind"] == "PlanAuthorizationReport"
    assert payload["status"] == "authorized"
    assert payload["authorized"] is True
    assert payload["decisionDigest"] == (
        "jcs-sha256:4d298b128a047cfb6d2498126d1821fca254ed1d482a71f9a538f858c4b8f82c"
    )
    assert payload["approvalAuthentication"] == "not-authenticated"
    assert payload["persistence"] == "not-persisted"
    assert payload["execution"] == "not-executed"
    assert payload["sideEffects"] == {
        "blocksExecuted": 0,
        "networkRequests": 0,
        "paidActions": 0,
        "persistentWrites": 0,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("decisionDigest", "sha256:" + "0" * 64),
        lambda value: value.__setitem__("authorized", False),
        lambda value: value.__setitem__("status", "pending"),
        lambda value: value.__setitem__("approvalAuthentication", "authenticated"),
        lambda value: value["requiredCapabilities"].append("a.capability"),
        lambda value: value.__setitem__("unknown", True),
    ),
)
def test_report_model_rejects_tampered_or_inconsistent_documents(mutate: object) -> None:
    payload = _authorized_report().model_dump(mode="json", by_alias=True)
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        PlanAuthorizationReport.model_validate(payload)


def test_report_is_frozen() -> None:
    report = _authorized_report()
    with pytest.raises((FrozenInstanceError, ValidationError)):
        report.status = PlanAuthorizationStatus.DENIED  # type: ignore[misc]


def test_authorization_digest_accepts_new_and_legacy_labels() -> None:
    payload = "a" * 64
    assert AUTHORIZATION_DIGEST.validate_python(f"jcs-sha256:{payload}") == f"jcs-sha256:{payload}"
    assert AUTHORIZATION_DIGEST.validate_python(f"sha256:{payload}") == f"sha256:{payload}"


@pytest.mark.parametrize(
    "value",
    (
        f"  jcs-sha256:{'a' * 64}  ",
        f"jcs-sha256:{'A' * 64}",
        f"sha256:{'A' * 64}",
        f"SHA256:{'a' * 64}",
        f"jcs-sha256:{'a' * 63}",
        f"sha256:{'a' * 65}",
        f"sha512:{'a' * 64}",
        "sha256:ABC",
        "not-a-digest",
    ),
)
def test_authorization_digest_rejects_whitespace_case_and_malformed_labels(value: str) -> None:
    with pytest.raises(ValidationError):
        AUTHORIZATION_DIGEST.validate_python(value)
