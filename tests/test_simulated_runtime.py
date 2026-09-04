from __future__ import annotations

import builtins
import importlib
import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any, NoReturn

import pytest

from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.execution import (
    PlanAuthorizationError,
    PlanAuthorizationPolicy,
    SimulatedRuntime,
    SimulationDisposition,
    SimulationError,
    SimulationEventIdentity,
    SimulationRequest,
    TrustedKernel,
    authorize_plan,
)
from llm_research_os.execution.simulated import FAILURE_PATH, SUCCESS_PATH, UNKNOWN_PATH
from llm_research_os.execution.synthetic import (
    TYPE_EVALUATION_METRIC,
    TYPE_TRAINING_STEP,
    parse_evaluation_metric_payload,
    parse_training_step_payload,
    synthetic_evaluation_payload,
    synthetic_training_payload,
)
from llm_research_os.projections import fold_events, replay_events
from llm_research_os.runs import AttemptStatus, RunControl, RunStateProjection, RunStatus
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import (
    DuplicateEventError,
    EventIntegrityError,
    EventSequenceConflictError,
    EventStore,
)
from llm_research_os.storage.schema import MIGRATION_STATEMENTS

EXAMPLES = Path(__file__).parents[1] / "examples"
PROJECT = "example-minimal"
RUN = "run.simulated"
WORKFLOW = "workflow.simulation"
ATTEMPT = "attempt.1"
TIME = "2026-08-30T12:00:00Z"
SOURCE = "https://researchos.dev/projects/example-minimal"
HOSTILE_KEY = "\x1b[31msecret-field\nnext-line"


class _Stopped(RuntimeError):
    """Interrupt a simulation after a legal prefix without translating the error."""


def _identities(
    path: tuple[str, ...], *, prefix: str = "evt"
) -> dict[str, SimulationEventIdentity]:
    return {
        event_type: SimulationEventIdentity(id=f"{prefix}.{index}.{event_type}", time=TIME)
        for index, event_type in enumerate(path, start=1)
    }


def _request(
    path: tuple[str, ...] = SUCCESS_PATH,
    *,
    prefix: str = "evt",
    attempt_id: str = ATTEMPT,
    workflow_id: str = WORKFLOW,
    stream_id: str = "stream.simulated",
    extra_events: dict[str, SimulationEventIdentity] | None = None,
) -> SimulationRequest:
    events = _identities(path, prefix=prefix)
    if extra_events:
        events.update(extra_events)
    return SimulationRequest(
        workflow_id=workflow_id,
        attempt_id=attempt_id,
        source=SOURCE,
        subject=RUN,
        stream_id=stream_id,
        actor_id="researcher.alice",
        events=events,
    )


def _cancel_identities() -> dict[str, SimulationEventIdentity]:
    return {
        "attempt.cancelled": SimulationEventIdentity(id="evt.cancel.attempt.cancelled", time=TIME),
        "run.cancelled": SimulationEventIdentity(id="evt.cancel.run.cancelled", time=TIME),
    }


def _spec_document(*, outcome: object | None = "success") -> dict[str, Any]:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    config = document["workflows"][0]["graph"]["nodes"][0].setdefault("config", {})
    if outcome is None:
        config.pop("outcome", None)
    else:
        config["outcome"] = outcome
    return document


def _runtime(store: EventStore, registry: BlockRegistry | None = None) -> SimulatedRuntime:
    return SimulatedRuntime(
        store,
        registry or build_registry(),
        project_id=PROJECT,
        run_id=RUN,
    )


def _replay(store: EventStore) -> object:
    projection = RunStateProjection(project_id=PROJECT, run_id=RUN)
    return fold_events((item.event for item in replay_events(store)), projection)


def _assert_unchanged(store: EventStore, expected_head: int) -> None:
    assert store.last_sequence() == expected_head
    assert store.verify_integrity() == expected_head


def _assert_error_hides_secrets(error: BaseException, *forbidden: str) -> None:
    rendered = "".join(str(part) for part in (str(error), *error.args, repr(error)))
    for item in forbidden:
        assert item not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def _trigger_statement(name: str) -> str:
    marker = f"CREATE TRIGGER {name}"
    return next(statement for statement in MIGRATION_STATEMENTS if marker in statement)


def _foreign_draft(event_id: str, *, streamid: str = "stream.foreign") -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": SOURCE,
        "type": "run.queued",
        "time": TIME,
        "subject": "run.foreign",
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "streamid": streamid,
        "data": {
            "schemaVersion": "v0alpha1",
            "actor": {"id": "researcher.alice"},
            "projectId": "project.foreign",
            "experimentRevision": 1,
            "payload": {
                "workflowId": "workflow.foreign",
                "specDigest": "sha256:" + "11" * 32,
                "registryDigest": "sha256:" + "22" * 32,
                "planDigest": "sha256:" + "33" * 32,
                "maxAttempts": 1,
            },
            "evidenceRefs": [],
            "runId": "run.foreign",
        },
    }


def _lifecycle_draft(
    event_type: str,
    event_id: str,
    *,
    payload: dict[str, Any],
    attempt_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": "researcher.alice"},
        "projectId": PROJECT,
        "experimentRevision": 1,
        "payload": payload,
        "evidenceRefs": [],
        "runId": RUN,
    }
    if attempt_id is not None:
        data["attemptId"] = attempt_id
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": SOURCE,
        "type": event_type,
        "time": TIME,
        "subject": RUN,
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "streamid": "stream.simulated",
        "data": data,
    }


def _limit_appends(store: EventStore, limit: int) -> None:
    original = store.append
    count = {"value": 0}

    def limited(
        document: dict[str, Any],
        *,
        expected_last_sequence: int | None = None,
    ) -> object:
        if count["value"] >= limit:
            raise _Stopped()
        stored = original(document, expected_last_sequence=expected_last_sequence)
        count["value"] += 1
        return stored

    store.append = limited  # type: ignore[method-assign]


def _t0_decision_digest(report: Any) -> str:
    plan = report.digests.plan
    assert plan is not None
    return authorize_plan(
        report,
        PlanAuthorizationPolicy(
            spec_digest=report.digests.spec,
            registry_digest=report.digests.registry,
            plan_digest=plan,
            granted_capabilities=("simulate",),
        ),
    ).decision_digest


def test_success_path_emits_six_events_and_matches_replay(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    registry = build_registry()
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    report = TrustedKernel(registry).dry_run(spec, workflow_id=WORKFLOW)
    with EventStore(database) as store:
        result = _runtime(store, registry).run(spec, _request())
        types = [item.event.type for item in result.stored]
        assert types == list(SUCCESS_PATH)
        assert result.disposition is SimulationDisposition.COMPLETED
        assert result.snapshot.status is RunStatus.COMPLETED
        assert result.snapshot == _replay(store)
        assert result.snapshot.max_attempts == 1
        assert result.report.digests.spec == report.digests.spec
        assert result.stored[0].event.data.payload == {
            "workflowId": WORKFLOW,
            "specDigest": report.digests.spec,
            "registryDigest": report.digests.registry,
            "planDigest": report.digests.plan,
            "decisionDigest": _t0_decision_digest(report),
            "maxAttempts": 1,
        }
        assert result.snapshot.digests.decision_digest == _t0_decision_digest(report)
        sequences = [item.sequence for item in result.stored]
        assert sequences == [1, 2, 3, 4, 5, 6]


def test_failure_path_emits_six_events_and_stays_failed(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        result = _runtime(store).run(_spec_document(outcome="failure"), _request(FAILURE_PATH))
        assert [item.event.type for item in result.stored] == list(FAILURE_PATH)
        assert result.disposition is SimulationDisposition.FAILED
        assert result.snapshot.status is RunStatus.FAILED
        assert result.snapshot == _replay(store)
        assert result.stored[4].event.data.payload == {
            "reasonCode": "simulation.outcome.failure",
            "retryHint": "not-retryable",
        }
        assert result.stored[5].event.data.payload == {"reasonCode": "simulation.outcome.failure"}


def test_unknown_path_emits_five_events_and_stops(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        result = _runtime(store).run(_spec_document(outcome="unknown"), _request(UNKNOWN_PATH))
        assert [item.event.type for item in result.stored] == list(UNKNOWN_PATH)
        assert result.disposition is SimulationDisposition.UNKNOWN
        assert result.snapshot.status is RunStatus.UNKNOWN
        assert result.snapshot.active_attempt_id == ATTEMPT
        assert result.snapshot == _replay(store)
        assert store.last_sequence() == 5


def test_sequence_uses_global_head_and_nonzero_streamversion(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.append(_foreign_draft("evt.foreign.1", streamid="stream.simulated"))
        store.append(_foreign_draft("evt.foreign.2", streamid="stream.other"))
        result = _runtime(store).run(load_spec(EXAMPLES / "valid/minimal.yaml"), _request())
        assert [item.sequence for item in result.stored] == [3, 4, 5, 6, 7, 8]
        assert result.stored[0].event.streamversion == 1
        assert result.snapshot == _replay(store)
        assert result.snapshot.status is RunStatus.COMPLETED


def test_missing_outcome_is_rejected_without_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="missing outcome"):
            _runtime(store).run(_spec_document(outcome=None), _request())
        _assert_unchanged(store, 0)


@pytest.mark.parametrize(
    "outcome",
    (
        [],
        {},
        {"secret-field": "sk-secret-value"},
        ["\x1b[31msecret-field\nnext-line"],
        "sk-secret-value",
    ),
)
def test_malformed_outcome_is_rejected_without_echo(tmp_path: Path, outcome: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        with pytest.raises(SimulationError) as info:
            _runtime(store).run(_spec_document(outcome=outcome), _request())
        _assert_error_hides_secrets(
            info.value,
            "secret-field",
            "sk-secret-value",
            "\x1b",
            "\n",
        )
        _assert_unchanged(store, 0)


def test_blocked_dry_run_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    document = _spec_document()
    document["workflows"][0]["graph"]["nodes"][0]["blockType"] = "missing.block"
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="ready plan"):
            _runtime(store).run(document, _request())
        _assert_unchanged(store, 0)


@pytest.mark.parametrize("runtime_type", ("python", "container", "remote-service", "composite"))
def test_non_simulated_runtime_writes_nothing(tmp_path: Path, runtime_type: str) -> None:
    database = tmp_path / "research.db"
    registry = BlockRegistry()
    for manifest in builtin_manifests():
        registry.register(manifest)
    payload: dict[str, object] = {"type": runtime_type}
    if runtime_type in {"python", "container", "remote-service"}:
        payload["entrypoint"] = "tripwire.module:main"
    registry.register(
        BlockManifest.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "Block",
                "metadata": {"id": "other.experiment", "version": "0.1.0"},
                "runtime": payload,
                "inputs": [],
                "outputs": [],
                "configSchema": {
                    "type": "object",
                    "properties": {
                        "outcome": {
                            "type": "string",
                            "enum": ["success", "failure", "unknown"],
                        },
                        "seed": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            }
        )
    )
    registry.seal()
    document = _spec_document()
    document["workflows"][0]["graph"]["nodes"][0]["blockType"] = "other.experiment"
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            SimulatedRuntime(store, registry, project_id=PROJECT, run_id=RUN).run(
                document, _request()
            )
        assert info.value.code == "unsupported-block-type"
        _assert_unchanged(store, 0)


def test_multi_task_edge_approval_loop_and_resources_write_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        runtime = _runtime(store)
        two_tasks = _spec_document()
        two_tasks["workflows"][0]["graph"]["nodes"].append(
            {
                "kind": "task",
                "id": "second",
                "blockType": "simulated.experiment",
                "blockVersion": "0.1.0",
                "config": {"outcome": "success", "seed": 0},
            }
        )
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            runtime.run(two_tasks, _request())
        assert info.value.code == "nodes-not-single"
        _assert_unchanged(store, 0)

        with_edge = _spec_document()
        with_edge["workflows"][0]["graph"]["nodes"].append(
            {
                "kind": "task",
                "id": "second",
                "blockType": "simulated.experiment",
                "blockVersion": "0.1.0",
                "config": {"outcome": "success", "seed": 0},
            }
        )
        with_edge["workflows"][0]["graph"]["edges"] = [{"source": "simulate", "target": "second"}]
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            runtime.run(with_edge, _request())
        assert info.value.code == "edges-not-empty"
        _assert_unchanged(store, 0)

        with_resource = _spec_document()
        with_resource["resources"] = [{"id": "cpu.local", "kind": "cpu", "paid": False}]
        with_resource["workflows"][0]["graph"]["nodes"][0]["resourceRefs"] = ["cpu.local"]
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            runtime.run(with_resource, _request())
        assert info.value.code == "task-resource-refs-not-empty"
        _assert_unchanged(store, 0)

        unused_resource = _spec_document()
        unused_resource["resources"] = [{"id": "cpu.unused", "kind": "cpu", "paid": False}]
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            runtime.run(unused_resource, _request())
        assert info.value.code == "spec-resources-not-empty"
        _assert_unchanged(store, 0)

        with_approval = _spec_document()
        with_approval["workflows"][0]["graph"]["nodes"] = [
            {
                "kind": "approval",
                "id": "gate",
                "requiredRole": "researcher",
                "prompt": "approve the simulation",
            }
        ]
        with pytest.raises(SimulationError) as info:
            runtime.run(with_approval, _request())
        assert info.value.code == "node-not-task"
        _assert_unchanged(store, 0)

        loop_registry = build_registry((EXAMPLES / "manifests/example-train.yaml",))
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            SimulatedRuntime(
                store, loop_registry, project_id="example-bounded-loop", run_id=RUN
            ).run(
                load_spec(EXAMPLES / "valid/bounded-loop.yaml"),
                _request(workflow_id="workflow.iteration"),
            )
        assert info.value.code == "node-not-task"
        _assert_unchanged(store, 0)


def test_unreferenced_spec_resources_write_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    unused = _spec_document()
    unused["resources"] = [{"id": "cpu.unused", "kind": "cpu", "paid": False}]
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match=r"simulated\.experiment") as info:
            _runtime(store).run(unused, _request())
        assert info.value.code == "spec-resources-not-empty"
        _assert_unchanged(store, 0)


def test_caller_mutation_after_preflight_cannot_change_outcome(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    config = spec.workflows[0].graph.nodes[0].config
    preflight_done = Event()
    mutated = Event()
    with EventStore(database) as store:
        original = store.append

        def gated(
            document: dict[str, Any],
            *,
            expected_last_sequence: int | None = None,
        ) -> object:
            if document.get("type") == "run.queued":
                preflight_done.set()
                if not mutated.wait(timeout=5):
                    raise AssertionError("caller mutation did not run")
            return original(document, expected_last_sequence=expected_last_sequence)

        store.append = gated  # type: ignore[method-assign]

        def mutate() -> None:
            if not preflight_done.wait(timeout=5):
                raise AssertionError("preflight did not reach append")
            config["outcome"] = "failure"
            mutated.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mutate)
            result = _runtime(store).run(spec, _request())
            future.result(timeout=5)
        assert [item.event.type for item in result.stored] == list(SUCCESS_PATH)
        assert result.snapshot.status is RunStatus.COMPLETED
        assert config["outcome"] == "failure"


def test_nested_container_mutation_does_not_alias_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    document = _spec_document()
    nested = document["workflows"][0]["graph"]["nodes"][0]["config"]
    with EventStore(database) as store:
        result = _runtime(store).run(document, _request())
        nested["outcome"] = "failure"
        nested["token"] = "sk-secret-value"
        assert result.snapshot.status is RunStatus.COMPLETED
        assert result.snapshot == _replay(store)


def test_invalid_later_event_identity_does_not_write_prefix(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    request = _request()
    request.events["run.completed"] = SimulationEventIdentity(id="", time="not-a-time")
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="ResearchEvent validation"):
            _runtime(store).run(load_spec(EXAMPLES / "valid/minimal.yaml"), request)
        _assert_unchanged(store, 0)


def test_duplicate_event_ids_are_rejected_before_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    request = _request()
    shared = SimulationEventIdentity(id="evt.shared", time=TIME)
    request.events["run.queued"] = shared
    request.events["run.started"] = shared
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="not unique"):
            _runtime(store).run(load_spec(EXAMPLES / "valid/minimal.yaml"), request)
        _assert_unchanged(store, 0)


@pytest.mark.parametrize(
    ("outcome", "path"),
    (
        ("success", SUCCESS_PATH),
        ("failure", FAILURE_PATH),
        ("unknown", UNKNOWN_PATH),
    ),
)
def test_resume_from_each_legal_prefix(
    tmp_path: Path,
    outcome: str,
    path: tuple[str, ...],
) -> None:
    for prefix in range(len(path)):
        database = tmp_path / f"{outcome}-{prefix}.db"
        request = _request(path, prefix=f"{outcome}-{prefix}")
        document = _spec_document(outcome=outcome)
        with EventStore(database) as store:
            _limit_appends(store, prefix)
            with pytest.raises(_Stopped):
                _runtime(store).run(document, request)
            assert store.last_sequence() == prefix
        with EventStore(database) as store:
            result = _runtime(store).run(document, request)
            assert [item.event.type for item in result.stored] == list(path[prefix:])
            assert result.snapshot == _replay(store)
            assert store.last_sequence() == len(path)


def test_terminal_rerun_is_idempotent(tmp_path: Path) -> None:
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    with EventStore(tmp_path / "research.db") as store:
        request = _request()
        first = _runtime(store).run(spec, request)
        second = _runtime(store).run(spec, request)
        assert first.disposition is SimulationDisposition.COMPLETED
        assert second.disposition is SimulationDisposition.COMPLETED
        assert second.stored == ()
        assert store.last_sequence() == 6
    with EventStore(tmp_path / "unknown.db") as store:
        unknown_request = _request(UNKNOWN_PATH)
        first_unknown = _runtime(store).run(_spec_document(outcome="unknown"), unknown_request)
        second_unknown = _runtime(store).run(_spec_document(outcome="unknown"), unknown_request)
        assert first_unknown.disposition is SimulationDisposition.UNKNOWN
        assert second_unknown.disposition is SimulationDisposition.UNRESOLVED
        assert second_unknown.stored == ()
        assert store.last_sequence() == 5
    with EventStore(tmp_path / "failed.db") as store:
        failed_request = _request(FAILURE_PATH)
        first_failed = _runtime(store).run(_spec_document(outcome="failure"), failed_request)
        second_failed = _runtime(store).run(_spec_document(outcome="failure"), failed_request)
        assert first_failed.disposition is SimulationDisposition.FAILED
        assert second_failed.disposition is SimulationDisposition.FAILED
        assert second_failed.stored == ()


def test_mismatched_existing_run_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        _limit_appends(store, 3)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        other = load_document(EXAMPLES / "valid/minimal.yaml")
        other["metadata"]["revision"] = 2
        with pytest.raises(SimulationError, match="does not match") as info:
            _runtime(store).run(other, request)
        assert info.value.code == "experiment-revision-mismatch"
        assert store.last_sequence() == 3
        with pytest.raises(SimulationError, match="does not match") as info:
            _runtime(store).run(spec, _request(attempt_id="attempt.other"))
        assert info.value.code == "attempt-id-mismatch"
        assert store.last_sequence() == 3


def test_omitted_decision_digest_on_existing_run_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    registry = build_registry()
    report = TrustedKernel(registry).dry_run(spec, workflow_id=WORKFLOW)
    with EventStore(database) as store:
        store.append(
            _lifecycle_draft(
                "run.queued",
                "evt.seed.run.queued",
                payload={
                    "workflowId": WORKFLOW,
                    "specDigest": report.digests.spec,
                    "registryDigest": report.digests.registry,
                    "planDigest": report.digests.plan,
                    "maxAttempts": 1,
                },
            )
        )
        with pytest.raises(SimulationError, match="does not match"):
            _runtime(store, registry).run(spec, _request())
        assert store.last_sequence() == 1


def test_stale_decision_digest_on_existing_run_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    registry = build_registry()
    report = TrustedKernel(registry).dry_run(spec, workflow_id=WORKFLOW)
    stale = "jcs-sha256:" + "00" * 32
    assert stale != _t0_decision_digest(report)
    with EventStore(database) as store:
        store.append(
            _lifecycle_draft(
                "run.queued",
                "evt.seed.run.queued",
                payload={
                    "workflowId": WORKFLOW,
                    "specDigest": report.digests.spec,
                    "registryDigest": report.digests.registry,
                    "planDigest": report.digests.plan,
                    "decisionDigest": stale,
                    "maxAttempts": 1,
                },
            )
        )
        with pytest.raises(SimulationError, match="does not match"):
            _runtime(store, registry).run(spec, _request())
        assert store.last_sequence() == 1


def _race_simulations(database: Path) -> tuple[list[object], list[object]]:
    start = Barrier(2, timeout=5)

    def run_one(index: int) -> tuple[str, object]:
        with EventStore(database) as store:
            original = store.append
            first = {"armed": True}

            def gated(
                document: dict[str, Any],
                *,
                expected_last_sequence: int | None = None,
            ) -> object:
                if first["armed"]:
                    first["armed"] = False
                    start.wait()
                return original(document, expected_last_sequence=expected_last_sequence)

            store.append = gated  # type: ignore[method-assign]
            try:
                result = _runtime(store).run(
                    load_spec(EXAMPLES / "valid/minimal.yaml"),
                    _request(prefix=f"race-{index}"),
                )
                return ("ok", result)
            except EventSequenceConflictError as exc:
                return ("conflict", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run_one, (0, 1)))
    successes = [item for kind, item in results if kind == "ok"]
    conflicts = [item for kind, item in results if kind == "conflict"]
    return successes, conflicts


def test_concurrent_cas_does_not_retry(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    successes, conflicts = _race_simulations(database)
    assert len(successes) == 1
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert isinstance(conflict, EventSequenceConflictError)
    with EventStore(database) as store:
        assert store.last_sequence() == 6
        assert store.verify_integrity() == 6


def test_concurrent_cas_is_stable_across_repeated_races(tmp_path: Path) -> None:
    for index in range(30):
        database = tmp_path / f"race-{index}.db"
        successes, conflicts = _race_simulations(database)
        assert len(successes) == 1, index
        assert len(conflicts) == 1, index


def test_integrity_and_duplicate_errors_are_not_success(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        store.append(_foreign_draft(request.events["run.queued"].id, streamid="stream.other"))
        with pytest.raises((SimulationError, DuplicateEventError)):
            _runtime(store).run(spec, request)
        assert store.last_sequence() == 1

    broken = tmp_path / "broken.db"
    with EventStore(broken) as store:
        _runtime(store).run(spec, _request(prefix="ok"))
    with sqlite3.connect(broken, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        last = connection.execute("SELECT MAX(sequence) FROM events").fetchone()[0]
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = ?",
            ("sha256:" + "00" * 32, last),
        )
        connection.execute(_trigger_statement("events_reject_update"))
    with EventStore(broken) as store, pytest.raises(EventIntegrityError):
        _runtime(store).run(spec, _request(prefix="later"))


def test_hostile_config_error_does_not_echo_secrets(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    document = _spec_document()
    document["workflows"][0]["graph"]["nodes"][0]["config"][HOSTILE_KEY] = "sk-secret-value"
    with EventStore(database) as store:
        with pytest.raises(SimulationError) as info:
            _runtime(store).run(document, _request())
        _assert_error_hides_secrets(
            info.value,
            HOSTILE_KEY,
            "sk-secret-value",
            "secret-field",
            "\x1b",
        )
        _assert_unchanged(store, 0)


def test_side_effect_tripwires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"runtime side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(LocalArtifactStore, "put", tripwire)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        result = _runtime(store).run(load_spec(EXAMPLES / "valid/minimal.yaml"), _request())
        assert result.disposition is SimulationDisposition.COMPLETED


def test_simulated_runtime_module_has_no_clock_or_io_imports() -> None:
    module = importlib.import_module("llm_research_os.execution.simulated")
    imported = set(module.__dict__)
    assert "os" not in imported
    assert "socket" not in imported
    assert "sqlite3" not in imported
    assert "subprocess" not in imported
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    for forbidden in (
        "datetime.now",
        "time.time",
        "random.",
        "uuid.",
        "urllib",
        "subprocess",
        "cuda",
        "mps",
        "ArtifactStore",
        "record_plan_authorization_event",
        "authorization_events",
        "query_plan_authorization_lineage",
    ):
        assert forbidden not in source


def test_cancellation_requested_emits_cancelled_facts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request(extra_events=_cancel_identities())
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.cancel.requested",
                payload={"reasonCode": "operator.requested"},
            )
        )
        result = _runtime(store).run(spec, request)
        assert [item.event.type for item in result.stored] == [
            "attempt.cancelled",
            "run.cancelled",
        ]
        assert result.disposition is SimulationDisposition.CANCELLED
        assert store.last_sequence() == 7
        assert result.snapshot.status is RunStatus.CANCELLED
        assert result.snapshot.attempts[0].status is AttemptStatus.CANCELLED
        assert result.snapshot.cancellation_requested is True


def test_attempt_cancel_requested_emits_attempt_cancelled_only(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request(extra_events=_cancel_identities())
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            _lifecycle_draft(
                "attempt.cancel.requested",
                "evt.attempt.cancel.requested",
                payload={"reasonCode": "operator.requested"},
                attempt_id=ATTEMPT,
            )
        )
        result = _runtime(store).run(spec, request)
        assert [item.event.type for item in result.stored] == ["attempt.cancelled"]
        assert result.disposition is SimulationDisposition.UNRESOLVED
        assert store.last_sequence() == 6
        assert result.snapshot.cancellation_requested is False
        assert result.snapshot.attempts[0].cancellation_requested is True
        assert result.snapshot.attempts[0].status is AttemptStatus.CANCELLED
        assert result.snapshot.status is RunStatus.RUNNING


def test_unknown_is_not_collapsed_to_cancelled(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = _spec_document(outcome="unknown")
    request = _request(UNKNOWN_PATH, extra_events=_cancel_identities())
    with EventStore(database) as store:
        result = _runtime(store).run(spec, request)
        assert result.disposition is SimulationDisposition.UNKNOWN
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.run.cancel.requested.after.unknown",
                payload={"reasonCode": "operator.requested"},
            )
        )
        resumed = _runtime(store).run(spec, request)
        assert resumed.disposition is SimulationDisposition.UNRESOLVED
        assert resumed.stored == ()
        assert resumed.snapshot.status is RunStatus.UNKNOWN
        assert store.last_sequence() == 6


def test_cancel_path_requires_caller_owned_identities(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        _limit_appends(store, 2)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.cancel.requested",
                payload={"reasonCode": "operator.requested"},
            )
        )
        with pytest.raises(SimulationError, match="incomplete"):
            _runtime(store).run(spec, request)
        assert store.last_sequence() == 3


def test_cancelled_run_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request(extra_events=_cancel_identities())
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.cancel.requested",
                payload={"reasonCode": "operator.requested"},
            )
        )
        first = _runtime(store).run(spec, request)
        assert first.disposition is SimulationDisposition.CANCELLED
        second = _runtime(store).run(spec, request)
        assert second.disposition is SimulationDisposition.CANCELLED
        assert second.stored == ()
        assert store.last_sequence() == 7


def test_attempt_cancelled_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(
            _lifecycle_draft(
                "attempt.cancel.requested",
                "evt.attempt.cancel.requested",
                payload={"reasonCode": "operator.requested"},
                attempt_id=ATTEMPT,
            )
        )
        control.append(
            _lifecycle_draft(
                "attempt.cancelled",
                "evt.attempt.cancelled",
                payload={},
                attempt_id=ATTEMPT,
            )
        )
        result = _runtime(store).run(spec, request)
        assert result.disposition is SimulationDisposition.UNRESOLVED
        assert result.stored == ()
        assert store.last_sequence() == 6
        assert result.snapshot.attempts[0].status is AttemptStatus.CANCELLED
        assert result.snapshot.status is RunStatus.RUNNING


def test_completed_after_run_cancel_request_is_terminal(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.run.cancel.requested",
                payload={"reasonCode": "operator.requested"},
            )
        )
        control.append(
            _lifecycle_draft(
                "attempt.succeeded",
                "evt.manual.attempt.succeeded",
                payload={},
                attempt_id=ATTEMPT,
            )
        )
        control.append(_lifecycle_draft("run.completed", "evt.manual.run.completed", payload={}))
        result = _runtime(store).run(spec, request)
        assert result.disposition is SimulationDisposition.COMPLETED
        assert result.stored == ()
        assert store.last_sequence() == 7
        assert result.snapshot.status is RunStatus.COMPLETED
        assert result.snapshot.cancellation_requested is True


def test_failed_after_run_cancel_request_is_terminal(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = _spec_document(outcome="failure")
    request = _request(FAILURE_PATH)
    with EventStore(database) as store:
        _limit_appends(store, 4)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(
            _lifecycle_draft(
                "run.cancel.requested",
                "evt.run.cancel.requested",
                payload={"reasonCode": "operator.requested"},
            )
        )
        control.append(
            _lifecycle_draft(
                "attempt.failed",
                "evt.manual.attempt.failed",
                payload={
                    "reasonCode": "simulation.outcome.failure",
                    "retryHint": "not-retryable",
                },
                attempt_id=ATTEMPT,
            )
        )
        control.append(
            _lifecycle_draft(
                "run.failed",
                "evt.manual.run.failed",
                payload={"reasonCode": "simulation.outcome.failure"},
            )
        )
        result = _runtime(store).run(spec, request)
        assert result.disposition is SimulationDisposition.FAILED
        assert result.stored == ()
        assert store.last_sequence() == 7
        assert result.snapshot.status is RunStatus.FAILED
        assert result.snapshot.cancellation_requested is True


def _substituted_simulated_registry(payload: dict[str, Any]) -> BlockRegistry:
    registry = BlockRegistry()
    registry.register(BlockManifest.model_validate(payload))
    registry.seal()
    return registry


def test_substituted_builtin_manifest_digest_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    payload = builtin_manifests()[0].model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["metadata"]["title"] = "Substituted simulated experiment"
    registry = _substituted_simulated_registry(payload)
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="canonical") as info:
            SimulatedRuntime(store, registry, project_id=PROJECT, run_id=RUN).run(
                load_spec(EXAMPLES / "valid/minimal.yaml"),
                _request(),
            )
        assert info.value.code == "manifest-digest-mismatch"
        _assert_unchanged(store, 0)


def test_permission_bearing_simulated_manifest_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    payload = builtin_manifests()[0].model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["permissions"] = ["network"]
    registry = _substituted_simulated_registry(payload)
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="canonical") as info:
            SimulatedRuntime(store, registry, project_id=PROJECT, run_id=RUN).run(
                load_spec(EXAMPLES / "valid/minimal.yaml"),
                _request(),
            )
        assert info.value.code == "manifest-digest-mismatch"
        _assert_unchanged(store, 0)


def test_unsealed_registry_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    registry = BlockRegistry()
    for manifest in builtin_manifests():
        registry.register(manifest)
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="sealed registry"):
            SimulatedRuntime(store, registry, project_id=PROJECT, run_id=RUN).run(
                load_spec(EXAMPLES / "valid/minimal.yaml"),
                _request(),
            )
        _assert_unchanged(store, 0)


def test_plan_authorization_failure_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "research.db"

    def reject(*args: object, **kwargs: object) -> NoReturn:
        raise PlanAuthorizationError("test rejection")

    monkeypatch.setattr("llm_research_os.execution.simulated.authorize_plan", reject)
    with EventStore(database) as store:
        with pytest.raises(SimulationError, match="authorization failed"):
            _runtime(store).run(load_spec(EXAMPLES / "valid/minimal.yaml"), _request())
        _assert_unchanged(store, 0)


def test_minimal_example_completes_success_simulation(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    assert spec.workflows[0].graph.nodes[0].config["outcome"] == "success"
    assert spec.workflows[0].graph.nodes[0].config["seed"] == 0
    with EventStore(database) as store:
        result = _runtime(store).run(spec, _request())
        assert result.disposition is SimulationDisposition.COMPLETED
        assert [item.event.type for item in result.stored] == list(SUCCESS_PATH)


def _metric_identities() -> dict[str, SimulationEventIdentity]:
    return {
        TYPE_TRAINING_STEP: SimulationEventIdentity(id="evt.training.step", time=TIME),
        TYPE_EVALUATION_METRIC: SimulationEventIdentity(id="evt.evaluation.metric", time=TIME),
    }


def test_success_path_emits_seeded_synthetic_metrics_after_attempt_started(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.db"
    expected = [
        *SUCCESS_PATH[:4],
        TYPE_TRAINING_STEP,
        TYPE_EVALUATION_METRIC,
        *SUCCESS_PATH[4:],
    ]
    with EventStore(database) as store:
        result = _runtime(store).run(
            load_spec(EXAMPLES / "valid/minimal.yaml"),
            _request(extra_events=_metric_identities()),
        )
        types = [item.event.type for item in result.stored]
        assert types == expected
        assert result.disposition is SimulationDisposition.COMPLETED
        assert result.snapshot == _replay(store)
        training = parse_training_step_payload(result.stored[4].event)
        evaluation = parse_evaluation_metric_payload(result.stored[5].event)
        assert training.kind == "synthetic"
        assert evaluation.kind == "synthetic"
        assert training.model_dump(mode="json", by_alias=True) == synthetic_training_payload(
            RUN, ATTEMPT
        )
        assert evaluation.model_dump(mode="json", by_alias=True) == synthetic_evaluation_payload(
            RUN, ATTEMPT
        )
        second = _runtime(store).run(
            load_spec(EXAMPLES / "valid/minimal.yaml"),
            _request(extra_events=_metric_identities()),
        )
        assert second.stored == ()
        assert store.get_event("evt.training.step") is not None


def test_failure_path_ignores_metric_identities(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        result = _runtime(store).run(
            _spec_document(outcome="failure"),
            _request(FAILURE_PATH, extra_events=_metric_identities()),
        )
        assert [item.event.type for item in result.stored] == list(FAILURE_PATH)
        assert store.get_event("evt.training.step") is None


def _run_simulation_toctou(database: Path, *, prefix: str) -> None:
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    config = spec.workflows[0].graph.nodes[0].config
    preflight_done = Event()
    mutated = Event()
    with EventStore(database) as store:
        original = store.append

        def gated(
            document: dict[str, Any],
            *,
            expected_last_sequence: int | None = None,
        ) -> object:
            if document.get("type") == "run.queued":
                preflight_done.set()
                assert mutated.wait(timeout=5)
            return original(document, expected_last_sequence=expected_last_sequence)

        store.append = gated  # type: ignore[method-assign]

        def mutate() -> None:
            assert preflight_done.wait(timeout=5)
            config["outcome"] = "failure"
            mutated.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mutate)
            result = _runtime(store).run(spec, _request(prefix=prefix))
            future.result(timeout=5)
        assert result.snapshot.status is RunStatus.COMPLETED
        assert [item.event.type for item in result.stored] == list(SUCCESS_PATH)


def test_toctou_isolation_is_stable_across_repeated_races(tmp_path: Path) -> None:
    for index in range(30):
        _run_simulation_toctou(tmp_path / f"toctou-{index}.db", prefix=f"toctou-{index}")
