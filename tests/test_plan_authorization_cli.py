from __future__ import annotations

import builtins
import importlib
import json
import socket
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

import llm_research_os.cli.authz_commands as cli_module
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli import main
from llm_research_os.execution import TrustedKernel
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec

ROOT = Path(__file__).parents[1]
MINIMAL_SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
MINIMAL_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
BOUNDED_SPEC = ROOT / "examples" / "valid" / "bounded-loop.yaml"
TRAIN_MANIFEST = ROOT / "examples" / "manifests" / "example-train.yaml"
REPORT_SCHEMA = ROOT / "schemas" / "plan-authorization-report" / "v0alpha1.schema.json"


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _request_for(
    spec: ResearchSpec,
    *,
    registry_paths: list[Path] | None = None,
    capabilities: list[str] | None = None,
    permissions: list[str] | None = None,
    decisions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    report = TrustedKernel(build_registry(registry_paths or [])).dry_run(spec)
    assert report.digests.plan is not None
    return {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "PlanAuthorizationRequest",
        "specDigest": report.digests.spec,
        "registryDigest": report.digests.registry,
        "planDigest": report.digests.plan,
        "grantedCapabilities": capabilities or [],
        "grantedPermissions": permissions or [],
        "requirementDecisions": decisions or [],
    }


def _authorize(
    spec: Path,
    request: Path,
    *,
    output_format: str = "json",
    registry: Path | None = None,
) -> int:
    command = ["authorize", str(spec), str(request)]
    if registry is not None:
        command.extend(("--registry", str(registry)))
    command.extend(("--format", output_format))
    return main(command)


def test_authorized_json_report_is_exact_schema_valid_and_nonexecuting(
    capsys: object,
) -> None:
    assert _authorize(MINIMAL_SPEC, MINIMAL_REQUEST) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    report = json.loads(output.out)
    Draft202012Validator(json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))).validate(report)
    assert report["status"] == "authorized"
    assert report["authorized"] is True
    assert report["requiredCapabilities"] == ["simulate"]
    assert report["missingCapabilities"] == []
    assert report["approvalAuthentication"] == "not-authenticated"
    assert report["persistence"] == "not-persisted"
    assert report["execution"] == "not-executed"
    assert report["sideEffects"] == {
        "blocksExecuted": 0,
        "networkRequests": 0,
        "paidActions": 0,
        "persistentWrites": 0,
    }


def test_text_output_never_claims_a_receipt_or_execution(capsys: object) -> None:
    assert _authorize(MINIMAL_SPEC, MINIMAL_REQUEST, output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "plan authorization: authorized" in output.out
    assert "approval authentication: not-authenticated" in output.out
    assert "persistent receipt: false" in output.out
    assert "execution performed: false" in output.out
    assert "side effects: 0 blocks, 0 network requests, 0 writes, 0 paid actions" in output.out


def test_valid_missing_grant_is_domain_denial_with_exit_one(
    tmp_path: Path,
    capsys: object,
) -> None:
    request = load_document(MINIMAL_REQUEST)
    request["grantedCapabilities"] = []
    path = _write_json(tmp_path / "denied.json", request)
    assert _authorize(MINIMAL_SPEC, path) == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    report = json.loads(output.out)
    assert report["status"] == "denied"
    assert report["authorized"] is False
    assert report["missingCapabilities"] == ["simulate"]
    assert report["execution"] == "not-executed"


def test_missing_and_approved_requirements_have_distinct_exit_codes(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(MINIMAL_SPEC)
    document["workflows"][0]["graph"] = {
        "nodes": [
            {
                "kind": "approval",
                "id": "review",
                "requiredRole": "researcher",
                "prompt": "review the exact plan",
            }
        ],
        "edges": [],
    }
    spec = ResearchSpec.model_validate(document)
    spec_path = _write_json(tmp_path / "approval-spec.json", document)
    pending_request = _request_for(spec)
    pending_path = _write_json(tmp_path / "pending.json", pending_request)

    assert _authorize(spec_path, pending_path) == 1
    pending_output = capsys.readouterr()  # type: ignore[attr-defined]
    pending = json.loads(pending_output.out)
    requirement_id = "approval:/workflow/workflow.simulation/review"
    assert pending["status"] == "pending"
    assert pending["pendingRequirements"] == [requirement_id]

    approved_request = {
        **pending_request,
        "requirementDecisions": [{"requirementId": requirement_id, "decision": "approved"}],
    }
    approved_path = _write_json(tmp_path / "approved.json", approved_request)
    assert _authorize(spec_path, approved_path) == 0
    approved_output = capsys.readouterr()  # type: ignore[attr-defined]
    approved = json.loads(approved_output.out)
    assert approved["status"] == "authorized"
    assert approved["approvedRequirements"] == [requirement_id]


def test_registry_loop_plan_can_be_explicitly_authorized(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec = ResearchSpec.model_validate(load_document(BOUNDED_SPEC))
    dry_run = TrustedKernel(build_registry([TRAIN_MANIFEST])).dry_run(spec)
    assert dry_run.plan is not None
    decisions = [
        {"requirementId": item.id, "decision": "approved"}
        for item in dry_run.plan.policy_requirements
    ]
    request = _request_for(
        spec,
        registry_paths=[TRAIN_MANIFEST],
        capabilities=["train.simulated"],
        decisions=decisions,
    )
    request_path = _write_json(tmp_path / "bounded.json", request)
    assert _authorize(BOUNDED_SPEC, request_path, registry=TRAIN_MANIFEST) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    report = json.loads(output.out)
    assert output.err == ""
    assert report["status"] == "authorized"
    assert report["requiredCapabilities"] == ["train.simulated"]
    assert report["pendingRequirements"] == []
    assert len(report["approvedRequirements"]) == 2


def test_stale_binding_and_unknown_grant_are_input_errors_without_echo(
    tmp_path: Path,
    capsys: object,
) -> None:
    stale = load_document(MINIMAL_REQUEST)
    stale["planDigest"] = "sha256:" + "0" * 64
    stale_path = _write_json(tmp_path / "stale.json", stale)
    assert _authorize(MINIMAL_SPEC, stale_path) == 2
    stale_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert stale_output.out == ""
    assert "does not match the plan binding" in stale_output.err

    secret = "private.secret.capability"
    unknown = load_document(MINIMAL_REQUEST)
    unknown["grantedCapabilities"].append(secret)
    unknown_path = _write_json(tmp_path / "unknown.json", unknown)
    assert _authorize(MINIMAL_SPEC, unknown_path) == 2
    unknown_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert unknown_output.out == ""
    assert "unknown capability grant" in unknown_output.err
    assert secret not in unknown_output.err


def test_blocked_plan_is_an_input_error_and_emits_no_authorization_report(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(MINIMAL_SPEC)
    document["workflows"][0]["graph"]["nodes"][0]["blockType"] = "unknown.block"
    spec_path = _write_json(tmp_path / "blocked.json", document)
    assert _authorize(spec_path, MINIMAL_REQUEST) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "complete ready plan" in output.err


def test_invalid_or_symlink_inputs_fail_before_evaluation(
    tmp_path: Path,
    capsys: object,
) -> None:
    invalid = load_document(MINIMAL_REQUEST)
    invalid.pop("planDigest")
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    assert _authorize(MINIMAL_SPEC, invalid_path) == 2
    invalid_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid_output.out == ""
    assert json.loads(invalid_output.err)["kind"] == "ProblemReport"

    request_link = tmp_path / "request-link.json"
    request_link.symlink_to(MINIMAL_REQUEST)
    assert _authorize(MINIMAL_SPEC, request_link) == 2
    request_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert request_output.out == ""
    assert "symbolic link" in request_output.err

    spec_link = tmp_path / "spec-link.yaml"
    spec_link.symlink_to(MINIMAL_SPEC)
    assert _authorize(spec_link, MINIMAL_REQUEST) == 2
    spec_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert spec_output.out == ""
    assert "symbolic link" in spec_output.err


def test_prompt_and_config_values_never_enter_cli_output(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(MINIMAL_SPEC)
    secret_prompt = "secret-approval-body-value"
    document["workflows"][0]["graph"] = {
        "nodes": [
            {
                "kind": "approval",
                "id": "review",
                "requiredRole": "researcher",
                "prompt": secret_prompt,
            }
        ],
        "edges": [],
    }
    spec = ResearchSpec.model_validate(document)
    spec_path = _write_json(tmp_path / "secret-spec.json", document)
    request = _request_for(
        spec,
        decisions=[
            {
                "requirementId": "approval:/workflow/workflow.simulation/review",
                "decision": "approved",
            }
        ],
    )
    request_path = _write_json(tmp_path / "secret-request.json", request)
    assert _authorize(spec_path, request_path) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert secret_prompt not in output.out
    assert secret_prompt not in output.err
    assert "success" not in output.out
    assert "seed" not in output.out


def test_authorize_cli_never_invokes_runtime_network_process_or_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(cli_module, "EventStore", tripwire, raising=False)
    monkeypatch.setattr(cli_module, "LocalArtifactStore", tripwire, raising=False)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(Path, "write_text", tripwire)

    assert _authorize(MINIMAL_SPEC, MINIMAL_REQUEST) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert json.loads(output.out)["status"] == "authorized"
