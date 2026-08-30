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
    SimulatedRuntime,
    SimulationDisposition,
    SimulationError,
    SimulationEventIdentity,
    SimulationRequest,
    TrustedKernel,
)
from llm_research_os.execution.simulated import FAILURE_PATH, SUCCESS_PATH, UNKNOWN_PATH
from llm_research_os.projections import fold_events, replay_events
from llm_research_os.runs import RunControl, RunStateProjection, RunStatus
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
) -> SimulationRequest:
    return SimulationRequest(
        workflow_id=workflow_id,
        attempt_id=attempt_id,
        source=SOURCE,
        subject=RUN,
        stream_id=stream_id,
        actor_id="researcher.alice",
        events=_identities(path, prefix=prefix),
    )


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
            "maxAttempts": 1,
        }
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
        with pytest.raises(SimulationError, match=r"simulated\.experiment"):
            SimulatedRuntime(store, registry, project_id=PROJECT, run_id=RUN).run(
                document, _request()
            )
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
        with pytest.raises(SimulationError, match=r"simulated\.experiment"):
            runtime.run(two_tasks, _request())
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
        with pytest.raises(SimulationError, match=r"simulated\.experiment"):
            runtime.run(with_edge, _request())
        _assert_unchanged(store, 0)

        with_resource = _spec_document()
        with_resource["resources"] = [{"id": "cpu.local", "kind": "cpu", "paid": False}]
        with_resource["workflows"][0]["graph"]["nodes"][0]["resourceRefs"] = ["cpu.local"]
        with pytest.raises(SimulationError, match=r"simulated\.experiment"):
            runtime.run(with_resource, _request())
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
        with pytest.raises(SimulationError):
            runtime.run(with_approval, _request())
        _assert_unchanged(store, 0)

        loop_registry = build_registry((EXAMPLES / "manifests/example-train.yaml",))
        with pytest.raises(SimulationError, match=r"simulated\.experiment"):
            SimulatedRuntime(
                store, loop_registry, project_id="example-bounded-loop", run_id=RUN
            ).run(
                load_spec(EXAMPLES / "valid/bounded-loop.yaml"),
                _request(workflow_id="workflow.iteration"),
            )
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
        with pytest.raises(SimulationError, match="does not match"):
            _runtime(store).run(other, request)
        assert store.last_sequence() == 3
        with pytest.raises(SimulationError, match="does not match"):
            _runtime(store).run(spec, _request(attempt_id="attempt.other"))
        assert store.last_sequence() == 3


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
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = 1",
            ("sha256:" + "00" * 32,),
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
    ):
        assert forbidden not in source


def test_cancellation_requested_stops_without_inferring_outcome(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    request = _request()
    with EventStore(database) as store:
        _limit_appends(store, 2)
        with pytest.raises(_Stopped):
            _runtime(store).run(spec, request)
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(
            {
                "specversion": "1.0",
                "id": "evt.cancel.requested",
                "source": SOURCE,
                "type": "run.cancel.requested",
                "time": TIME,
                "subject": RUN,
                "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
                "datacontenttype": "application/json",
                "streamid": "stream.simulated",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice"},
                    "projectId": PROJECT,
                    "experimentRevision": 1,
                    "payload": {"reasonCode": "operator.requested"},
                    "evidenceRefs": [],
                    "runId": RUN,
                },
            }
        )
        result = _runtime(store).run(spec, request)
        assert result.disposition is SimulationDisposition.UNRESOLVED
        assert result.stored == ()
        assert store.last_sequence() == 3
        assert result.snapshot.cancellation_requested is True
        assert result.snapshot.status is RunStatus.RUNNING


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


def test_minimal_example_completes_success_simulation(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    assert spec.workflows[0].graph.nodes[0].config["outcome"] == "success"
    assert spec.workflows[0].graph.nodes[0].config["seed"] == 0
    with EventStore(database) as store:
        result = _runtime(store).run(spec, _request())
        assert result.disposition is SimulationDisposition.COMPLETED
        assert [item.event.type for item in result.stored] == list(SUCCESS_PATH)


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
