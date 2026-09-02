from __future__ import annotations

import builtins
import importlib
import json
import socket
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from pydantic import TypeAdapter, ValidationError

from llm_research_os.events.models import ResearchEvent, validate_event_document
from llm_research_os.projections import fold_events, replay_events
from llm_research_os.runs import (
    RunPayloadError,
    RunSnapshot,
    RunStateError,
    RunStateProjection,
    RunStatus,
    RunTransitionError,
    validate_run_snapshot_document,
)
from llm_research_os.runs.models import (
    LIFECYCLE_TYPES,
    PAYLOAD_MODELS,
    StrictDigest,
    run_snapshot_document,
)
from llm_research_os.storage import EventStore

STRICT_DIGEST = TypeAdapter(StrictDigest)

EXAMPLES = Path(__file__).parents[1] / "examples" / "run-state"
SPEC = "sha256:" + "11" * 32
REGISTRY = "sha256:" + "22" * 32
PLAN = "sha256:" + "33" * 32


def _load_trace(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(documents: Iterable[dict[str, Any]]) -> list[ResearchEvent]:
    return [validate_event_document(item) for item in documents]


def _fold(
    documents: Iterable[dict[str, Any]],
    *,
    project_id: str = "project.example",
    run_id: str = "run.example",
    resume: RunSnapshot | object | None = ...,
) -> RunSnapshot | None:
    projection = RunStateProjection(project_id=project_id, run_id=run_id)
    events = _events(documents)
    if resume is ...:
        return fold_events(events, projection)
    return fold_events(events, projection, resume=resume)


def _event(
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    *,
    attempt: str | None = None,
    project: str = "project.example",
    run: str | None = "run.example",
    revision: int = 1,
    event_id: str | None = None,
    time: str = "2026-08-29T12:00:00Z",
    streamid: str = "stream.not-the-run-id",
    streamversion: int = 0,
    block_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": "researcher.alice"},
        "projectId": project,
        "experimentRevision": revision,
        "payload": payload,
        "evidenceRefs": [],
    }
    if run is not None:
        data["runId"] = run
    if attempt is not None:
        data["attemptId"] = attempt
    if block_id is not None:
        data["blockId"] = block_id
    return {
        "specversion": "1.0",
        "id": event_id or f"evt.{event_type}.{sequence}",
        "source": "https://researchos.dev/projects/example",
        "type": event_type,
        "time": time,
        "subject": run or project,
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "streamid": streamid,
        "streamversion": streamversion,
        "data": data,
    }


def _queued_payload(max_attempts: int = 2) -> dict[str, Any]:
    return {
        "workflowId": "wf.train",
        "specDigest": SPEC,
        "registryDigest": REGISTRY,
        "planDigest": PLAN,
        "maxAttempts": max_attempts,
    }


def _as_draft(document: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
    draft = json.loads(json.dumps(document))
    draft.pop("sequence")
    draft.pop("sequencetype")
    draft.pop("streamversion")
    if event_id is not None:
        draft["id"] = event_id
    return draft


def test_payload_models_cover_the_frozen_lifecycle_catalog() -> None:
    assert set(PAYLOAD_MODELS) == LIFECYCLE_TYPES


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.json")), ids=lambda p: p.name)
def test_valid_traces_fold_to_committed_snapshots(path: Path) -> None:
    trace = _load_trace(path)
    snapshot = _fold(trace["events"])
    assert snapshot is not None
    assert run_snapshot_document(snapshot) == trace["snapshot"]
    assert validate_run_snapshot_document(trace["snapshot"]) == snapshot


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "invalid").glob("*.json")), ids=lambda p: p.name
)
def test_invalid_traces_fail_closed(path: Path) -> None:
    trace = _load_trace(path)
    with pytest.raises(RunStateError) as exc_info:
        _fold(trace["events"])
    message = str(exc_info.value)
    assert "sk-secret-value" not in message
    assert "nope" not in message
    assert " wf.train" not in message


def test_attempt_succeeded_does_not_complete_the_run() -> None:
    events = _load_trace(EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json")["events"]
    snapshot = _fold(events[:5])
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.attempts[0].status == "succeeded"
    assert snapshot.review.reviewed is False


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.json")), ids=lambda p: p.name)
def test_full_fold_matches_checkpoint_resume(path: Path) -> None:
    events = _load_trace(path)["events"]
    projection = RunStateProjection(project_id="project.example", run_id="run.example")
    parsed = _events(events)
    full = fold_events(parsed, projection)
    if full is not None:
        assert validate_run_snapshot_document(run_snapshot_document(full)) == full
    for index in range(len(parsed) + 1):
        checkpoint = fold_events(parsed[:index], projection)
        if checkpoint is not None:
            assert validate_run_snapshot_document(run_snapshot_document(checkpoint)) == checkpoint
        resumed = fold_events(parsed[index:], projection, resume=checkpoint)
        assert resumed == full


def test_event_store_replay_rebuilds_the_same_snapshot(tmp_path: Path) -> None:
    events = _load_trace(EXAMPLES / "valid" / "03-unknown-lost-recovered-succeeded.json")["events"]
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        for index, document in enumerate(events, start=1):
            store.append(_as_draft(document, event_id=f"store.{index}"))
        first = [item.event for item in replay_events(store, page_size=2)]
        second = [item.event for item in replay_events(store, page_size=3)]
    projection = RunStateProjection(project_id="project.example", run_id="run.example")
    assert fold_events(first, projection) == fold_events(second, projection)


def test_same_run_id_under_different_projects_does_not_mix() -> None:
    alpha = [
        _event(1, "run.queued", _queued_payload(), project="project.alpha", run="run.shared"),
        _event(4, "run.started", {}, project="project.alpha", run="run.shared"),
    ]
    beta = [
        _event(
            2,
            "run.queued",
            _queued_payload(max_attempts=1),
            project="project.beta",
            run="run.shared",
        ),
        _event(
            3,
            "run.cancel.requested",
            {"reasonCode": "reason.user-stop"},
            project="project.beta",
            run="run.shared",
        ),
        _event(5, "run.cancelled", {}, project="project.beta", run="run.shared"),
    ]
    mixed = [alpha[0], beta[0], beta[1], alpha[1], beta[2]]
    alpha_snapshot = _fold(mixed, project_id="project.alpha", run_id="run.shared")
    beta_snapshot = _fold(mixed, project_id="project.beta", run_id="run.shared")
    assert alpha_snapshot is not None
    assert beta_snapshot is not None
    assert alpha_snapshot.status is RunStatus.RUNNING
    assert alpha_snapshot.max_attempts == 2
    assert beta_snapshot.status is RunStatus.CANCELLED
    assert beta_snapshot.max_attempts == 1


def test_missing_heartbeat_does_not_infer_lost_unknown_or_failed() -> None:
    snapshot = _fold(
        [
            _event(1, "run.queued", _queued_payload()),
            _event(2, "run.started", {}),
            _event(
                3,
                "attempt.queued",
                {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
                attempt="attempt.1",
            ),
            _event(4, "attempt.started", {}, attempt="attempt.1"),
        ]
    )
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.attempts[0].status == "running"
    assert snapshot.attempts[0].last_heartbeat_sequence is None


def test_unrelated_event_types_do_not_change_run_or_attempt_status() -> None:
    prefix = [
        _event(1, "run.queued", _queued_payload()),
        _event(2, "run.started", {}),
    ]
    before = _fold(prefix)
    after = _fold(
        [
            *prefix,
            _event(
                3,
                "run.heartbeat",
                {"status": "running"},
                attempt="attempt.ignored",
                block_id="block.train",
            ),
            _event(4, "metric.recorded", {"loss": 0.1}),
            _event(5, "research.note", {}, run=None),
        ]
    )
    assert before is not None
    assert after is not None
    assert after.status == before.status
    assert after.attempts == before.attempts
    assert after.cancellation_requested == before.cancellation_requested
    assert after.workflow_id == before.workflow_id
    assert after.digests == before.digests
    assert after.last_sequence == 4
    assert after.last_event_id == "evt.metric.recorded.4"


def test_other_run_events_create_sequence_gaps_without_state_changes() -> None:
    snapshot = _fold(
        [
            _event(1, "run.queued", _queued_payload()),
            _event(2, "run.started", {}, project="project.other", run="run.other"),
            _event(10, "run.started", {}),
        ]
    )
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.last_sequence == 10


def test_heartbeat_updates_observation_only() -> None:
    snapshot = _fold(
        [
            _event(1, "run.queued", _queued_payload()),
            _event(2, "run.started", {}),
            _event(
                3,
                "attempt.queued",
                {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
                attempt="attempt.1",
            ),
            _event(4, "attempt.started", {}, attempt="attempt.1"),
            _event(5, "attempt.heartbeat", {}, attempt="attempt.1"),
            _event(6, "attempt.heartbeat", {}, attempt="attempt.1"),
        ]
    )
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.attempts[0].status == "running"
    assert snapshot.attempts[0].last_heartbeat_sequence == 6


def test_retry_hint_does_not_authorize_retry() -> None:
    failed = [
        _event(1, "run.queued", _queued_payload()),
        _event(2, "run.started", {}),
        _event(
            3,
            "attempt.queued",
            {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
            attempt="attempt.1",
        ),
        _event(
            4,
            "attempt.failed",
            {"reasonCode": "reason.oom", "retryHint": "not-retryable"},
            attempt="attempt.1",
        ),
    ]
    pending = _fold(failed)
    assert pending is not None
    assert pending.status is RunStatus.RETRY_PENDING
    retried = _fold(
        [
            *failed,
            _event(
                5,
                "attempt.queued",
                {"ordinal": 2, "retryOf": "attempt.1", "retryDecisionId": "decision.retry.1"},
                attempt="attempt.2",
            ),
        ]
    )
    assert retried is not None
    assert retried.status is RunStatus.RUNNING
    assert retried.active_attempt_id == "attempt.2"


def test_run_cancelled_with_no_attempts() -> None:
    snapshot = _fold(
        [
            _event(1, "run.queued", _queued_payload()),
            _event(2, "run.cancel.requested", {"reasonCode": "reason.user-stop"}),
            _event(3, "run.cancelled", {}),
        ]
    )
    assert snapshot is not None
    assert snapshot.status is RunStatus.CANCELLED
    assert snapshot.attempts == ()


def test_retry_while_unknown_is_rejected() -> None:
    with pytest.raises(RunTransitionError, match="lost or unknown"):
        _fold(
            [
                _event(1, "run.queued", _queued_payload()),
                _event(2, "run.started", {}),
                _event(
                    3,
                    "attempt.queued",
                    {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
                    attempt="attempt.1",
                ),
                _event(4, "attempt.started", {}, attempt="attempt.1"),
                _event(5, "attempt.unknown", {"reasonCode": "reason.stale"}, attempt="attempt.1"),
                _event(
                    6,
                    "attempt.queued",
                    {"ordinal": 2, "retryOf": "attempt.1", "retryDecisionId": "decision.retry.1"},
                    attempt="attempt.2",
                ),
            ]
        )


def test_max_attempts_is_an_m0_policy_cap() -> None:
    with pytest.raises(RunTransitionError, match="maxAttempts"):
        _fold(
            [
                _event(1, "run.queued", _queued_payload(max_attempts=1)),
                _event(2, "run.started", {}),
                _event(
                    3,
                    "attempt.queued",
                    {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
                    attempt="attempt.1",
                ),
                _event(
                    4,
                    "attempt.failed",
                    {"reasonCode": "reason.oom", "retryHint": "retryable"},
                    attempt="attempt.1",
                ),
                _event(
                    5,
                    "attempt.queued",
                    {"ordinal": 2, "retryOf": "attempt.1", "retryDecisionId": "decision.retry.1"},
                    attempt="attempt.2",
                ),
            ]
        )


def test_duplicate_reviewed_is_rejected() -> None:
    events = _load_trace(EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json")["events"]
    with pytest.raises(RunTransitionError, match="only once"):
        _fold([*events, _event(8, "run.reviewed", {"decisionId": "decision.review.2"})])


def test_missing_retry_decision_id_is_rejected() -> None:
    with pytest.raises(RunTransitionError, match="retryDecisionId"):
        _fold(
            [
                _event(1, "run.queued", _queued_payload()),
                _event(2, "run.started", {}),
                _event(
                    3,
                    "attempt.queued",
                    {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
                    attempt="attempt.1",
                ),
                _event(
                    4,
                    "attempt.failed",
                    {"reasonCode": "reason.oom", "retryHint": "retryable"},
                    attempt="attempt.1",
                ),
                _event(
                    5,
                    "attempt.queued",
                    {"ordinal": 2, "retryOf": "attempt.1", "retryDecisionId": None},
                    attempt="attempt.2",
                ),
            ]
        )


def test_lifecycle_events_require_null_block_id() -> None:
    with pytest.raises(RunTransitionError, match="blockId"):
        _fold([_event(1, "run.queued", _queued_payload(), block_id="block.train")])


def test_stream_identity_is_not_consulted() -> None:
    snapshot = _fold(
        [
            _event(1, "run.queued", _queued_payload(), streamid="alpha", streamversion=9),
            _event(2, "run.started", {}, streamid="beta", streamversion=0),
        ]
    )
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING


def test_projection_rejects_trimmed_constructor_ids() -> None:
    with pytest.raises(RunStateError, match="identifier"):
        RunStateProjection(project_id=" project.example", run_id="run.example")


def test_initial_state_is_none() -> None:
    projection = RunStateProjection(project_id="project.example", run_id="run.example")
    assert projection.initial_state() is None
    assert _fold([]) is None


def test_python_snapshot_field_names_are_rejected() -> None:
    snapshot = _load_trace(EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json")[
        "snapshot"
    ]
    snapshot["project_id"] = snapshot.pop("projectId")
    with pytest.raises(ValidationError):
        validate_run_snapshot_document(snapshot)


def test_bool_is_not_accepted_as_a_snapshot_sequence() -> None:
    snapshot = _load_trace(EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json")[
        "snapshot"
    ]
    snapshot["lastSequence"] = True
    with pytest.raises(ValidationError):
        validate_run_snapshot_document(snapshot)


def _clone_valid_snapshot(name: str) -> dict[str, Any]:
    return json.loads(json.dumps(_load_trace(EXAMPLES / "valid" / name)["snapshot"]))


def _unreview(document: dict[str, Any]) -> None:
    document["review"] = {
        "reviewed": False,
        "eventId": None,
        "sequence": None,
        "decisionId": None,
    }


def _assert_impossible_snapshot(document: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_run_snapshot_document(document)


def test_failed_run_with_succeeded_latest_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["status"] = "failed"
    _assert_impossible_snapshot(document)


def test_completed_run_with_failed_latest_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["attempts"][0]["status"] = "failed"
    document["attempts"][0]["retryHint"] = "retryable"
    _assert_impossible_snapshot(document)


def test_retry_pending_with_succeeded_latest_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["status"] = "retry_pending"
    _unreview(document)
    _assert_impossible_snapshot(document)


def test_lost_run_with_mismatched_active_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    _unreview(document)
    document["status"] = "lost"
    document["attempts"][0]["status"] = "running"
    document["activeAttemptId"] = document["attempts"][0]["attemptId"]
    _assert_impossible_snapshot(document)


def test_unknown_run_with_mismatched_active_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    _unreview(document)
    document["status"] = "unknown"
    document["attempts"][0]["status"] = "lost"
    document["activeAttemptId"] = document["attempts"][0]["attemptId"]
    _assert_impossible_snapshot(document)


def test_cancelled_run_without_cancellation_request_is_rejected() -> None:
    document = _clone_valid_snapshot("05-cancel-requested-then-cancelled.json")
    document["cancellationRequested"] = False
    _assert_impossible_snapshot(document)


def test_retry_of_pointing_at_the_wrong_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("02-failed-retry-succeeded.json")
    document["attempts"][1]["retryOf"] = "attempt.other"
    _assert_impossible_snapshot(document)


def test_retry_chain_with_non_failed_previous_attempt_is_rejected() -> None:
    document = _clone_valid_snapshot("02-failed-retry-succeeded.json")
    document["attempts"][0]["status"] = "succeeded"
    document["attempts"][0]["retryHint"] = None
    _assert_impossible_snapshot(document)


def test_attempt_sequence_ahead_of_run_cursor_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["attempts"][0]["lastSequence"] = document["lastSequence"] + 1
    _assert_impossible_snapshot(document)


def test_attempt_sequences_must_increase_by_ordinal() -> None:
    document = _clone_valid_snapshot("02-failed-retry-succeeded.json")
    document["attempts"][1]["lastSequence"] = document["attempts"][0]["lastSequence"]
    _assert_impossible_snapshot(document)


def test_heartbeat_sequence_ahead_of_attempt_cursor_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["attempts"][0]["lastHeartbeatSequence"] = document["attempts"][0]["lastSequence"] + 1
    _assert_impossible_snapshot(document)


def test_review_sequence_ahead_of_run_cursor_is_rejected() -> None:
    document = _clone_valid_snapshot("01-single-attempt-succeeded-reviewed.json")
    document["review"]["sequence"] = document["lastSequence"] + 1
    _assert_impossible_snapshot(document)


def _collection_lengths(snapshot: RunSnapshot) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for name, value in vars(snapshot).items():
        if isinstance(value, (list, dict, set, tuple)):
            lengths[name] = len(value)
    for attempt in snapshot.attempts:
        for name, value in vars(attempt).items():
            if isinstance(value, (list, dict, set, tuple)):
                lengths[f"attempt.{name}"] = len(value)
    return lengths


def test_retained_state_does_not_grow_with_event_history() -> None:
    documents = [
        _event(1, "run.queued", _queued_payload()),
        _event(2, "run.started", {}),
        _event(
            3,
            "attempt.queued",
            {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
            attempt="attempt.1",
        ),
        _event(4, "attempt.started", {}, attempt="attempt.1"),
    ]
    documents.extend(
        _event(sequence, "attempt.heartbeat", {}, attempt="attempt.1") for sequence in range(5, 45)
    )
    snapshot = _fold(documents)
    assert snapshot is not None
    lengths = _collection_lengths(snapshot)
    assert lengths["attempts"] == 1
    assert all(length <= 32 for length in lengths.values())
    dumped = run_snapshot_document(snapshot)
    assert "evt.attempt.heartbeat.5" not in json.dumps(dumped)
    assert dumped["attempts"][0]["lastHeartbeatSequence"] == 44
    assert dumped["lastEventId"] == "evt.attempt.heartbeat.44"


def test_reducer_has_no_runtime_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"runtime side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    events = _load_trace(EXAMPLES / "valid" / "04-cancel-requested-then-completed.json")["events"]
    snapshot = _fold(events)
    assert snapshot is not None
    assert snapshot.status is RunStatus.COMPLETED


def test_reducer_module_does_not_import_io_modules() -> None:
    module = importlib.import_module("llm_research_os.runs.reducer")
    imported = set(module.__dict__)
    assert "os" not in imported
    assert "socket" not in imported
    assert "sqlite3" not in imported
    assert "pathlib" not in imported
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "time.time", "random.", "sqlite3", "urllib"):
        assert forbidden not in source


def test_payload_error_does_not_echo_secret_text() -> None:
    with pytest.raises(RunPayloadError) as exc_info:
        _fold([_event(1, "run.queued", {**_queued_payload(), "token": "sk-secret-value"})])
    assert "sk-secret-value" not in str(exc_info.value)
    assert "token" not in str(exc_info.value)


def test_payload_error_does_not_echo_hostile_unknown_key() -> None:
    hostile_key = "\x1b[31msecret-field\nnext-line"
    with pytest.raises(RunPayloadError) as exc_info:
        _fold([_event(1, "run.queued", {**_queued_payload(), hostile_key: True})])
    error = exc_info.value
    rendered = "".join(str(part) for part in (str(error), *error.args, repr(error)))
    assert hostile_key not in rendered
    assert "\x1b" not in rendered
    assert "\n" not in rendered
    assert "secret-field" not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "run.queued" in str(error)
    assert "evt.run.queued.1" in str(error)
    assert "sequence 1" in str(error)


def test_ordinary_invalid_payload_still_raises_run_payload_error() -> None:
    with pytest.raises(RunPayloadError) as exc_info:
        _fold([_event(1, "run.queued", {"workflowId": "wf.train"})])
    message = str(exc_info.value)
    assert "run.queued" in message
    assert "evt.run.queued.1" in message
    assert "sequence 1" in message
    assert "workflowId" not in message


def test_fold_resume_none_starts_from_empty_run() -> None:
    events = _load_trace(EXAMPLES / "valid" / "01-single-attempt-succeeded-reviewed.json")["events"]
    projection = RunStateProjection(project_id="project.example", run_id="run.example")
    parsed = _events(events)
    assert fold_events(parsed, projection, resume=None) == fold_events(parsed, projection)


def test_strict_digest_accepts_new_and_legacy_labels() -> None:
    payload = "a" * 64
    current = f"jcs-sha256:{payload}"
    legacy = f"sha256:{payload}"
    assert len(legacy) == 71
    assert len(current) == 75
    assert STRICT_DIGEST.validate_python(current) == current
    assert STRICT_DIGEST.validate_python(legacy) == legacy
    assert STRICT_DIGEST.validate_python(SPEC) == SPEC


@pytest.mark.parametrize(
    "value",
    (
        f"  jcs-sha256:{'a' * 64}  ",
        f"jcs-sha256:{'A' * 64}",
        f"sha256:{'A' * 64}",
        f"SHA256:{'a' * 64}",
        f"jcs-sha256:{'a' * 63}",
        f"sha256:{'a' * 65}",
        f"sha512:{'a' * 64}",
        "sha256:" + "a" * 60,
        "not-a-digest",
    ),
)
def test_strict_digest_rejects_whitespace_case_length_and_malformed_labels(value: str) -> None:
    with pytest.raises(ValidationError):
        STRICT_DIGEST.validate_python(value)
