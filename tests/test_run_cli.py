from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli import main
from llm_research_os.execution import PlanAuthorizationPolicy, TrustedKernel, authorize_plan
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
REQUEST = ROOT / "examples" / "simulation-requests" / "valid" / "success.json"
AUTHORIZATION_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
EVENT_REQUEST = ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json"
RUN_STATE_SCHEMA = ROOT / "schemas" / "run-state" / "v0alpha1.schema.json"


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _seed_auth(database: Path, spec: Path, tmp_path: Path) -> None:
    with EventStore(database):
        pass
    report = TrustedKernel(build_registry()).dry_run(
        load_spec(spec), workflow_id="workflow.simulation"
    )
    assert report.digests.plan is not None
    result = authorize_plan(
        report,
        PlanAuthorizationPolicy(
            spec_digest=report.digests.spec,
            registry_digest=report.digests.registry,
            plan_digest=report.digests.plan,
            granted_capabilities=("simulate",),
        ),
    )
    auth_document = load_document(AUTHORIZATION_REQUEST)
    auth_document["specDigest"] = result.spec_digest
    auth_document["registryDigest"] = result.registry_digest
    auth_document["planDigest"] = result.plan_digest
    event_document = load_document(EVENT_REQUEST)
    event_document["experimentRevision"] = report.project.revision
    event_document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    auth_path = _write_json(tmp_path / f"{database.name}-authorization.json", auth_document)
    event_path = _write_json(tmp_path / f"{database.name}-event.json", event_document)
    assert (
        main(
            [
                "authorizations",
                "record",
                str(spec),
                str(auth_path),
                str(event_path),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )


def _spec_for(tmp_path: Path, outcome: str) -> Path:
    document = load_document(SPEC)
    document["workflows"][0]["graph"]["nodes"][0]["config"]["outcome"] = outcome
    return _write_json(tmp_path / f"{outcome}-spec.json", document)


def _request_for(tmp_path: Path, outcome: str) -> Path:
    document = load_document(REQUEST)
    events = document["events"]
    if outcome == "failure":
        events.pop("attempt.succeeded")
        events.pop("run.completed")
        events["attempt.failed"] = {
            "id": "evt.5.attempt.failed",
            "time": "2026-08-30T12:00:00Z",
        }
        events["run.failed"] = {
            "id": "evt.6.run.failed",
            "time": "2026-08-30T12:00:00Z",
        }
    elif outcome == "unknown":
        events.pop("attempt.succeeded")
        events.pop("run.completed")
        events["attempt.unknown"] = {
            "id": "evt.5.attempt.unknown",
            "time": "2026-08-30T12:00:00Z",
        }
    return _write_json(tmp_path / f"{outcome}-request.json", document)


def _run(
    spec: Path,
    request: Path,
    database: Path,
    *,
    output_format: str = "json",
) -> int:
    return main(
        [
            "runs",
            "simulate",
            str(spec),
            str(request),
            str(database),
            "--format",
            output_format,
        ]
    )


def test_simulate_command_creates_completed_run_and_emits_run_snapshot(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_auth(database, SPEC, tmp_path)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _run(SPEC, REQUEST, database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    snapshot = json.loads(output.out)
    assert output.err == ""
    assert snapshot["apiVersion"] == "researchos.dev/v0alpha1"
    assert snapshot["kind"] == "RunSnapshot"
    assert snapshot["projectId"] == "example-minimal"
    assert snapshot["runId"] == "run.simulated"
    assert snapshot["workflowId"] == "workflow.simulation"
    assert snapshot["status"] == "completed"
    assert snapshot["lastSequence"] == 7
    assert snapshot["activeAttemptId"] is None
    assert "disposition" not in snapshot
    assert snapshot["consumedAuthorization"] == {
        "eventId": "evt.authorization.example-minimal.1",
        "sequence": 1,
    }
    report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC))
    assert report.digests.plan is not None
    expected_decision = authorize_plan(
        report,
        PlanAuthorizationPolicy(
            spec_digest=report.digests.spec,
            registry_digest=report.digests.registry,
            plan_digest=report.digests.plan,
            granted_capabilities=("simulate",),
        ),
    ).decision_digest
    assert snapshot["digests"]["decisionDigest"] == expected_decision
    Draft202012Validator(json.loads(RUN_STATE_SCHEMA.read_text(encoding="utf-8"))).validate(
        snapshot
    )
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 7
        assert [item.event.type for item in store.read_events(limit=10)] == [
            "plan.authorization.evaluated",
            "run.queued",
            "run.started",
            "attempt.queued",
            "attempt.started",
            "attempt.succeeded",
            "run.completed",
        ]


def test_completed_rerun_is_idempotent_and_text_is_explicit(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_auth(database, SPEC, tmp_path)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _run(SPEC, REQUEST, database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _run(SPEC, REQUEST, database, output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "simulation disposition: completed" in output.out
    assert "status: completed" in output.out
    assert "appended events: 0" in output.out
    assert "scientific conclusion: not evaluated" in output.out
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 7


def test_failure_and_unknown_are_domain_negative_exit_one(
    tmp_path: Path,
    capsys: object,
) -> None:
    for outcome, status, count in (("failure", "failed", 7), ("unknown", "unknown", 6)):
        database = tmp_path / f"{outcome}.db"
        spec = _spec_for(tmp_path, outcome)
        _seed_auth(database, spec, tmp_path)
        capsys.readouterr()  # type: ignore[attr-defined]
        assert (
            _run(
                spec,
                _request_for(tmp_path, outcome),
                database,
            )
            == 1
        )
        output = capsys.readouterr()  # type: ignore[attr-defined]
        snapshot = json.loads(output.out)
        assert output.err == ""
        assert snapshot["status"] == status
        assert snapshot["lastSequence"] == count
        with EventStore(database, create=False) as store:
            assert store.verify_integrity() == count


def test_invalid_request_fails_before_database_creation(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(REQUEST)
    document["events"]["run.queued"]["time"] = "2026-08-30T12:00:00+00:60"
    request = _write_json(tmp_path / "invalid.json", document)
    database = tmp_path / "research.db"
    assert _run(SPEC, request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["kind"] == "ProblemReport"
    assert problem["valid"] is False
    assert not database.exists()


def test_missing_event_identities_are_not_generated(tmp_path: Path, capsys: object) -> None:
    document = load_document(REQUEST)
    document["events"] = {}
    request = _write_json(tmp_path / "empty-events.json", document)
    database = tmp_path / "research.db"
    _seed_auth(database, SPEC, tmp_path)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _run(SPEC, request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["type"] == "SimulationError"
    assert "incomplete" in problem["errors"][0]["message"]
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 1


def test_spec_and_request_symlinks_fail_before_database_creation(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec_link = tmp_path / "spec.yaml"
    spec_link.symlink_to(SPEC)
    request_link = tmp_path / "request.json"
    request_link.symlink_to(REQUEST)
    for spec, request, name in (
        (spec_link, REQUEST, "spec.db"),
        (SPEC, request_link, "request.db"),
    ):
        database = tmp_path / name
        assert _run(spec, request, database) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.out == ""
        assert json.loads(output.err)["kind"] == "ProblemReport"
        assert not database.exists()


def test_corrupt_database_is_problem_report_not_traceback(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    database.write_bytes(b"not sqlite")
    before = database.read_bytes()
    assert _run(SPEC, REQUEST, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["kind"] == "ProblemReport"
    assert problem["errors"][0]["type"] == "EventStoreSchemaError"
    assert database.read_bytes() == before


def test_unexpected_request_field_does_not_echo_value(
    tmp_path: Path,
    capsys: object,
) -> None:
    document: dict[str, Any] = load_document(REQUEST)
    document["secret-field"] = "sk-secret-value"
    request = _write_json(tmp_path / "hostile.json", document)
    database = tmp_path / "research.db"
    assert _run(SPEC, request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "sk-secret-value" not in output.err
    assert not database.exists()


def test_unsupported_plan_problem_type_is_the_stable_reason_code(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(SPEC)
    document["workflows"][0]["graph"]["nodes"].append(
        {
            "kind": "task",
            "id": "second",
            "blockType": "simulated.experiment",
            "blockVersion": "0.1.0",
            "config": {"outcome": "success", "seed": 0},
        }
    )
    spec = _write_json(tmp_path / "two-tasks.json", document)
    database = tmp_path / "research.db"
    assert _run(spec, REQUEST, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["type"] == "nodes-not-single"
    assert "simulated.experiment" in problem["errors"][0]["message"]
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 0


def test_database_integrity_is_preserved_after_cli_run(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _seed_auth(database, SPEC, tmp_path)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert _run(SPEC, REQUEST, database) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    with sqlite3.connect(database, autocommit=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 7
