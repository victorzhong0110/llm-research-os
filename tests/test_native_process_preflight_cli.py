from __future__ import annotations

import builtins
import importlib
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

import llm_research_os.cli as cli_module
from llm_research_os.cli import main
from llm_research_os.spec.io import load_document

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "native-process-preflight"
SPEC = EXAMPLES / "spec.yaml"
MANIFEST = EXAMPLES / "manifest.yaml"
AUTHORIZATION_REQUEST = EXAMPLES / "authorization-request.json"
PREFLIGHT_REQUEST = EXAMPLES / "preflight-request.json"
REPORT_SCHEMA = ROOT / "schemas" / "native-process-preflight-report" / "v0alpha1.schema.json"


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _preflight(
    authorization_request: Path = AUTHORIZATION_REQUEST,
    preflight_request: Path = PREFLIGHT_REQUEST,
    *,
    spec: Path = SPEC,
    manifest: Path = MANIFEST,
    output_format: str = "json",
) -> int:
    return main(
        [
            "native",
            "preflight",
            str(spec),
            str(authorization_request),
            str(preflight_request),
            "--registry",
            str(manifest),
            "--format",
            output_format,
        ]
    )


def test_json_report_is_exact_schema_valid_and_explicitly_nonlaunchable(
    capsys: object,
) -> None:
    assert _preflight() == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    report = json.loads(output.out)
    Draft202012Validator(json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))).validate(report)
    assert report["status"] == "reviewable"
    assert report["launchAllowed"] is False
    assert report["isolation"] == "not-enforced"
    assert report["execution"] == "not-executed"
    assert report["sideEffects"]["processesSpawned"] == 0
    assert "example_native_worker:run" not in output.out


def test_text_output_never_claims_isolation_authority_or_execution(capsys: object) -> None:
    assert _preflight(output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "native process preflight: reviewable" in output.out
    assert "launch allowed: false" in output.out
    assert "authorization authentication: not-authenticated" in output.out
    assert "authorization persistence: not-persisted" in output.out
    assert "process isolation enforced: false" in output.out
    assert "execution performed: false" in output.out
    assert "0 processes" in output.out
    assert "example_native_worker:run" not in output.out


def test_stale_preflight_binding_is_input_error_without_report(
    tmp_path: Path,
    capsys: object,
) -> None:
    request = load_document(PREFLIGHT_REQUEST)
    request["planDigest"] = "sha256:" + "0" * 64
    path = _write_json(tmp_path / "stale.json", request)
    assert _preflight(preflight_request=path) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "authorization binding" in output.err
    assert "NativeProcessPreflightReport" not in output.err


def test_denied_or_unknown_authorization_fails_closed_without_echo(
    tmp_path: Path,
    capsys: object,
) -> None:
    denied = load_document(AUTHORIZATION_REQUEST)
    denied["grantedCapabilities"] = []
    denied_path = _write_json(tmp_path / "denied.json", denied)
    assert _preflight(authorization_request=denied_path) == 2
    denied_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert denied_output.out == ""
    assert "authorized exact plan" in denied_output.err

    secret = "private.unexpected.capability"
    unknown = load_document(AUTHORIZATION_REQUEST)
    unknown["grantedCapabilities"].append(secret)
    unknown_path = _write_json(tmp_path / "unknown.json", unknown)
    assert _preflight(authorization_request=unknown_path) == 2
    unknown_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert unknown_output.out == ""
    assert "authorization failed" in unknown_output.err
    assert secret not in unknown_output.err


def test_invalid_and_symlink_inputs_fail_before_preflight(
    tmp_path: Path,
    capsys: object,
) -> None:
    invalid = load_document(PREFLIGHT_REQUEST)
    invalid["shell"] = True
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    assert _preflight(preflight_request=invalid_path) == 2
    invalid_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid_output.out == ""
    assert json.loads(invalid_output.err)["kind"] == "ProblemReport"

    for name, target, argument in (
        ("spec-link.yaml", SPEC, "spec"),
        ("authorization-link.json", AUTHORIZATION_REQUEST, "authorization"),
        ("preflight-link.json", PREFLIGHT_REQUEST, "preflight"),
    ):
        link = tmp_path / name
        link.symlink_to(target)
        kwargs = {argument: link}
        if argument == "authorization":
            result = _preflight(authorization_request=link)
        elif argument == "preflight":
            result = _preflight(preflight_request=link)
        else:
            result = _preflight(spec=link)
        assert result == 2, kwargs
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.out == ""
        assert "symbolic link" in output.err


def test_cli_never_imports_spawns_signals_networks_or_persists(
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(cli_module, "EventStore", tripwire)
    monkeypatch.setattr(cli_module, "LocalArtifactStore", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    monkeypatch.setattr(os, "system", tripwire)
    monkeypatch.setattr(os, "kill", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(Path, "write_text", tripwire)

    assert _preflight() == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert json.loads(output.out)["launchAllowed"] is False
