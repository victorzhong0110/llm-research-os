from __future__ import annotations

import importlib
import json
import socket
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

import llm_research_os.cli.authz_commands as cli_module
from llm_research_os.cli import main
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
AUTHORIZATION_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
EVENT_REQUEST = ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json"
QUERY = ROOT / "examples" / "plan-authorization-lineage" / "valid" / "minimal.json"
PLAN_IDENTITY_QUERY = (
    ROOT / "examples" / "plan-authorization-lineage" / "valid" / "plan-identity.json"
)
REPORT_SCHEMA = ROOT / "schemas" / "plan-authorization-lineage-report" / "v0alpha1.schema.json"
ZERO_DIGEST = "sha256:" + "0" * 64


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _database(path: Path) -> Path:
    with EventStore(path):
        pass
    return path


def _record(database: Path) -> int:
    return main(
        [
            "authorizations",
            "record",
            str(SPEC),
            str(AUTHORIZATION_REQUEST),
            str(EVENT_REQUEST),
            str(database),
            "--format",
            "json",
        ]
    )


def _find(
    database: Path,
    query: Path = QUERY,
    *,
    output_format: str = "json",
) -> int:
    return main(
        [
            "authorizations",
            "find",
            str(query),
            str(database),
            "--format",
            output_format,
        ]
    )


def test_find_returns_schema_valid_lineage_report(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _find(database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    report = json.loads(output.out)
    Draft202012Validator(json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))).validate(report)
    assert report["kind"] == "PlanAuthorizationLineageReport"
    assert report["matchCount"] == 1
    assert report["matches"][0]["status"] == "authorized"
    assert report["approvalAuthentication"] == "not-authenticated"
    assert report["authority"] == "audit-only"
    assert report["execution"] == "not-executed"
    assert report["runtimeConsumption"] == "not-consumed"
    assert report["persistence"] == "read-only"
    assert report["sideEffects"] == {
        "blocksExecuted": 0,
        "networkRequests": 0,
        "paidActions": 0,
        "persistentWrites": 0,
    }


def test_text_output_reports_reconstruction_without_claiming_authority(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _find(database, output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "authorization lineage: reconstructed" in output.out
    assert "matches: 1" in output.out
    assert "approval authentication: not-authenticated" in output.out
    assert "event authority: audit-only" in output.out
    assert "execution performed: false" in output.out
    assert "runtime consumption: not-consumed" in output.out


def test_empty_store_is_a_successful_zero_match_reconstruction(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _find(database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    report = json.loads(output.out)
    assert report["matchCount"] == 0
    assert report["matches"] == []
    assert report["highWaterSequence"] == 0


def test_missing_database_is_not_created(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "missing.db"
    assert _find(database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "does not exist" in output.err
    assert not database.exists()


def test_stale_decision_digest_is_an_empty_candidate_set(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = json.loads(QUERY.read_text(encoding="utf-8"))
    document["binding"]["decisionDigest"] = ZERO_DIGEST
    query = _write_json(tmp_path / "stale.json", document)
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _find(database, query) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    report = json.loads(output.out)
    assert report["matchCount"] == 0
    assert report["highWaterSequence"] == 1


def test_plan_identity_query_matches_without_decision_digest(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _find(database, PLAN_IDENTITY_QUERY) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    report = json.loads(output.out)
    assert report["matchCount"] == 1
    assert "decisionDigest" not in report["query"]["binding"]


def test_invalid_or_symlink_query_fails_before_database_open(
    tmp_path: Path,
    capsys: object,
) -> None:
    invalid = json.loads(QUERY.read_text(encoding="utf-8"))
    invalid["projectId"] = "private invalid project value"
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    missing_database = tmp_path / "missing.db"
    assert _find(missing_database, invalid_path) == 2
    invalid_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid_output.out == ""
    assert "private invalid project value" not in invalid_output.err
    assert not missing_database.exists()

    link = tmp_path / "link.json"
    link.symlink_to(QUERY)
    assert _find(missing_database, link) == 2
    link_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert link_output.out == ""
    assert "symbolic link" in link_output.err
    assert not missing_database.exists()


def test_find_command_never_invokes_runtime_process_network_or_artifacts(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path / "events.db")
    assert _record(database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"unexpected side effect: {args!r} {kwargs!r}")

    monkeypatch.setattr(cli_module, "SimulatedRuntime", tripwire, raising=False)
    monkeypatch.setattr(cli_module, "LocalArtifactStore", tripwire, raising=False)
    monkeypatch.setattr(cli_module, "record_plan_authorization_event", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)

    assert _find(database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert json.loads(output.out)["kind"] == "PlanAuthorizationLineageReport"
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 1
