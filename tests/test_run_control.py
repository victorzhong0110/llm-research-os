from __future__ import annotations

import builtins
import importlib
import json
import socket
import sqlite3
import subprocess
import time
from collections import UserDict, UserList
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any, NoReturn

import pytest

from llm_research_os.events.models import validate_event_document
from llm_research_os.projections import fold_events, replay_events
from llm_research_os.runs import (
    RunControl,
    RunControlError,
    RunControlHead,
    RunPayloadError,
    RunStateProjection,
    RunStatus,
    RunTransitionError,
)
from llm_research_os.runs.control import _snapshot_json_document
from llm_research_os.storage import (
    DuplicateEventError,
    EventIntegrityError,
    EventSequenceConflictError,
    EventStore,
)
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.schema import MIGRATION_STATEMENTS
from llm_research_os.storage.store import EventStore as EventStoreClass

SPEC = "sha256:" + "11" * 32
REGISTRY = "sha256:" + "22" * 32
PLAN = "sha256:" + "33" * 32
PROJECT = "project.example"
RUN = "run.example"


def _queued_payload(max_attempts: int = 2) -> dict[str, Any]:
    return {
        "workflowId": "wf.train",
        "specDigest": SPEC,
        "registryDigest": REGISTRY,
        "planDigest": PLAN,
        "maxAttempts": max_attempts,
    }


def _draft(
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str,
    attempt: str | None = None,
    project: str = PROJECT,
    run: str = RUN,
    revision: int = 1,
    streamid: str = "stream.example",
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": "researcher.alice"},
        "projectId": project,
        "experimentRevision": revision,
        "payload": payload,
        "evidenceRefs": [],
        "runId": run,
    }
    if attempt is not None:
        data["attemptId"] = attempt
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": "https://researchos.dev/projects/example",
        "type": event_type,
        "time": "2026-08-29T12:00:00Z",
        "subject": run,
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "streamid": streamid,
        "data": data,
    }


def _foreign_draft(index: int, *, project: str, run: str) -> dict[str, Any]:
    return _draft(
        "run.queued",
        _queued_payload(max_attempts=1),
        event_id=f"evt.foreign.{index}",
        project=project,
        run=run,
        streamid=f"stream.{project}",
    )


def _queued_draft(event_id: str = "evt.run.queued.1", **kwargs: Any) -> dict[str, Any]:
    return _draft("run.queued", _queued_payload(), event_id=event_id, **kwargs)


def _started_draft(event_id: str = "evt.run.started.2", **kwargs: Any) -> dict[str, Any]:
    return _draft("run.started", {}, event_id=event_id, **kwargs)


def _attempt_queued_draft(event_id: str = "evt.attempt.queued.3") -> dict[str, Any]:
    return _draft(
        "attempt.queued",
        {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
        event_id=event_id,
        attempt="attempt.1",
    )


def _attempt_started_draft(event_id: str = "evt.attempt.started.4") -> dict[str, Any]:
    return _draft("attempt.started", {}, event_id=event_id, attempt="attempt.1")


def _attempt_succeeded_draft(event_id: str = "evt.attempt.succeeded.5") -> dict[str, Any]:
    return _draft("attempt.succeeded", {}, event_id=event_id, attempt="attempt.1")


def _completed_draft(event_id: str = "evt.run.completed.6") -> dict[str, Any]:
    return _draft("run.completed", {}, event_id=event_id)


def _success_path() -> list[dict[str, Any]]:
    return [
        _queued_draft(),
        _started_draft(),
        _attempt_queued_draft(),
        _attempt_started_draft(),
        _attempt_succeeded_draft(),
        _completed_draft(),
    ]


def _trigger_statement(name: str) -> str:
    marker = f"CREATE TRIGGER {name}"
    return next(statement for statement in MIGRATION_STATEMENTS if marker in statement)


def _replay_snapshot(store: EventStore) -> object:
    projection = RunStateProjection(project_id=PROJECT, run_id=RUN)
    return fold_events((item.event for item in replay_events(store)), projection)


def _preflight_snapshot(
    control: RunControl,
    document: dict[str, Any],
) -> object:
    head = control.rebuild()
    preflight = dict(document)
    preflight.update(
        {
            "sequence": str(head.last_sequence + 1),
            "sequencetype": "Integer",
            "streamversion": 0,
        }
    )
    event = validate_event_document(preflight)
    projection = RunStateProjection(project_id=PROJECT, run_id=RUN)
    return projection.apply(head.snapshot, event)


def _assert_unchanged(store: EventStore, expected_head: int) -> None:
    assert store.last_sequence() == expected_head
    assert store.verify_integrity() == expected_head


def _assert_error_hides_secrets(error: BaseException, *forbidden: str) -> None:
    rendered = "".join(str(part) for part in (str(error), *error.args, repr(error)))
    for item in forbidden:
        assert item not in rendered


def test_empty_store_rebuild_returns_zero_head_and_none_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        head = control.rebuild()
        assert head.last_sequence == 0
        assert head.snapshot is None
        assert store.last_sequence() == 0


def test_rebuild_uses_global_head_but_folds_only_configured_run(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.append(_foreign_draft(1, project="project.alpha", run="run.shared"))
        store.append(_foreign_draft(2, project="project.beta", run="run.shared"))
        store.append(_queued_draft())
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        head = control.rebuild()
        assert head.last_sequence == 3
        assert store.last_sequence() == 3
        assert head.snapshot is not None
        assert head.snapshot.project_id == PROJECT
        assert head.snapshot.run_id == RUN
        assert head.snapshot.status is RunStatus.QUEUED
        other = RunControl(store, project_id="project.alpha", run_id="run.shared")
        alpha = other.rebuild()
        assert alpha.last_sequence == 3
        assert alpha.snapshot is not None
        assert alpha.snapshot.project_id == "project.alpha"
        assert alpha.snapshot.max_attempts == 1


def test_legal_lifecycle_appends_match_store_replay(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        result = None
        for draft in _success_path():
            expected = _preflight_snapshot(control, draft)
            result = control.append(draft)
            assert result.snapshot == expected
            assert result.snapshot == _replay_snapshot(store)
        assert result is not None
        assert result.snapshot.status is RunStatus.COMPLETED
        assert result.snapshot.active_attempt_id is None
        assert result.snapshot.attempts[0].status == "succeeded"
        assert store.verify_integrity() == 6
        rebuilt = control.rebuild()
        assert rebuilt.last_sequence == 6
        assert rebuilt.snapshot == result.snapshot


def test_illegal_first_event_fails_before_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(RunTransitionError, match="first lifecycle event"):
            control.append(_started_draft())
        _assert_unchanged(store, 0)
        assert store.get_event("evt.run.started.2") is None


def test_illegal_transition_fails_before_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())
        with pytest.raises(RunTransitionError, match="latest attempt"):
            control.append(_completed_draft())
        _assert_unchanged(store, 1)
        assert store.get_event("evt.run.completed.6") is None


def test_bad_payload_unknown_key_and_identity_drift_fail_before_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    hostile_key = "\x1b[31msecret-field\nnext-line"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        secret_payload = {**_queued_payload(), "token": "sk-secret-value"}
        with pytest.raises(RunPayloadError) as secret_info:
            control.append(_draft("run.queued", secret_payload, event_id="evt.secret"))
        _assert_error_hides_secrets(secret_info.value, "sk-secret-value", "token")
        _assert_unchanged(store, 0)

        hostile_payload = {**_queued_payload(), hostile_key: True}
        with pytest.raises(RunPayloadError) as hostile_info:
            control.append(_draft("run.queued", hostile_payload, event_id="evt.hostile"))
        _assert_error_hides_secrets(
            hostile_info.value,
            hostile_key,
            "\x1b",
            "secret-field",
        )
        assert hostile_info.value.__context__ is None
        _assert_unchanged(store, 0)

        control.append(_queued_draft())
        with pytest.raises(RunTransitionError, match="experimentRevision"):
            control.append(_started_draft(revision=2))
        _assert_unchanged(store, 1)
        assert store.get_event("evt.run.started.2") is None


def test_store_owned_fields_are_rejected_and_not_overwritten(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        for field, value in (
            ("sequence", "9"),
            ("sequencetype", "Integer"),
            ("streamversion", 0),
        ):
            draft = _queued_draft()
            draft[field] = value
            with pytest.raises(RunControlError, match="store-assigned"):
                control.append(draft)
            assert field in draft
            _assert_unchanged(store, 0)


def test_project_or_run_mismatch_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(RunControlError, match="projectId/runId"):
            control.append(_queued_draft(project="project.other"))
        with pytest.raises(RunControlError, match="projectId/runId"):
            control.append(_queued_draft(run="run.other"))
        _assert_unchanged(store, 0)


def test_non_lifecycle_event_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(RunControlError, match="lifecycle type"):
            control.append(_draft("metric.recorded", {"loss": 0.1}, event_id="evt.metric"))
        _assert_unchanged(store, 0)


@pytest.mark.parametrize(
    "event_type",
    (
        [],
        {},
        {"secret-field": "sk-secret-value"},
        ["\x1b[31msecret-field\nnext-line"],
    ),
)
def test_malformed_event_type_is_stable_run_control_error(
    tmp_path: Path,
    event_type: object,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        draft = _queued_draft()
        draft["type"] = event_type
        with pytest.raises(RunControlError) as info:
            control.append(draft)
        error = info.value
        assert str(error) == "event draft failed ResearchEvent validation"
        _assert_error_hides_secrets(
            error,
            "secret-field",
            "sk-secret-value",
            "\x1b",
            "\n",
        )
        assert error.__cause__ is None
        assert error.__context__ is None
        _assert_unchanged(store, 0)
        assert store.read_events(limit=10) == []


def test_predicted_sequence_uses_global_head_not_run_count(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.append(_foreign_draft(1, project="project.alpha", run="run.alpha"))
        store.append(_foreign_draft(2, project="project.beta", run="run.beta"))
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        expected = _preflight_snapshot(control, _queued_draft())
        result = control.append(_queued_draft())
        assert result.stored.sequence == 3
        assert result.stored.event.sequence == "3"
        assert result.stored.event.streamversion == 0
        assert result.snapshot == expected
        assert result.snapshot.last_sequence == 3
        assert store.last_sequence() == 3


def test_committed_snapshot_matches_preflight_when_streamversion_is_nonzero(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft(streamid="stream.shared"))
        started = _started_draft(streamid="stream.shared")
        expected = _preflight_snapshot(control, started)
        result = control.append(started)
        assert result.stored.event.streamversion == 1
        assert result.snapshot == expected
        assert result.snapshot == _replay_snapshot(store)


def test_exhausted_global_sequence_fails_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_research_os.runs.control.CLOUD_EVENTS_INTEGER_MAX", 1)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())
        with pytest.raises(RunControlError, match="exhausted"):
            control.append(_started_draft())
        _assert_unchanged(store, 1)
        assert store.get_event("evt.run.started.2") is None


def test_integrity_error_fails_closed_without_append(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = 1",
            ("sha256:" + "00" * 32,),
        )
        connection.execute(_trigger_statement("events_reject_update"))

    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(EventIntegrityError):
            control.rebuild()
        with pytest.raises(EventIntegrityError):
            control.append(_started_draft())
        assert store.get_event("evt.run.started.2") is None


def test_rebuild_pages_without_retaining_event_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits: list[int] = []
    original = EventStoreClass.read_events

    def tracked(
        self: EventStore,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[StoredEvent]:
        limits.append(limit)
        return original(self, after_sequence=after_sequence, limit=limit)

    monkeypatch.setattr(EventStoreClass, "read_events", tracked)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        for index in range(1, 8):
            store.append(_foreign_draft(index, project="project.other", run=f"run.{index}"))
        control = RunControl(store, project_id=PROJECT, run_id=RUN, page_size=3)
        head = control.rebuild()
        assert head.last_sequence == 7
        assert head.snapshot is None
        assert limits
        assert all(limit == 3 for limit in limits)
        assert not hasattr(control, "events")
        assert not hasattr(control, "_events")
        assert not hasattr(head, "events")
        for name, value in vars(control).items():
            assert "seen" not in name
            assert not isinstance(value, (list, dict, set, tuple))
        assert set(RunControlHead.__slots__) == {"last_sequence", "snapshot"}


def _gate_append(store: EventStore, barrier: Barrier) -> None:
    original = store.append

    def gated(
        document: dict[str, Any],
        *,
        expected_last_sequence: int | None = None,
    ) -> StoredEvent:
        barrier.wait()
        return original(document, expected_last_sequence=expected_last_sequence)

    store.append = gated  # type: ignore[method-assign]


def _run_queued_toctou(database: Path) -> None:
    caller = _queued_draft()
    expected_payload = dict(caller["data"]["payload"])
    expected_project = caller["data"]["projectId"]
    expected_run = caller["data"]["runId"]
    preflight_done = Event()
    mutated = Event()
    with EventStore(database) as store:
        original_append = store.append

        def gated(
            document: dict[str, Any],
            *,
            expected_last_sequence: int | None = None,
        ) -> StoredEvent:
            assert document is not caller
            assert document["data"] is not caller["data"]
            assert document["data"]["payload"] is not caller["data"]["payload"]
            preflight_done.set()
            if not mutated.wait(timeout=5):
                raise AssertionError("caller mutation did not run before EventStore.append")
            return original_append(document, expected_last_sequence=expected_last_sequence)

        store.append = gated  # type: ignore[method-assign]
        control = RunControl(store, project_id=PROJECT, run_id=RUN)

        def mutate() -> None:
            if not preflight_done.wait(timeout=5):
                raise AssertionError("preflight did not reach EventStore.append")
            caller["type"] = "run.started"
            caller["data"]["payload"] = {}
            caller["data"]["projectId"] = "project.mutated"
            caller["data"]["runId"] = "run.mutated"
            mutated.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mutate)
            result = control.append(caller)
            future.result(timeout=5)

        assert result.stored.event.type == "run.queued"
        assert result.stored.event.data.payload == expected_payload
        assert result.stored.event.data.project_id == expected_project
        assert result.stored.event.data.run_id == expected_run
        assert result.snapshot.status is RunStatus.QUEUED
        assert caller["type"] == "run.started"
        events = store.read_events(limit=10)
        assert len(events) == 1
        assert events[0].event.type == "run.queued"
        assert events[0].event.data.payload == expected_payload
        assert events[0].event.data.project_id == expected_project
        assert events[0].event.data.run_id == expected_run
        _assert_unchanged(store, 1)
        assert store.get_event("evt.run.queued.1") is not None


def _race_started_appends(database: Path) -> tuple[list[object], list[object], list[str]]:
    start = Barrier(2, timeout=5)
    drafts = (
        _started_draft("evt.run.started.alpha"),
        _started_draft("evt.run.started.beta"),
    )

    def run_one(index: int) -> tuple[str, object]:
        with EventStore(database) as store:
            _gate_append(store, start)
            control = RunControl(store, project_id=PROJECT, run_id=RUN)
            try:
                return ("ok", control.append(drafts[index]))
            except EventSequenceConflictError as exc:
                return ("conflict", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run_one, (0, 1)))
    successes = [item for kind, item in results if kind == "ok"]
    conflicts = [item for kind, item in results if kind == "conflict"]
    return successes, conflicts, [draft["id"] for draft in drafts]


def test_concurrent_cas_exactly_one_append_wins(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(_queued_draft())

    successes, conflicts, event_ids = _race_started_appends(database)
    assert len(successes) == 1
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert isinstance(conflict, EventSequenceConflictError)
    assert conflict.expected_last_sequence == 1
    assert conflict.actual_last_sequence == 2

    with EventStore(database) as store:
        assert store.last_sequence() == 2
        assert store.verify_integrity() == 2
        present = {event_id for event_id in event_ids if store.get_event(event_id) is not None}
        assert len(present) == 1


def test_concurrent_cas_is_stable_across_repeated_races(tmp_path: Path) -> None:
    for index in range(30):
        database = tmp_path / f"race-{index}.db"
        with EventStore(database) as store:
            RunControl(store, project_id=PROJECT, run_id=RUN).append(_queued_draft())
        successes, conflicts, event_ids = _race_started_appends(database)
        assert len(successes) == 1, index
        assert len(conflicts) == 1, index
        with EventStore(database) as store:
            present = {event_id for event_id in event_ids if store.get_event(event_id) is not None}
            assert len(present) == 1, index
            assert store.verify_integrity() == 2


def test_caller_mutation_after_preflight_cannot_change_persisted_event(tmp_path: Path) -> None:
    _run_queued_toctou(tmp_path / "research.db")


def test_toctou_isolation_is_stable_across_repeated_races(tmp_path: Path) -> None:
    for index in range(30):
        _run_queued_toctou(tmp_path / f"toctou-{index}.db")


def test_conflict_retry_replays_and_rejects_now_illegal_transition(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        RunControl(store, project_id=PROJECT, run_id=RUN).append(_queued_draft())
    successes, conflicts, event_ids = _race_started_appends(database)
    assert len(successes) == 1
    assert len(conflicts) == 1
    with EventStore(database) as store:
        present = {event_id for event_id in event_ids if store.get_event(event_id) is not None}
        loser_id = next(event_id for event_id in event_ids if event_id not in present)
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(RunTransitionError, match="illegal lifecycle transition"):
            control.append(_started_draft(loser_id))
        _assert_unchanged(store, 2)
        assert store.get_event(loser_id) is None


def test_duplicate_event_id_still_outranks_a_legal_transition(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft("evt.shared"))
        with pytest.raises(DuplicateEventError, match=r"evt\.shared"):
            control.append(_started_draft("evt.shared"))
        _assert_unchanged(store, 1)
        assert store.get_event("evt.shared") is not None
        assert store.read_events(limit=10)[0].event.type == "run.queued"


def test_run_control_has_no_runtime_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"runtime side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        result = control.append(_queued_draft())
        assert result.snapshot.status is RunStatus.QUEUED


def test_run_control_module_does_not_import_io_or_runtime_modules() -> None:
    module = importlib.import_module("llm_research_os.runs.control")
    imported = set(module.__dict__)
    assert "os" not in imported
    assert "socket" not in imported
    assert "sqlite3" not in imported
    assert "subprocess" not in imported
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "time.time", "random.", "uuid.", "urllib", "subprocess"):
        assert forbidden not in source


def test_omitted_event_id_is_not_generated(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        draft = _queued_draft()
        del draft["id"]
        with pytest.raises(RunControlError, match="ResearchEvent validation"):
            control.append(draft)
        _assert_unchanged(store, 0)


def test_non_dict_draft_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        with pytest.raises(RunControlError, match="JSON object"):
            control.append([_queued_draft()])  # type: ignore[arg-type]
        _assert_unchanged(store, 0)


def test_isolated_snapshot_does_not_change_when_caller_mutates_nested_containers() -> None:
    document = _queued_draft()
    nested_data = document["data"]
    nested_payload = document["data"]["payload"]
    nested_refs = document["data"]["evidenceRefs"]
    snapshot = _snapshot_json_document(document)
    nested_payload["workflowId"] = "wf.mutated"
    nested_refs.append("ev.mutated")
    nested_data["projectId"] = "project.mutated"
    document["type"] = "run.started"
    assert snapshot["type"] == "run.queued"
    assert snapshot["data"]["payload"]["workflowId"] == "wf.train"
    assert snapshot["data"]["evidenceRefs"] == []
    assert snapshot["data"]["projectId"] == PROJECT
    assert snapshot["data"] is not nested_data
    assert snapshot["data"]["payload"] is not nested_payload
    assert snapshot["data"]["evidenceRefs"] is not nested_refs


def test_append_does_not_mutate_caller_document(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        draft = _queued_draft()
        nested_data = draft["data"]
        before = json.dumps(draft, sort_keys=True)
        result = control.append(draft)
        assert result.snapshot.status is RunStatus.QUEUED
        assert draft["data"] is nested_data
        assert "sequence" not in draft
        assert "sequencetype" not in draft
        assert "streamversion" not in draft
        assert json.dumps(draft, sort_keys=True) == before


def test_cyclic_json_is_rejected_quickly_without_write(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)

        cyclic_dict = _queued_draft()
        cyclic_dict["data"]["payload"]["loop"] = cyclic_dict["data"]
        started = time.monotonic()
        with pytest.raises(RunControlError, match="cyclic JSON"):
            control.append(cyclic_dict)
        assert time.monotonic() - started < 1
        _assert_unchanged(store, 0)

        cyclic_list: list[object] = []
        cyclic_list.append(cyclic_list)
        cyclic_array = _queued_draft("evt.run.queued.list")
        cyclic_array["data"]["payload"]["loop"] = cyclic_list
        started = time.monotonic()
        with pytest.raises(RunControlError, match="cyclic JSON"):
            control.append(cyclic_array)
        assert time.monotonic() - started < 1
        _assert_unchanged(store, 0)
        assert store.read_events(limit=10) == []


class _Hooked:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __deepcopy__(self, memo: object) -> _Hooked:
        self.calls.append("deepcopy")
        return self

    def __copy__(self) -> _Hooked:
        self.calls.append("copy")
        return self

    def __iter__(self) -> Any:
        self.calls.append("iter")
        return iter(())

    def items(self) -> Any:
        self.calls.append("items")
        return {}.items()


class _HookedDict(dict[str, Any]):
    def __deepcopy__(self, memo: object) -> _HookedDict:
        raise AssertionError("dict subclass __deepcopy__ ran")

    def __copy__(self) -> _HookedDict:
        raise AssertionError("dict subclass __copy__ ran")


class _HookedList(list[Any]):
    def __deepcopy__(self, memo: object) -> _HookedList:
        raise AssertionError("list subclass __deepcopy__ ran")

    def __copy__(self) -> _HookedList:
        raise AssertionError("list subclass __copy__ ran")


@pytest.mark.parametrize(
    "bad_value",
    (
        (1, 2),
        {"set-item"},
        b"bytes",
        UserDict({"workflowId": "wf.train"}),
        UserList(["a"]),
        _HookedDict({"workflowId": "wf.train"}),
        _HookedList(["a"]),
    ),
)
def test_non_json_containers_are_rejected_without_write(
    tmp_path: Path,
    bad_value: object,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        draft = _queued_draft()
        draft["data"]["payload"]["extra"] = bad_value
        with pytest.raises(RunControlError, match="JSON values"):
            control.append(draft)
        _assert_unchanged(store, 0)
        assert store.read_events(limit=10) == []


def test_copy_hooks_are_not_executed(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    hooked = _Hooked()
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        draft = _queued_draft()
        draft["data"]["payload"]["hooked"] = hooked
        with pytest.raises(RunControlError, match="JSON values"):
            control.append(draft)
        assert hooked.calls == []
        _assert_unchanged(store, 0)


def test_shared_acyclic_containers_are_not_treated_as_cycles() -> None:
    shared_object = {"note": "shared"}
    shared_array = ["shared"]
    document = {
        "left": shared_object,
        "right": shared_object,
        "items": [shared_array, shared_array],
    }
    snapshot = _snapshot_json_document(document)
    assert snapshot["left"] == {"note": "shared"}
    assert snapshot["right"] == {"note": "shared"}
    assert snapshot["left"] is not shared_object
    assert snapshot["right"] is not shared_object
    assert snapshot["items"][0] is not shared_array
    shared_object["note"] = "mutated"
    shared_array.append("mutated")
    assert snapshot["left"]["note"] == "shared"
    assert snapshot["items"][0] == ["shared"]


def test_shared_acyclic_payload_is_not_rejected_as_cyclic(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        shared = {"note": "shared"}
        draft = _queued_draft()
        draft["data"]["payload"]["left"] = shared
        draft["data"]["payload"]["right"] = shared
        with pytest.raises(RunPayloadError):
            control.append(draft)
        _assert_unchanged(store, 0)
