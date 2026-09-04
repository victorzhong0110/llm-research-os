from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    SimulatedRuntime,
    SimulationError,
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.simulated import (
    SUCCESS_PATH,
    SimulationEventIdentity,
    SimulationRequest,
)
from llm_research_os.runs import RunControl
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore
from llm_research_os.storage.models import StoredEvent

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
SPEC = EXAMPLES / "valid" / "minimal.yaml"
EVENT_REQUEST = EXAMPLES / "plan-authorization-events" / "valid" / "minimal.json"
PROJECT = "example-minimal"
RUN = "run.simulated"
WORKFLOW = "workflow.simulation"
TIME = "2026-08-30T12:00:00Z"
SOURCE = "https://researchos.dev/projects/example-minimal"
SCHEMA = "https://researchos.dev/schemas/research-event/v0alpha1.schema.json"


def _simulation_request(*, event_id: str, sequence: str) -> SimulationRequest:
    return SimulationRequest(
        workflow_id=WORKFLOW,
        attempt_id="attempt.1",
        source=SOURCE,
        subject=RUN,
        stream_id="stream.simulated",
        actor_id="researcher.alice",
        authorization_event_id=event_id,
        authorization_sequence=sequence,
        events={
            event_type: SimulationEventIdentity(id=f"evt.{index}.{event_type}", time=TIME)
            for index, event_type in enumerate(SUCCESS_PATH, start=1)
        },
    )


def _record_authorization(
    store: EventStore,
    *,
    event_id: str = "evt.authorization.consume",
    granted: tuple[str, ...] = ("simulate",),
) -> tuple[StoredEvent, PlanAuthorizationResult]:
    spec = load_spec(SPEC)
    report = TrustedKernel(build_registry()).dry_run(spec, workflow_id=WORKFLOW)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=granted,
    )
    result = authorize_plan(report, policy)
    document = load_document(EVENT_REQUEST)
    document["event"] = {"id": event_id, "time": "2026-09-02T05:00:00Z"}
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    recorded = record_plan_authorization_event(
        store,
        report,
        policy,
        validate_plan_authorization_event_request_document(document),
    )
    return recorded.stored, result


def _draft_from(stored: StoredEvent, *, event_id: str) -> dict[str, Any]:
    draft = stored.event.model_dump(mode="json", by_alias=True, exclude_none=True)
    for key in ("sequence", "sequencetype", "streamversion"):
        draft.pop(key, None)
    draft["id"] = event_id
    return draft


def test_simulated_runtime_consumes_local_authorization_citation(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, _result = _record_authorization(store)
        result = SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
            load_spec(SPEC),
            _simulation_request(event_id=stored.event.id, sequence=stored.event.sequence),
        )
        assert result.snapshot.consumed_authorization is not None
        assert result.snapshot.consumed_authorization.event_id == stored.event.id
        assert result.snapshot.consumed_authorization.sequence == stored.sequence
        assert result.stored[0].event.data.payload["authorizationEventId"] == stored.event.id


def test_missing_authorization_event_writes_nothing(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(SimulationError, match="not found") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id="evt.missing", sequence="1"),
            )
        assert info.value.code == "authorization-event-not-found"
        assert store.last_sequence() == 0


def test_sequence_swap_writes_nothing(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        first, _result = _record_authorization(store, event_id="evt.authorization.first")
        second, _ignored = _record_authorization(store, event_id="evt.authorization.second")
        with pytest.raises(SimulationError, match="sequence") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=first.event.id, sequence=second.event.sequence),
            )
        assert info.value.code == "authorization-sequence-mismatch"
        assert store.last_sequence() == 2


def test_denied_authorization_cannot_start_a_run(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, result = _record_authorization(store, granted=())
        assert result.authorized is False
        with pytest.raises(SimulationError, match="not an authorized") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=stored.event.id, sequence=stored.event.sequence),
            )
        assert info.value.code == "authorization-not-authorized"
        assert store.last_sequence() == 1


def test_non_human_actor_cannot_start_a_run(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, _result = _record_authorization(store)
        draft = _draft_from(stored, event_id="evt.authorization.system")
        draft["data"]["actor"]["kind"] = "system"
        appended = store.append(draft)
        with pytest.raises(SimulationError, match="not a local human") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=appended.event.id, sequence=appended.event.sequence),
            )
        assert info.value.code == "authorization-actor-not-human"
        assert store.last_sequence() == 2


def test_binding_mismatch_writes_nothing(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, _result = _record_authorization(store)
        failure = load_document(SPEC)
        failure["workflows"][0]["graph"]["nodes"][0]["config"]["outcome"] = "failure"
        with pytest.raises(SimulationError, match="in-process gate") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                failure,
                _simulation_request(event_id=stored.event.id, sequence=stored.event.sequence),
            )
        assert info.value.code == "authorization-binding-mismatch"
        assert store.last_sequence() == 1


def test_project_mismatch_writes_nothing(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, _result = _record_authorization(store)
        draft = _draft_from(stored, event_id="evt.authorization.other-project")
        draft["data"]["projectId"] = "project.foreign"
        appended = store.append(draft)
        with pytest.raises(SimulationError, match="project revision") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=appended.event.id, sequence=appended.event.sequence),
            )
        assert info.value.code == "authorization-project-mismatch"
        assert store.last_sequence() == 2


def test_wrong_type_is_not_consumed(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        store.append(
            {
                "specversion": "1.0",
                "id": "evt.not-authorization",
                "source": SOURCE,
                "type": "run.queued",
                "time": TIME,
                "subject": RUN,
                "dataschema": SCHEMA,
                "datacontenttype": "application/json",
                "streamid": "stream.foreign",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice", "kind": "human"},
                    "projectId": PROJECT,
                    "experimentRevision": 1,
                    "payload": {
                        "workflowId": WORKFLOW,
                        "specDigest": "sha256:" + "11" * 32,
                        "registryDigest": "sha256:" + "22" * 32,
                        "planDigest": "sha256:" + "33" * 32,
                        "maxAttempts": 1,
                    },
                    "evidenceRefs": [],
                    "runId": "run.foreign",
                },
            }
        )
        with pytest.raises(SimulationError, match="type") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id="evt.not-authorization", sequence="1"),
            )
        assert info.value.code == "authorization-type-mismatch"
        assert store.last_sequence() == 1


def test_legacy_snapshot_without_citation_fails_closed(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        stored, result = _record_authorization(store)
        report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC), workflow_id=WORKFLOW)
        assert report.digests.plan is not None
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            {
                "specversion": "1.0",
                "id": "evt.legacy.run.queued",
                "source": SOURCE,
                "type": "run.queued",
                "time": TIME,
                "subject": RUN,
                "dataschema": SCHEMA,
                "datacontenttype": "application/json",
                "streamid": "stream.simulated",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice"},
                    "projectId": PROJECT,
                    "experimentRevision": 1,
                    "payload": {
                        "workflowId": WORKFLOW,
                        "specDigest": report.digests.spec,
                        "registryDigest": report.digests.registry,
                        "planDigest": report.digests.plan,
                        "decisionDigest": result.decision_digest,
                        "maxAttempts": 1,
                    },
                    "evidenceRefs": [],
                    "runId": RUN,
                },
            }
        )
        with pytest.raises(SimulationError, match="existing run does not match") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=stored.event.id, sequence=stored.event.sequence),
            )
        assert info.value.code == "authorization-citation-missing"
        assert store.last_sequence() == 2


def test_resume_rejects_a_different_authorization_event(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.db") as store:
        first, _result = _record_authorization(store, event_id="evt.authorization.first")
        SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
            load_spec(SPEC),
            _simulation_request(event_id=first.event.id, sequence=first.event.sequence),
        )
        second, _ignored = _record_authorization(store, event_id="evt.authorization.second")
        with pytest.raises(SimulationError, match="existing run does not match") as info:
            SimulatedRuntime(store, build_registry(), project_id=PROJECT, run_id=RUN).run(
                load_spec(SPEC),
                _simulation_request(event_id=second.event.id, sequence=second.event.sequence),
            )
        assert info.value.code == "authorization-event-id-mismatch"
        assert store.last_sequence() == 8
