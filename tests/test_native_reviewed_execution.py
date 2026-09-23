"""R03 reviewed-native contract: schemas, examples, and a non-launching validator."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.execution.errors import NativeReviewedExecutionError
from llm_research_os.execution.native_reviewed import (
    GrantContractCheck,
    PreparedMaterialCitation,
    ReviewedPrefixCitation,
    ReviewedValidationContext,
    observe_host_feasibility,
    parse_native_reviewed_request,
    validate_native_reviewed_execution,
)
from llm_research_os.execution.native_reviewed import (
    execution_object as reviewed_execution_object,
)
from llm_research_os.execution.native_reviewed_documents import (
    EXECUTE_NATIVE_CAPABILITY,
    MAX_REVIEWED_REQUEST_BYTES,
    NATIVE_REVIEWED_MEDIA_TYPE,
    SUPPORTED_REVIEWED_PLATFORMS,
    NativeReviewedExecutionReport,
    NativeReviewedExecutionRequest,
)
from llm_research_os.execution.native_reviewed_schema import (
    native_reviewed_execution_report_schema_matches,
    native_reviewed_execution_request_schema_matches,
)
from llm_research_os.policy.capabilities import (
    KNOWN_PLAN_CAPABILITIES,
    ExecutionCapability,
)
from llm_research_os.workers.binding import EXECUTION_CAPABILITIES, brick_execution_document
from llm_research_os.workers.errors import WorkerCallError

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "native-reviewed-execution"
REQUEST_SCHEMA = ROOT / "schemas" / "native-reviewed-execution-request" / "v0alpha1.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "native-reviewed-execution-report" / "v0alpha1.schema.json"
VALIDATOR_SOURCE = ROOT / "src" / "llm_research_os" / "execution" / "native_reviewed.py"

SEMANTIC_REASONS = {
    "swapped-spec-digest": "spec-digest-mismatch",
    "swapped-registry-digest": "registry-digest-mismatch",
    "swapped-plan-digest": "plan-digest-mismatch",
    "swapped-decision-digest": "decision-digest-mismatch",
    "foreign-project": "foreign-project",
    "stale-revision": "stale-revision",
    "foreign-workflow": "foreign-workflow",
    "foreign-task": "foreign-task",
    "foreign-run": "foreign-run",
    "foreign-attempt": "foreign-attempt",
    "foreign-worker": "foreign-worker",
    "authorization-sequence": "authorization-sequence-mismatch",
    "authorization-actor": "authorization-actor-mismatch",
    "authorization-event": "authorization-event-mismatch",
    "changed-code": "code-digest-mismatch",
    "changed-entrypoint": "entrypoint-mismatch",
    "changed-input": "input-digest-mismatch",
    "changed-config": "config-digest-mismatch",
    "changed-interpreter": "interpreter-digest-mismatch",
    "changed-dependency-lock": "dependency-lock-mismatch",
    "changed-inventory": "inventory-digest-mismatch",
    "changed-python-abi": "environment-identity-mismatch",
    "changed-review": "review-digest-mismatch",
    "required-network": "required-network-unenforced",
    "required-filesystem": "required-filesystem-unenforced",
    "required-memory": "required-memory-unenforced",
    "required-process": "required-process-unenforced",
    "missing-memory-ceiling": "missing-resource-ceiling",
}
SELF_CONSISTENT = {
    "required-network",
    "required-filesystem",
    "required-memory",
    "required-process",
    "missing-memory-ceiling",
}
GRANT_REASONS = {
    "execute-local": "grant-capability-mismatch",
    "process-native": "grant-capability-mismatch",
    "forged-hmac": "grant-hmac-invalid",
    "expired": "grant-expired",
    "revoked": "grant-revoked",
    "nonce-replay": "grant-nonce-replay",
    "resumed-claim": "grant-resumed-claim",
    "consumed-claim": "grant-already-consumed",
    "python-brick-media": "grant-media-mismatch",
    "substituted-image": "grant-binding-mismatch",
    "foreign-run": "grant-binding-mismatch",
}


def _load(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _request(path: Path) -> NativeReviewedExecutionRequest:
    return NativeReviewedExecutionRequest.model_validate(_load(path))


def _context(request: NativeReviewedExecutionRequest) -> ReviewedValidationContext:
    inputs = tuple((item.name, item.digest) for item in request.inputs)
    citation = ReviewedPrefixCitation(
        prefix_verified=True,
        decision_kind="authorization-decision",
        project_id=request.project_id,
        revision_id=request.revision_id,
        workflow_id=request.workflow_id,
        task_id=request.task_id,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
        worker_id=request.worker_id,
        authorization_event_id=request.authorization_event_id,
        authorization_sequence=request.authorization_sequence,
        actor_id=request.actor_id,
        actor_kind="human",
        authorized=True,
        capabilities=frozenset({EXECUTE_NATIVE_CAPABILITY}),
        spec_digest=request.spec_digest,
        registry_digest=request.registry_digest,
        plan_digest=request.plan_digest,
        decision_digest=request.decision_digest,
        review_citation_digest=request.code.review.citation_digest,
        bundle_digest=request.code.bundle_digest,
        media_type=request.code.media_type,
        entrypoint=request.code.entrypoint,
        input_digests=inputs,
        config_digest=request.config_digest,
        interpreter_digest=request.environment.interpreter_digest,
        python_version=request.environment.python_version,
        abi=request.environment.abi,
        dependency_lock_digest=request.environment.dependency_lock_digest,
        inventory_digest=request.environment.inventory_digest,
        platform_os=request.platform.os,
        platform_architecture=request.platform.architecture,
    )
    prepared = PreparedMaterialCitation(
        bundle_digest=request.code.bundle_digest,
        media_type=request.code.media_type,
        entrypoint=request.code.entrypoint,
        input_digests=inputs,
        config_digest=request.config_digest,
        interpreter_digest=request.environment.interpreter_digest,
        python_version=request.environment.python_version,
        abi=request.environment.abi,
        dependency_lock_digest=request.environment.dependency_lock_digest,
        inventory_digest=request.environment.inventory_digest,
        platform_os=request.platform.os,
        platform_architecture=request.platform.architecture,
    )
    return ReviewedValidationContext(citation=citation, prepared=prepared)


def _grant(path: Path) -> GrantContractCheck:
    document = _load(path)
    return GrantContractCheck(
        capability=str(document["capability"]),
        hmac_valid=document["hmacValid"] is True,
        expired=document["expired"] is True,
        revoked=document["revoked"] is True,
        nonce_consumed=document["nonceConsumed"] is True,
        claim_state=document["claimState"],  # type: ignore[arg-type]
        image_digest=str(document["imageDigest"]),
        image_media_type=str(document["imageMediaType"]),
        config_digest=str(document["configDigest"]),
        project_id=str(document["projectId"]),
        run_id=str(document["runId"]),
        task_id=str(document["taskId"]),
        worker_id=str(document["workerId"]),
        attempt_id=str(document["attemptId"]),
    )


def _refuse(request: NativeReviewedExecutionRequest, context: ReviewedValidationContext) -> str:
    report = validate_native_reviewed_execution(request, context)
    assert report.launch_allowed is False
    assert report.accepted_for_preparation is False
    assert report.outcome == "refused"
    assert report.evidence_class == "contract-check"
    assert report.side_effects.entrypoints_imported == 0
    assert report.side_effects.processes_spawned == 0
    assert report.side_effects.lifecycle_facts_appended == 0
    return report.reason_code


def test_generated_schemas_match_models_and_reject_launch() -> None:
    assert native_reviewed_execution_request_schema_matches(REQUEST_SCHEMA)
    assert native_reviewed_execution_report_schema_matches(REPORT_SCHEMA)
    request_schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))
    report_schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(request_schema)
    Draft202012Validator.check_schema(report_schema)
    assert request_schema["additionalProperties"] is False
    assert report_schema["properties"]["launchAllowed"]["const"] is False
    assert report_schema["properties"]["evidenceClass"]["const"] == "contract-check"


def test_valid_examples_are_preparation_only() -> None:
    request_validator = Draft202012Validator(json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8")))
    report_validator = Draft202012Validator(json.loads(REPORT_SCHEMA.read_text(encoding="utf-8")))
    for name in ("linux", "darwin"):
        document = _load(EXAMPLES / "valid" / f"{name}-request.json")
        request_validator.validate(document)
        request = NativeReviewedExecutionRequest.model_validate(document)
        report = validate_native_reviewed_execution(request, _context(request))
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert payload == _load(EXAMPLES / "valid" / f"{name}-report.json")
        report_validator.validate(payload)
        assert report.accepted_for_preparation is True
        assert report.launch_allowed is False
        assert report.reason_code == "launch-not-implemented"
        assert report.restrictions.network.enforced == "not-enforced"
        assert report.restrictions.network.unsupported == "network-isolation"
        assert report.restrictions.filesystem.unsupported == "filesystem-confinement"
        assert report.restrictions.memory.unsupported == "memory-limit"
        assert report.limits.wall_time_seconds.enforced == "not-enforced"
        assert report.limits.memory_bytes.evidence == "declared"
        assert report.limits.process_count.evidence == "missing"


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "invalid" / "schema").glob("*.json")),
    ids=lambda path: path.name,
)
def test_schema_invalid_examples_fail_closed(path: Path) -> None:
    document = _load(path)
    errors = list(
        Draft202012Validator(json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))).iter_errors(
            document
        )
    )
    assert errors
    with pytest.raises(ValidationError):
        NativeReviewedExecutionRequest.model_validate(document)


@pytest.mark.parametrize("name,reason", sorted(SEMANTIC_REASONS.items()))
def test_semantic_examples_refuse_without_launch(name: str, reason: str) -> None:
    request = _request(EXAMPLES / "invalid" / "semantic" / f"{name}.json")
    baseline = _request(EXAMPLES / "valid" / "linux-request.json")
    context = _context(request if name in SELF_CONSISTENT else baseline)
    assert _refuse(request, context) == reason


def test_duplicate_input_name_with_different_digest_is_rejected() -> None:
    document = _load(EXAMPLES / "valid" / "linux-request.json")
    inputs = document["inputs"]
    assert isinstance(inputs, list)
    duplicate = dict(inputs[0])
    duplicate["digest"] = "sha256:" + "ab" * 32
    inputs.append(duplicate)
    with pytest.raises(ValidationError):
        NativeReviewedExecutionRequest.model_validate(document)


def test_inconsistent_config_digest_refuses() -> None:
    document = _load(EXAMPLES / "valid" / "linux-request.json")
    digest = str(document["configDigest"])
    document["configDigest"] = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    request = NativeReviewedExecutionRequest.model_validate(document)
    assert _refuse(request, _context(request)) == "config-digest-mismatch"


def test_prefix_actor_and_decision_failures() -> None:
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    context = _context(request)
    assert _refuse(
        request, replace(context, citation=replace(context.citation, prefix_verified=False))
    ) == ("prefix-unverified")
    assert (
        _refuse(
            request,
            replace(
                context, citation=replace(context.citation, decision_kind="application-receipt")
            ),
        )
        == "decision-not-authorization"
    )
    assert (
        _refuse(
            request,
            replace(context, citation=replace(context.citation, decision_kind="ai-proposal")),
        )
        == "decision-not-authorization"
    )
    assert (
        _refuse(
            request,
            replace(context, citation=replace(context.citation, actor_kind="ai")),
        )
        == "authorization-actor-not-human"
    )
    assert (
        _refuse(
            request,
            replace(context, citation=replace(context.citation, authorized=False)),
        )
        == "authorization-not-authorized"
    )
    assert (
        _refuse(
            request,
            replace(
                context,
                citation=replace(context.citation, capabilities=frozenset({"execute.local"})),
            ),
        )
        == "authorization-capability-mismatch"
    )
    mixed = replace(
        context,
        citation=replace(
            context.citation,
            capabilities=frozenset({"execute.native", "read.local_evidence"}),
        ),
    )
    report = validate_native_reviewed_execution(request, mixed)
    assert report.accepted_for_preparation is True
    assert report.launch_allowed is False


def test_prepared_substitution_refuses_before_launch() -> None:
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    context = _context(request)
    other = "sha256:" + "cd" * 32
    cases = {
        "bundle_digest": "code-digest-mismatch",
        "entrypoint": "entrypoint-mismatch",
        "interpreter_digest": "interpreter-digest-mismatch",
        "dependency_lock_digest": "dependency-lock-mismatch",
        "inventory_digest": "inventory-digest-mismatch",
        "config_digest": "config-digest-mismatch",
        "python_version": "environment-identity-mismatch",
    }
    for field, reason in cases.items():
        value: object = (
            other
            if field.endswith("digest")
            else "3.13.1"
            if field == "python_version"
            else "other.task:main"
        )
        if field == "entrypoint":
            value = "other.task:main"
        prepared = replace(context.prepared, **{field: value})
        assert _refuse(request, replace(context, prepared=prepared)) == reason
    prepared = replace(context.prepared, input_digests=(("corpus", other),))
    assert _refuse(request, replace(context, prepared=prepared)) == "input-digest-mismatch"
    prepared = replace(context.prepared, media_type="researchos.python-brick/v0alpha1")
    assert _refuse(request, replace(context, prepared=prepared)) == "media-type-mismatch"


@pytest.mark.parametrize("name,reason", sorted(GRANT_REASONS.items()))
def test_grant_contract_checks_do_not_launch(name: str, reason: str) -> None:
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    context = replace(
        _context(request),
        grant=_grant(EXAMPLES / "invalid" / "grants" / f"{name}.json"),
    )
    assert _refuse(request, context) == reason


def test_matching_unconsumed_grant_still_cannot_launch() -> None:
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    grant = _grant(EXAMPLES / "grants" / "unconsumed.json")
    report = validate_native_reviewed_execution(request, replace(_context(request), grant=grant))
    assert report.accepted_for_preparation is True
    assert report.launch_allowed is False
    assert report.reason_code == "launch-not-implemented"
    assert grant.claim_state == "unclaimed"
    assert grant.nonce_consumed is False


def test_parser_bounds_and_shapes() -> None:
    raw = (EXAMPLES / "valid" / "linux-request.json").read_bytes()
    assert parse_native_reviewed_request(raw).profile == "native-reviewed-python/v0alpha1"
    with pytest.raises(NativeReviewedExecutionError, match="byte limit") as limited:
        parse_native_reviewed_request(b"{" + b" " * MAX_REVIEWED_REQUEST_BYTES)
    assert limited.value.code == "request-too-large"
    with pytest.raises(NativeReviewedExecutionError, match="not JSON") as invalid:
        parse_native_reviewed_request(b"not-json")
    assert invalid.value.code == "request-invalid"
    with pytest.raises(NativeReviewedExecutionError, match="JSON object") as array:
        parse_native_reviewed_request(b"[]")
    assert array.value.code == "request-invalid"
    with pytest.raises(NativeReviewedExecutionError, match="not a valid") as rejected:
        parse_native_reviewed_request(b'{"apiVersion":"nope"}')
    assert rejected.value.code == "request-invalid"


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"[" * 16000 + b"]" * 16000,
        b'{"apiVersion":"one","apiVersion":"two"}',
        b'{"nested":{"field":1,"field":2}}',
        b'{"number":' + b"9" * 5000 + b"}",
    ],
)
def test_parser_rejects_malformed_documents_with_contract_error(payload: bytes) -> None:
    with pytest.raises(NativeReviewedExecutionError) as error:
        parse_native_reviewed_request(payload)
    assert error.value.code == "request-invalid"


def test_report_cannot_claim_launch_or_side_effects() -> None:
    payload = _load(EXAMPLES / "valid" / "linux-report.json")
    payload["launchAllowed"] = True
    with pytest.raises(ValidationError):
        NativeReviewedExecutionReport.model_validate(payload)
    payload = _load(EXAMPLES / "valid" / "linux-report.json")
    side_effects = payload["sideEffects"]
    assert isinstance(side_effects, dict)
    side_effects["processesSpawned"] = 1
    with pytest.raises(ValidationError):
        NativeReviewedExecutionReport.model_validate(payload)


def test_validator_source_has_no_launch_path(monkeypatch: pytest.MonkeyPatch) -> None:
    source = VALIDATOR_SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "posix_spawn",
        "os.system",
        "importlib",
        "llm_research_os.storage",
    ):
        assert forbidden not in source

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("user code launch")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(importlib, "import_module", boom)
    before = set(sys.modules)
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    report = validate_native_reviewed_execution(request, _context(request))
    assert report.launch_allowed is False
    assert "reviewed.task" not in sys.modules
    assert set(sys.modules) == before


def test_execute_native_is_registered_and_not_honored() -> None:
    assert ExecutionCapability.NATIVE.value == "execute.native"
    assert "execute.native" in KNOWN_PLAN_CAPABILITIES
    assert "execute.native" not in EXECUTION_CAPABILITIES
    assert "execute.local" in EXECUTION_CAPABILITIES
    with pytest.raises(WorkerCallError, match="runtime does not match"):
        brick_execution_document(
            image_digest="sha256:" + "ab" * 32,
            image_media_type=NATIVE_REVIEWED_MEDIA_TYPE,
            runtime="python-sandbox",
        )


def test_host_feasibility_does_not_claim_isolation() -> None:
    host = observe_host_feasibility()
    assert host.profile == "native-reviewed-python/v0alpha1"
    assert host.launch_implemented is False
    assert host.network_enforced is False
    assert host.filesystem_enforced is False
    assert host.memory_enforced is False
    assert host.process_group_enforced is False
    assert host.wall_clock_enforced is False
    assert host.output_bounds_enforced is False
    assert host.system in {"linux", "darwin"}
    assert (host.system, host.architecture) in SUPPORTED_REVIEWED_PLATFORMS
    assert host.supported is True


def test_execution_object_covers_profile_code_inputs_and_limits() -> None:
    request = _request(EXAMPLES / "valid" / "linux-request.json")
    document = reviewed_execution_object(request)
    assert document["profile"] == "native-reviewed-python/v0alpha1"
    assert "code" in document
    assert "inputs" in document
    assert "environment" in document
    assert "limits" in document
    assert "runId" not in document
