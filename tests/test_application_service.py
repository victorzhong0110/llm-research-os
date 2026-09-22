"""R02 shared application services: identity, receipts, and existing controls."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from llm_research_os.application import (
    ApplicationCommand,
    ApplicationError,
    ApplicationReceipt,
    ApplicationService,
    init_workspace,
    load_application_command,
)
from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution import (
    PlanAuthorizationPolicy,
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.projections.replay import replay_events
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.requests import load_proposal_submit_request
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore
from llm_research_os.storage.schema import SCHEMA_VERSION

EXAMPLES = Path(__file__).parents[1] / "examples"
ROOT = Path(__file__).parents[1]
COMMAND_EXAMPLES = EXAMPLES / "application-command"
COMMAND_SCHEMA = ROOT / "schemas/application-command/v0alpha1.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas/application-receipt/v0alpha1.schema.json"
PROJECT = "example-minimal"
TIME = "2026-09-22T00:00:00Z"
ACTOR = "researcher.alice"
AUTH_EVENT_ID = "evt.authorization.example-minimal.1"
AUTH_EVENT_REQUEST = EXAMPLES / "plan-authorization-events" / "valid" / "minimal.json"
SIMULATION_REQUEST = EXAMPLES / "m1-checkpoint" / "simulation.json"
PROPOSAL = EXAMPLES / "research-decisions" / "valid" / "proposal-submit.json"


def _command(operation: dict[str, Any], **overrides: Any) -> ApplicationCommand:
    document: dict[str, Any] = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.test.1",
        "actorId": ACTOR,
        "submittedAt": TIME,
        "expectedHead": None,
        "expectedRevision": None,
        "operation": operation,
    }
    document.update(overrides)
    return ApplicationCommand.model_validate(document)


def _workspace(tmp_path: Path, project_id: str = PROJECT) -> Path:
    root = tmp_path / "workspace"
    init_workspace(
        root,
        project_id=project_id,
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )
    return root


def _cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    program = (
        "import sys; from llm_research_os.cli import main; raise SystemExit(main(sys.argv[1:]))"
    )
    return subprocess.run(
        [sys.executable, "-c", program, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _event_digests(database: Path) -> tuple[tuple[str, str], ...]:
    with EventStore(database, require_existing=True) as store:
        assert store.schema_version == SCHEMA_VERSION
        return tuple(
            (stored.event.id, stored.digest)
            for stored in replay_events(store, after_sequence=0, freeze_high_water=True)
        )


def _seed_authorization(database: Path) -> int:
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    registry = build_registry()
    report = TrustedKernel(registry).dry_run(spec, workflow_id="workflow.simulation")
    if report.digests.plan is None:
        raise AssertionError("authorization seed requires a ready plan")
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("simulate",),
    )
    result = authorize_plan(report, policy)
    document = load_document(AUTH_EVENT_REQUEST)
    document["projectId"] = str(report.project.id)
    document["experimentRevision"] = report.project.revision
    document["workflowId"] = str(report.workflow_id)
    document["event"] = {"id": AUTH_EVENT_ID, "time": "2026-09-02T05:00:00Z"}
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    with EventStore(database) as store:
        recorded = record_plan_authorization_event(
            store,
            report,
            policy,
            validate_plan_authorization_event_request_document(document),
        )
        assert recorded.stored.event.id == AUTH_EVENT_ID
        assert recorded.stored.event.sequence == "1"
        return store.last_sequence()


def test_committed_application_schemas_match_examples() -> None:
    command_validator = Draft202012Validator(json.loads(COMMAND_SCHEMA.read_text(encoding="utf-8")))
    receipt_validator = Draft202012Validator(json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(command_validator.schema)
    Draft202012Validator.check_schema(receipt_validator.schema)
    for path in sorted((COMMAND_EXAMPLES / "valid").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["kind"] == "ApplicationCommand":
            command_validator.validate(document)
            ApplicationCommand.model_validate(document)
        else:
            receipt_validator.validate(document)
            ApplicationReceipt.model_validate(document)
    for path in sorted((COMMAND_EXAMPLES / "invalid").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "decision-missing-expected-head.json":
            with pytest.raises(ApplicationError, match="application command failed validation"):
                load_application_command(path)
            continue
        with pytest.raises(JsonSchemaValidationError):
            command_validator.validate(document)
        with pytest.raises(ApplicationError, match="application command failed validation"):
            load_application_command(path)


def test_shared_control_and_worker_roots_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with pytest.raises(ApplicationError, match="must not overlap") as exc_info:
        init_workspace(
            root,
            project_id=PROJECT,
            control_db=Path("control/events.sqlite"),
            cas_root=Path("cas"),
            worker_root=Path("control"),
        )
    assert exc_info.value.code == "shared-root"
    assert not (root / "workspace.json").exists()


def test_cli_and_python_validate_have_identical_semantic_results(tmp_path: Path) -> None:
    python_root = _workspace(tmp_path / "python")
    cli_root = _workspace(tmp_path / "cli")
    command = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.spec.validate.1",
        "actorId": ACTOR,
        "submittedAt": TIME,
        "expectedHead": None,
        "expectedRevision": 1,
        "operation": {
            "kind": "spec.validate",
            "document": str(EXAMPLES / "valid/minimal.yaml"),
        },
    }
    command_path = tmp_path / "command.json"
    command_path.write_text(json.dumps(command), encoding="utf-8")
    python_document = ApplicationService.open(python_root).execute(
        load_application_command(command_path)
    )
    completed = _cli(["app", "execute", "--root", str(cli_root), str(command_path)])
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == python_document
    assert python_document["disposition"] == "committed"
    assert python_document["result"] == {
        "valid": True,
        "projectId": PROJECT,
        "revision": 1,
    }
    assert python_document["resultDigest"] == content_digest(python_document["result"])
    assert python_document["factEventIds"] == []


def test_receipt_survives_restart_and_conflicting_content_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = ApplicationService.open(root)
    command = _command(
        {"kind": "spec.validate", "document": str(EXAMPLES / "valid/minimal.yaml")},
        expectedRevision=1,
        commandId="cmd.restart.1",
    )
    first = service.execute(command)
    reopened = ApplicationService.open(root).execute(command)
    assert reopened["disposition"] == "replayed"
    assert reopened["resultDigest"] == first["resultDigest"]
    assert reopened["requestDigest"] == first["requestDigest"]
    changed = _command(
        {"kind": "spec.validate", "document": str(EXAMPLES / "valid/minimal.yaml")},
        expectedRevision=1,
        commandId="cmd.restart.1",
        submittedAt="2026-09-22T00:00:01Z",
    )
    with pytest.raises(ApplicationError, match="different content") as exc_info:
        ApplicationService.open(root).execute(changed)
    assert exc_info.value.code == "receipt-conflict"


def test_cross_project_spec_and_stale_revision_fail(tmp_path: Path) -> None:
    foreign = ApplicationService.open(_workspace(tmp_path / "foreign", project_id="other-project"))
    command = _command(
        {"kind": "spec.validate", "document": str(EXAMPLES / "valid/minimal.yaml")},
        expectedRevision=1,
    )
    with pytest.raises(ApplicationError, match="does not match the workspace") as mismatch:
        foreign.execute(command)
    assert mismatch.value.code == "project-mismatch"
    assert foreign.workspace.receipt_db.exists() is False or _receipt_count(foreign) == 0
    local = ApplicationService.open(_workspace(tmp_path / "local"))
    stale = _command(
        {"kind": "spec.validate", "document": str(EXAMPLES / "valid/minimal.yaml")},
        expectedRevision=2,
    )
    with pytest.raises(ApplicationError, match="expectedRevision") as revision:
        local.execute(stale)
    assert revision.value.code == "stale-revision"


def test_stale_head_does_not_append_and_schema_v2_digests_stay_put(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    database = root / "control" / "events.sqlite"
    head = _seed_authorization(database)
    before = _event_digests(database)
    service = ApplicationService.open(root)
    command = _command(
        {
            "kind": "run.simulate",
            "spec": str(EXAMPLES / "valid/minimal.yaml"),
            "request": str(SIMULATION_REQUEST),
            "registry": [],
        },
        commandId="cmd.simulate.stale",
        expectedHead=0,
        expectedRevision=1,
    )
    with pytest.raises(ApplicationError, match="expectedHead") as exc_info:
        service.execute(command)
    assert exc_info.value.code == "stale-head"
    assert _event_digests(database) == before
    with EventStore(database, require_existing=True) as store:
        assert store.schema_version == 2
        assert store.last_sequence() == head


def test_repeated_simulation_does_not_create_a_duplicate_run(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    database = root / "control" / "events.sqlite"
    head = _seed_authorization(database)
    before = _event_digests(database)
    service = ApplicationService.open(root)
    command = _command(
        {
            "kind": "run.simulate",
            "spec": str(EXAMPLES / "valid/minimal.yaml"),
            "request": str(SIMULATION_REQUEST),
            "registry": [],
        },
        commandId="cmd.simulate.1",
        expectedHead=head,
        expectedRevision=1,
    )
    first = service.execute(command)
    assert first["disposition"] == "committed"
    assert first["result"]["runId"] == "run.simulated"
    assert first["factEventIds"]
    after_first = _event_digests(database)
    assert before == after_first[: len(before)]
    replayed = ApplicationService.open(root).execute(command)
    assert replayed["disposition"] == "replayed"
    assert replayed["factEventIds"] == first["factEventIds"]
    assert _event_digests(database) == after_first
    second_identity = _command(
        {
            "kind": "run.simulate",
            "spec": str(EXAMPLES / "valid/minimal.yaml"),
            "request": str(SIMULATION_REQUEST),
            "registry": [],
        },
        commandId="cmd.simulate.2",
        expectedHead=_head(database),
        expectedRevision=1,
    )
    second = ApplicationService.open(root).execute(second_identity)
    assert second["result"]["appendedEvents"] == 0
    assert second["result"]["runId"] == "run.simulated"
    digests = _event_digests(database)
    assert digests == after_first
    run_ids = _run_ids(database)
    assert run_ids == {"run.simulated"}


def test_decision_receipt_links_the_fact_and_rejects_a_missing_artifact(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    database = root / "control" / "events.sqlite"
    with EventStore(database) as store:
        proposal = load_proposal_submit_request(PROPOSAL)
        ResearchControl(store, project_id=PROJECT).append(proposal.event_draft())
        head = store.last_sequence()
    before = _event_digests(database)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "DecisionRecordRequest",
                "projectId": PROJECT,
                "experimentRevision": 1,
                "source": "https://researchos.dev/projects/example-minimal",
                "subject": "decision.accept-proposal",
                "streamid": "stream.research",
                "actor": {"id": ACTOR, "kind": "human"},
                "event": {"id": "evt.decision.1", "time": "2026-09-04T12:02:00Z"},
                "decisionId": "decision.accept-proposal",
                "targetKind": "proposal",
                "targetId": "proposal.revise-eval",
                "outcome": "accept",
                "rationale": "The proposal is specific enough to try.",
                "overriddenDissentIds": [],
                "evidenceRefs": [],
            }
        ),
        encoding="utf-8",
    )
    service = ApplicationService.open(root)
    source = tmp_path / "artifact.txt"
    source.write_text("bounded artifact", encoding="utf-8")
    digest = LocalArtifactStore(root / "cas").put(source).digest
    document = json.loads(decision_path.read_text(encoding="utf-8"))
    document["evidenceRefs"] = [digest]
    decision_path.write_text(json.dumps(document), encoding="utf-8")
    missing = decision_path.with_name("missing-artifact.json")
    missing_document = json.loads(decision_path.read_text(encoding="utf-8"))
    missing_document["event"] = {"id": "evt.decision.missing", "time": "2026-09-04T12:03:00Z"}
    missing_document["decisionId"] = "decision.missing-artifact"
    missing_document["evidenceRefs"] = ["sha256:" + ("ab" * 32)]
    missing.write_text(json.dumps(missing_document), encoding="utf-8")
    with pytest.raises(ApplicationError, match="not in the workspace CAS") as missing_info:
        service.execute(
            _command(
                {"kind": "research.decision", "request": str(missing)},
                commandId="cmd.decision.missing",
                expectedHead=head,
                expectedRevision=1,
            )
        )
    assert missing_info.value.code == "artifact-missing"
    assert _event_digests(database) == before
    recorded = service.execute(
        _command(
            {"kind": "research.decision", "request": str(decision_path)},
            commandId="cmd.decision.1",
            expectedHead=head,
            expectedRevision=1,
        )
    )
    assert recorded["factEventIds"] == ["evt.decision.1"]
    assert recorded["result"]["eventId"] == "evt.decision.1"
    assert recorded["artifactDigests"] == [digest]
    after = _event_digests(database)
    assert before == after[: len(before)]
    assert any(event_id == "evt.decision.1" for event_id, _digest in after)
    replayed = service.execute(
        _command(
            {"kind": "research.decision", "request": str(decision_path)},
            commandId="cmd.decision.1",
            expectedHead=head,
            expectedRevision=1,
        )
    )
    assert replayed["disposition"] == "replayed"
    assert _event_digests(database) == after


def test_ledger_run_query_and_revision_list_are_project_scoped(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    database = root / "control" / "events.sqlite"
    head = _seed_authorization(database)
    service = ApplicationService.open(root)
    simulate = _command(
        {
            "kind": "run.simulate",
            "spec": str(EXAMPLES / "valid/minimal.yaml"),
            "request": str(SIMULATION_REQUEST),
            "registry": [],
        },
        commandId="cmd.simulate.read",
        expectedHead=head,
        expectedRevision=1,
    )
    service.execute(simulate)
    observed = _head(database)
    ledger = service.execute(
        _command(
            {"kind": "research.ledger"},
            commandId="cmd.ledger.1",
            expectedHead=observed,
        )
    )
    assert ledger["result"]["projectId"] == PROJECT
    revision_list = service.execute(
        _command(
            {"kind": "revision.list"},
            commandId="cmd.revisions.1",
            expectedHead=observed,
        )
    )
    assert revision_list["result"]["projectId"] == PROJECT
    run_show = service.execute(
        _command(
            {"kind": "run.show", "runId": "run.simulated"},
            commandId="cmd.run.1",
            expectedHead=observed,
        )
    )
    assert run_show["result"]["runId"] == "run.simulated"
    assert run_show["result"]["projectId"] == PROJECT
    with pytest.raises(ApplicationError, match="not in this project") as missing:
        service.execute(
            _command(
                {"kind": "run.show", "runId": "run.missing"},
                commandId="cmd.run.missing",
                expectedHead=observed,
            )
        )
    assert missing.value.code == "run-not-found"
    with pytest.raises(ApplicationError, match="EventStore does not exist") as absent:
        ApplicationService.open(_workspace(tmp_path / "empty")).execute(
            _command(
                {"kind": "research.ledger"},
                commandId="cmd.ledger.missing",
                expectedHead=0,
            )
        )
    assert absent.value.code == "store-missing"


def test_core_import_does_not_load_training_extras() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import llm_research_os.application; "
            "forbidden={'torch','transformers','peft','mlx','unsloth'}; "
            "overlap=sorted(forbidden.intersection(sys.modules)); "
            "raise SystemExit(0 if not overlap else 1)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0


def test_dry_run_and_diff_reuse_existing_controls(tmp_path: Path) -> None:
    service = ApplicationService.open(_workspace(tmp_path))
    spec = EXAMPLES / "valid/minimal.yaml"
    revised = tmp_path / "revised.yaml"
    revised.write_text(
        spec.read_text(encoding="utf-8").replace("revision: 1\n", "revision: 2\n", 1),
        encoding="utf-8",
    )
    diff = service.execute(
        _command(
            {"kind": "spec.diff", "old": str(spec), "new": str(revised)},
            commandId="cmd.diff.1",
            expectedRevision=2,
        )
    )
    assert diff["result"]["fromRevision"] == 1
    assert diff["result"]["toRevision"] == 2
    dry_run = service.execute(
        _command(
            {"kind": "plan.dry-run", "document": str(spec), "workflowId": "workflow.simulation"},
            commandId="cmd.dry-run.1",
            expectedRevision=1,
        )
    )
    assert dry_run["result"]["status"] == "ready"
    assert dry_run["factEventIds"] == []
    described = service.execute(_command({"kind": "workspace.show"}, commandId="cmd.workspace.1"))
    assert described["result"]["projectId"] == PROJECT
    assert described["result"]["supportedEventSchemaVersion"] == SCHEMA_VERSION
    assert described["result"]["controlDb"] == "control/events.sqlite"
    assert "worker" in described["result"]["workerRoot"]


def _receipt_count(service: ApplicationService) -> int:
    if not service.workspace.receipt_db.exists():
        return 0
    import sqlite3

    connection = sqlite3.connect(service.workspace.receipt_db)
    try:
        row = connection.execute("SELECT COUNT(*) FROM operation_receipts").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def _head(database: Path) -> int:
    with EventStore(database, require_existing=True) as store:
        return store.last_sequence()


def _run_ids(database: Path) -> set[str]:
    identities: set[str] = set()
    with EventStore(database, require_existing=True) as store:
        for stored in replay_events(store, after_sequence=0, freeze_high_water=True):
            run_id = stored.event.data.run_id
            if run_id is not None:
                identities.add(run_id)
    return identities
