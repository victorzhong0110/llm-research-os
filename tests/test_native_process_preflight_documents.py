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
    NATIVE_PROCESS_PREFLIGHT_API_VERSION,
    NATIVE_PROCESS_PREFLIGHT_REPORT_SCHEMA_ID,
    NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA_ID,
    NativeProcessPreflightReport,
    TrustedKernel,
    load_native_process_preflight_request,
    load_plan_authorization_request,
    preflight_native_process,
    validate_native_process_preflight_request_document,
)
from llm_research_os.execution.native_preflight_documents import PreflightDigest
from llm_research_os.execution.native_preflight_report_schema import (
    build_schema as build_report_schema,
)
from llm_research_os.execution.native_preflight_report_schema import (
    canonical_schema as canonical_report_schema,
)
from llm_research_os.execution.native_preflight_request_schema import (
    build_schema as build_request_schema,
)
from llm_research_os.execution.native_preflight_request_schema import (
    canonical_schema as canonical_request_schema,
)
from llm_research_os.spec.io import SpecLoadError, load_document, load_spec

PREFLIGHT_DIGEST = TypeAdapter(PreflightDigest)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "native-process-preflight"
SPEC = EXAMPLES / "spec.yaml"
MANIFEST = EXAMPLES / "manifest.yaml"
AUTHORIZATION_REQUEST = EXAMPLES / "authorization-request.json"
PREFLIGHT_REQUEST = EXAMPLES / "preflight-request.json"
REQUEST_SCHEMA = ROOT / "schemas" / "native-process-preflight-request" / "v0alpha1.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "native-process-preflight-report" / "v0alpha1.schema.json"
PROTOCOL = ROOT / "docs" / "protocols" / "native-process-preflight-v0alpha1.md"


def _valid_document() -> dict[str, Any]:
    return load_document(PREFLIGHT_REQUEST)


def _report() -> NativeProcessPreflightReport:
    registry = build_registry([MANIFEST])
    dry_run = TrustedKernel(registry).dry_run(load_spec(SPEC))
    authorization = load_plan_authorization_request(AUTHORIZATION_REQUEST)
    preflight = load_native_process_preflight_request(PREFLIGHT_REQUEST)
    return NativeProcessPreflightReport.from_result(
        preflight_native_process(
            dry_run,
            registry,
            authorization.policy(),
            preflight.policy(),
        )
    )


def test_request_schema_is_closed_strict_bounded_and_versioned() -> None:
    schema = build_request_schema()
    assert schema["$id"] == NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == NATIVE_PROCESS_PREFLIGHT_API_VERSION
    assert schema["properties"]["kind"]["const"] == "NativeProcessPreflightRequest"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "apiVersion",
        "kind",
        "specDigest",
        "registryDigest",
        "planDigest",
        "authorizationDecisionDigest",
        "taskPath",
        "runner",
        "shell",
        "network",
        "workspace",
        "environmentAllowlist",
        "limits",
    }
    assert schema["properties"]["taskPath"]["minItems"] == 1
    assert schema["properties"]["taskPath"]["maxItems"] == 128
    assert schema["properties"]["environmentAllowlist"]["maxItems"] == 0


def test_committed_schemas_are_current_and_valid_draft_2020_12() -> None:
    assert REQUEST_SCHEMA.read_text(encoding="utf-8") == canonical_request_schema()
    assert REPORT_SCHEMA.read_text(encoding="utf-8") == canonical_report_schema()
    assert build_report_schema()["$id"] == NATIVE_PROCESS_PREFLIGHT_REPORT_SCHEMA_ID
    for schema in (build_request_schema(), build_report_schema()):
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)
    report_definitions = build_report_schema()["$defs"]
    report_task_path = report_definitions["NativeProcessTaskIdentity"]["properties"]["taskPath"]
    assert report_task_path["minItems"] == 1
    assert report_task_path["maxItems"] == 128
    report_environment = report_definitions["NativeProcessLaunchConstraints"]["properties"][
        "environmentAllowlist"
    ]
    assert report_environment["maxItems"] == 0


def test_valid_request_round_trips_to_an_isolated_policy() -> None:
    document = _valid_document()
    request = validate_native_process_preflight_request_document(document)
    policy = request.policy()
    assert request.model_dump(mode="json", by_alias=True) == document
    assert policy.task_path == ("workflow", "workflow.native", "invoke")
    assert policy.environment_allowlist == ()
    assert policy.shell is False
    assert policy.limits.wall_time_seconds == 30
    document["taskPath"][2] = "changed"
    document["limits"]["wallTimeSeconds"] = 1
    assert policy.task_path == ("workflow", "workflow.native", "invoke")
    assert policy.limits.wall_time_seconds == 30


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("taskPath", ("workflow", "workflow.native", "invoke")),
        ("taskPath", "workflow/workflow.native/invoke"),
        ("environmentAllowlist", ()),
        ("environmentAllowlist", None),
    ),
)
def test_request_collections_must_be_json_arrays(field: str, value: object) -> None:
    document = _valid_document()
    document[field] = value
    with pytest.raises(ValidationError, match="JSON arrays"):
        validate_native_process_preflight_request_document(document)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("unknown", True),
        lambda value: value.__setitem__("shell", 0),
        lambda value: value.__setitem__("shell", True),
        lambda value: value.__setitem__("network", "unrestricted"),
        lambda value: value.__setitem__("environmentAllowlist", ["PATH"]),
        lambda value: value["limits"].__setitem__("wallTimeSeconds", True),
        lambda value: value["limits"].__setitem__("wallTimeSeconds", 0),
        lambda value: value["limits"].__setitem__("stdoutBytes", 16_777_217),
        lambda value: value["limits"].__setitem__("terminationGraceSeconds", 61),
    ),
)
def test_request_rejects_unknown_coerced_or_unsafe_values(mutate: Any) -> None:
    document = _valid_document()
    mutate(document)
    assert list(Draft202012Validator(build_request_schema()).iter_errors(document))
    with pytest.raises(ValidationError):
        validate_native_process_preflight_request_document(document)


def test_request_loader_rejects_symlinks_duplicate_keys_and_yaml_aliases(
    tmp_path: Path,
) -> None:
    link = tmp_path / "preflight.json"
    link.symlink_to(PREFLIGHT_REQUEST)
    with pytest.raises(SpecLoadError, match="symbolic link"):
        load_native_process_preflight_request(link)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"kind":"NativeProcessPreflightRequest","kind":"changed"}',
        encoding="utf-8",
    )
    with pytest.raises(SpecLoadError, match="duplicate JSON object key"):
        load_native_process_preflight_request(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("task: &task\n  - workflow\ncopy: *task\n", encoding="utf-8")
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_native_process_preflight_request(alias)


def test_report_is_schema_valid_normalized_self_verifying_and_nonlaunchable() -> None:
    report = _report()
    payload = report.model_dump(mode="json", by_alias=True)
    Draft202012Validator(build_report_schema()).validate(payload)
    assert NativeProcessPreflightReport.model_validate(payload) == report
    assert payload["status"] == "reviewable"
    assert payload["launchAllowed"] is False
    assert payload["preflightDigest"] == (
        "jcs-sha256:040f5679d7ac79cf47c805f960e0d5a568812ef6cf5d2e3465314be138f708e5"
    )
    assert payload["task"]["entrypointDigest"].startswith("jcs-sha256:")
    assert "entrypoint" not in payload["task"]
    assert payload["authorizationAuthentication"] == "not-authenticated"
    assert payload["authorizationPersistence"] == "not-persisted"
    assert payload["isolation"] == "not-enforced"
    assert payload["execution"] == "not-executed"
    assert payload["sideEffects"] == {
        "blocksExecuted": 0,
        "entrypointsImported": 0,
        "networkRequests": 0,
        "paidActions": 0,
        "persistentWrites": 0,
        "processesSpawned": 0,
        "signalsSent": 0,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("preflightDigest", "sha256:" + "0" * 64),
        lambda value: value.__setitem__("launchAllowed", True),
        lambda value: value.__setitem__("launchAllowed", 0),
        lambda value: value.__setitem__("isolation", "enforced"),
        lambda value: value.__setitem__("execution", "executed"),
        lambda value: value["binding"].__setitem__("planDigest", "sha256:" + "0" * 64),
        lambda value: value["task"].__setitem__("blockId", "another.block"),
        lambda value: value["task"].__setitem__("entrypointDigest", "sha256:" + "0" * 64),
        lambda value: value["constraints"].__setitem__("shell", True),
        lambda value: value["constraints"].__setitem__("shell", 0),
        lambda value: value["limits"].__setitem__("stdoutBytes", 1),
        lambda value: value["sideEffects"].__setitem__("processesSpawned", 1),
        lambda value: value["sideEffects"].__setitem__("processesSpawned", False),
        lambda value: value.__setitem__("unknown", True),
    ),
)
def test_report_rejects_tampered_claims_or_digest_inputs(mutate: Any) -> None:
    payload = _report().model_dump(mode="json", by_alias=True)
    mutate(payload)
    with pytest.raises(ValidationError):
        NativeProcessPreflightReport.model_validate(payload)


def test_protocol_normative_examples_match_committed_documents() -> None:
    protocol = PROTOCOL.read_text(encoding="utf-8")
    for path in (AUTHORIZATION_REQUEST, PREFLIGHT_REQUEST):
        rendered = json.dumps(load_document(path), ensure_ascii=False, indent=2)
        assert rendered in protocol


def test_report_is_frozen() -> None:
    report = _report()
    with pytest.raises((FrozenInstanceError, ValidationError)):
        report.launch_allowed = True  # type: ignore[misc]


def test_preflight_digest_accepts_new_and_legacy_labels() -> None:
    payload = "a" * 64
    assert PREFLIGHT_DIGEST.validate_python(f"jcs-sha256:{payload}") == f"jcs-sha256:{payload}"
    assert PREFLIGHT_DIGEST.validate_python(f"sha256:{payload}") == f"sha256:{payload}"


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
def test_preflight_digest_rejects_whitespace_case_and_malformed_labels(value: str) -> None:
    with pytest.raises(ValidationError):
        PREFLIGHT_DIGEST.validate_python(value)
