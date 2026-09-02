from __future__ import annotations

import importlib
import json
import socket
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

import llm_research_os.cli as cli_module
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli import main
from llm_research_os.execution import TrustedKernel, authorize_plan
from llm_research_os.execution.authorization_documents import (
    validate_plan_authorization_request_document,
)
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
AUTHORIZATION_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
EVENT_REQUEST = ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json"
EVENT_SCHEMA = ROOT / "schemas" / "research-event" / "v0alpha1.schema.json"
ZERO_DIGEST = "sha256:" + "0" * 64


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _database(path: Path) -> Path:
    with EventStore(path):
        pass
    return path


def _record(
    database: Path,
    *,
    authorization_request: Path = AUTHORIZATION_REQUEST,
    event_request: Path = EVENT_REQUEST,
    output_format: str = "json",
) -> int:
    return main(
        [
            "authorizations",
            "record",
            str(SPEC),
            str(authorization_request),
            str(event_request),
            str(database),
            "--format",
            output_format,
        ]
    )


def test_authorized_record_is_schema_valid_and_replayable(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    event = json.loads(output.out)
    Draft202012Validator(json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))).validate(event)
    assert event["type"] == "plan.authorization.evaluated"
    assert event["sequence"] == "1"
    assert event["data"]["runId"] is None
    assert event["data"]["attemptId"] is None
    assert event["data"]["blockId"] is None
    payload = event["data"]["payload"]
    assert payload["status"] == "authorized"
    assert payload["authorized"] is True
    assert payload["approvalAuthentication"] == "not-authenticated"
    assert payload["authority"] == "audit-only"
    assert payload["execution"] == "not-executed"

    assert main(["events", "replay", str(database)]) == 0
    replay_output = capsys.readouterr()  # type: ignore[attr-defined]
    replayed = [json.loads(line) for line in replay_output.out.splitlines()]
    assert replayed == [event]


def test_text_output_reports_persistence_without_claiming_authority_or_execution(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database, output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "authorization event: recorded" in output.out
    assert "plan authorization: authorized" in output.out
    assert "approval authentication: not-authenticated" in output.out
    assert "event authority: audit-only" in output.out
    assert "execution performed: false" in output.out


def test_denied_evaluation_is_persisted_with_exit_one(
    tmp_path: Path,
    capsys: object,
) -> None:
    authorization_document = load_document(AUTHORIZATION_REQUEST)
    authorization_document["grantedCapabilities"] = []
    authorization_path = _write_json(tmp_path / "denied-authorization.json", authorization_document)
    report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC))
    policy = validate_plan_authorization_request_document(authorization_document).policy()
    result = authorize_plan(report, policy)
    event_document = load_document(EVENT_REQUEST)
    event_document["binding"]["decisionDigest"] = result.decision_digest
    event_document["event"]["id"] = "evt.authorization.denied.cli"
    event_path = _write_json(tmp_path / "denied-event.json", event_document)
    database = _database(tmp_path / "events.db")

    assert (
        _record(
            database,
            authorization_request=authorization_path,
            event_request=event_path,
        )
        == 1
    )
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    event = json.loads(output.out)
    assert event["data"]["payload"]["status"] == "denied"
    assert event["data"]["payload"]["authorized"] is False
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 1


def test_missing_database_is_not_created(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "missing.db"
    assert _record(database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "does not exist" in output.err
    assert not database.exists()


def test_stale_event_binding_fails_without_append(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(EVENT_REQUEST)
    document["binding"]["decisionDigest"] = ZERO_DIGEST
    request = _write_json(tmp_path / "stale.json", document)
    database = _database(tmp_path / "events.db")
    assert _record(database, event_request=request) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "recomputed decision" in output.err
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 0


def test_duplicate_event_identity_fails_without_second_fact(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _record(database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "already exists" in output.err
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 1


def test_invalid_or_symlink_input_fails_before_database_open(
    tmp_path: Path,
    capsys: object,
) -> None:
    invalid = load_document(EVENT_REQUEST)
    invalid["actor"]["id"] = "private invalid actor value"
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    missing_database = tmp_path / "missing.db"
    assert _record(missing_database, event_request=invalid_path) == 2
    invalid_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid_output.out == ""
    assert "private invalid actor value" not in invalid_output.err
    assert not missing_database.exists()

    link = tmp_path / "link.json"
    link.symlink_to(EVENT_REQUEST)
    assert _record(missing_database, event_request=link) == 2
    link_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert link_output.out == ""
    assert "symbolic link" in link_output.err
    assert not missing_database.exists()


def test_record_command_never_invokes_runtime_process_network_or_artifacts(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path / "events.db")

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"unexpected side effect: {args!r} {kwargs!r}")

    monkeypatch.setattr(cli_module, "SimulatedRuntime", tripwire)
    monkeypatch.setattr(cli_module, "LocalArtifactStore", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)

    assert _record(database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert json.loads(output.out)["type"] == "plan.authorization.evaluated"
