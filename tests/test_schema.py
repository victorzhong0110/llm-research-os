import json
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.blocks.registry import build_registry
from llm_research_os.blocks.report_schema import build_schema as build_block_report_schema
from llm_research_os.blocks.report_schema import schema_matches as block_report_schema_matches
from llm_research_os.blocks.reports import BlockRegistryEntry, BlockRegistryReport
from llm_research_os.blocks.schema import build_schema as build_block_schema
from llm_research_os.blocks.schema import schema_matches as block_schema_matches
from llm_research_os.events.models import validate_event_document
from llm_research_os.execution import TrustedKernel
from llm_research_os.execution.schema import build_schema as build_dry_run_schema
from llm_research_os.execution.schema import schema_matches as dry_run_schema_matches
from llm_research_os.problem import ProblemDetail, ProblemReport
from llm_research_os.problem_schema import build_schema as build_problem_schema
from llm_research_os.problem_schema import schema_matches as problem_schema_matches
from llm_research_os.spec.io import load_spec
from llm_research_os.spec.schema import SCHEMA_DIALECT, SCHEMA_ID, build_schema, schema_matches

SCHEMA = Path(__file__).parents[1] / "schemas" / "research-spec" / "v0alpha1.schema.json"
BLOCK_SCHEMA = Path(__file__).parents[1] / "schemas" / "block-manifest" / "v0alpha1.schema.json"
BLOCK_REPORT_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "block-command-report" / "v0alpha1.schema.json"
)
DRY_RUN_SCHEMA = Path(__file__).parents[1] / "schemas" / "dry-run-report" / "v0alpha1.schema.json"
PROBLEM_SCHEMA = Path(__file__).parents[1] / "schemas" / "problem-report" / "v0alpha1.schema.json"
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


def test_block_manifest_schema_is_current_and_valid() -> None:
    assert block_schema_matches(BLOCK_SCHEMA)
    schema = build_block_schema()
    assert schema["$schema"] == SCHEMA_DIALECT
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for path in sorted((EXAMPLES / "manifests").glob("*.yaml")):
        validator.validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_dry_run_report_schema_is_current_and_accepts_ready_report() -> None:
    assert dry_run_schema_matches(DRY_RUN_SCHEMA)
    schema = build_dry_run_schema()
    Draft202012Validator.check_schema(schema)
    report = TrustedKernel(build_registry()).dry_run(load_spec(EXAMPLES / "valid/minimal.yaml"))
    Draft202012Validator(schema).validate(
        report.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_dry_run_report_schema_rejects_inconsistent_status_and_digest_shapes() -> None:
    schema = build_dry_run_schema()
    validator = Draft202012Validator(schema)
    report = TrustedKernel(build_registry()).dry_run(load_spec(EXAMPLES / "valid/minimal.yaml"))
    payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)

    missing_plan = json.loads(json.dumps(payload))
    del missing_plan["plan"]
    del missing_plan["digests"]["plan"]
    assert list(validator.iter_errors(missing_plan))

    blocked_with_plan = json.loads(json.dumps(payload))
    blocked_with_plan["status"] = "blocked"
    blocked_with_plan["summary"]["basis"] = "source"
    blocked_with_plan["diagnostics"] = [
        {"code": "blocked", "severity": "error", "path": "/", "message": "blocked"}
    ]
    assert list(validator.iter_errors(blocked_with_plan))

    invalid_digest = json.loads(json.dumps(payload))
    invalid_digest["digests"]["plan"] = "not-a-digest"
    assert list(validator.iter_errors(invalid_digest))

    blocked = TrustedKernel(build_registry()).dry_run(
        load_spec(EXAMPLES / "valid/bounded-loop.yaml")
    )
    blocked_payload = blocked.model_dump(mode="json", by_alias=True, exclude_none=True)
    blocked_payload["summary"]["stageCount"] = 999
    assert list(validator.iter_errors(blocked_payload))


def test_block_command_report_schema_is_current_valid_and_operation_aware() -> None:
    assert block_report_schema_matches(BLOCK_REPORT_SCHEMA)
    schema = build_block_report_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    registry = build_registry()
    block = registry.blocks()[0]
    listed = BlockRegistryReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="BlockRegistryReport",
        operation="list",
        registryDigest=registry.digest(),
        blocks=(BlockRegistryEntry.model_validate(block.public_summary()),),
    ).public_payload()
    validator.validate(listed)

    list_with_manifest = json.loads(json.dumps(listed))
    list_with_manifest["blocks"][0]["manifest"] = block.manifest.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert list(validator.iter_errors(list_with_manifest))

    shown = BlockRegistryReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="BlockRegistryReport",
        operation="show",
        registryDigest=registry.digest(),
        blocks=(BlockRegistryEntry.model_validate(block.public_detail()),),
    ).public_payload()
    validator.validate(shown)
    del shown["blocks"][0]["manifest"]
    assert list(validator.iter_errors(shown))


def test_problem_report_schema_is_current_valid_and_accepts_diagnostics() -> None:
    assert problem_schema_matches(PROBLEM_SCHEMA)
    schema = build_problem_schema()
    Draft202012Validator.check_schema(schema)
    report = ProblemReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="ProblemReport",
        valid=False,
        errors=(ProblemDetail(path="/document", message="invalid", type="invalid"),),
    )
    Draft202012Validator(schema).validate(
        report.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        ProblemDetail(path="/invalid~2escape", message="invalid", type="invalid")


def _valid_spec_paths() -> list[Path]:
    return sorted((EXAMPLES / "valid").glob("*.yaml"))


def _valid_event_paths() -> list[Path]:
    return sorted((EXAMPLES / "events" / "valid").glob("*.json"))


@given(st.sampled_from(_valid_spec_paths()))
@settings(max_examples=max(1, len(_valid_spec_paths())), deadline=200)
def test_valid_specs_round_trip_through_pydantic(path: Path) -> None:
    spec = load_spec(path)
    dumped = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert type(spec).model_validate(dumped) == spec


@given(st.sampled_from(_valid_event_paths()))
@settings(max_examples=max(1, len(_valid_event_paths())), deadline=200)
def test_valid_events_round_trip_through_pydantic(path: Path) -> None:
    event = validate_event_document(json.loads(path.read_text(encoding="utf-8")))
    dumped = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert validate_event_document(dumped) == event
