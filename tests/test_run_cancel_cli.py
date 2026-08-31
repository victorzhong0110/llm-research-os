from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from jsonschema import Draft202012Validator

from llm_research_os.cli import main
from llm_research_os.runs import (
    load_run_cancellation_request,
    request_cancellation,
)
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventSequenceConflictError, EventStore

ROOT = Path(__file__).parents[1]
REQUESTS = ROOT / "examples" / "run-cancellation-requests" / "valid"
RUN_REQUEST = REQUESTS / "run.json"
ATTEMPT_REQUEST = REQUESTS / "attempt.json"
RUN_STATE_SCHEMA = ROOT / "schemas" / "run-state" / "v0alpha1.schema.json"
SPEC_DIGEST = "sha256:" + "11" * 32
REGISTRY_DIGEST = "sha256:" + "22" * 32
PLAN_DIGEST = "sha256:" + "33" * 32


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _draft(
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": "runtime.simulated"},
        "projectId": "example-minimal",
        "experimentRevision": 1,
        "runId": "run.simulated",
        "payload": payload,
        "evidenceRefs": [],
    }
    if attempt_id is not None:
        data["attemptId"] = attempt_id
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": "https://researchos.dev/projects/example-minimal",
        "type": event_type,
        "time": "2026-08-30T12:00:00Z",
        "subject": "run.simulated",
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "streamid": "stream.simulated",
        "data": data,
    }


def _seed_running(database: Path) -> None:
    drafts = (
        _draft(
            "run.queued",
            {
                "workflowId": "workflow.simulation",
                "specDigest": SPEC_DIGEST,
                "registryDigest": REGISTRY_DIGEST,
                "planDigest": PLAN_DIGEST,
                "maxAttempts": 1,
            },
            event_id="evt.1.run.queued",
        ),
        _draft("run.started", {}, event_id="evt.2.run.started"),
        _draft(
            "attempt.queued",
            {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
            event_id="evt.3.attempt.queued",
            attempt_id="attempt.1",
        ),
        _draft(
            "attempt.started",
            {},
            event_id="evt.4.attempt.started",
            attempt_id="attempt.1",
        ),
    )
    with EventStore(database) as store:
        for draft in drafts:
            store.append(draft)


def _seed_completed(database: Path) -> None:
    _seed_running(database)
    with EventStore(database, require_existing=True) as store:
        store.append(
            _draft(
                "attempt.succeeded",
                {},
                event_id="evt.5.attempt.succeeded",
                attempt_id="attempt.1",
            )
        )
        store.append(_draft("run.completed", {}, event_id="evt.6.run.completed"))


def _cancel(
    request: Path,
    database: Path,
    *,
    output_format: str = "json",
) -> int:
    return main(
        [
            "runs",
            "cancel",
            str(request),
            str(database),
            "--format",
            output_format,
        ]
    )


def test_run_cancel_records_request_without_claiming_cancelled(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    assert _cancel(RUN_REQUEST, database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    snapshot = json.loads(output.out)
    assert output.err == ""
    assert snapshot["kind"] == "RunSnapshot"
    assert snapshot["status"] == "running"
    assert snapshot["cancellationRequested"] is True
    assert snapshot["attempts"][0]["status"] == "running"
    assert snapshot["attempts"][0]["cancellationRequested"] is False
    assert snapshot["lastSequence"] == 5
    Draft202012Validator(json.loads(RUN_STATE_SCHEMA.read_text(encoding="utf-8"))).validate(
        snapshot
    )
    with EventStore(database, create=False) as store:
        stored = store.get_event("evt.7.run.cancel.requested")
        assert stored is not None
        assert stored.event.type == "run.cancel.requested"
        assert stored.event.data.attempt_id is None
        assert stored.event.data.payload == {"reasonCode": "researcher.requested"}
        assert store.verify_integrity() == 5


def test_attempt_cancel_records_only_active_attempt_request(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    assert _cancel(ATTEMPT_REQUEST, database) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    snapshot = json.loads(output.out)
    assert output.err == ""
    assert snapshot["status"] == "running"
    assert snapshot["cancellationRequested"] is False
    assert snapshot["attempts"][0]["status"] == "running"
    assert snapshot["attempts"][0]["cancellationRequested"] is True
    with EventStore(database, create=False) as store:
        events = store.read_events(after_sequence=4, limit=10)
        assert len(events) == 1
        assert events[0].event.type == "attempt.cancel.requested"
        assert events[0].event.data.attempt_id == "attempt.1"


def test_text_output_states_request_not_process_or_outcome(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    assert _cancel(ATTEMPT_REQUEST, database, output_format="text") == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "cancellation request: recorded" in output.out
    assert "target: attempt attempt.1" in output.out
    assert "attempt cancellation requested: true" in output.out
    assert "run status: running" in output.out
    assert "process signal sent: false" in output.out
    assert "cancellation outcome: not observed" in output.out


def test_missing_database_fails_without_creating_it(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "missing.db"
    assert _cancel(RUN_REQUEST, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["type"] == "EventStoreSchemaError"
    assert not database.exists()


def test_invalid_and_symlink_requests_fail_before_database_open(
    tmp_path: Path,
    capsys: object,
) -> None:
    invalid_document = load_document(RUN_REQUEST)
    invalid_document["event"].pop("id")
    invalid = _write_json(tmp_path / "invalid.json", invalid_document)
    link = tmp_path / "request-link.json"
    link.symlink_to(RUN_REQUEST)
    for index, request in enumerate((invalid, link), start=1):
        database = tmp_path / f"missing-{index}.db"
        assert _cancel(request, database) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.out == ""
        assert json.loads(output.err)["kind"] == "ProblemReport"
        assert not database.exists()


def test_terminal_run_revision_drift_and_wrong_attempt_are_zero_write_errors(
    tmp_path: Path,
    capsys: object,
) -> None:
    completed = tmp_path / "completed.db"
    _seed_completed(completed)
    assert _cancel(RUN_REQUEST, completed) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "terminal run" in output.err
    with EventStore(completed, create=False) as store:
        assert store.verify_integrity() == 6

    for name, mutate in (
        ("revision", lambda doc: doc.__setitem__("experimentRevision", 2)),
        (
            "attempt",
            lambda doc: doc["target"].__setitem__("attemptId", "attempt.other"),
        ),
    ):
        database = tmp_path / f"{name}.db"
        _seed_running(database)
        document = load_document(ATTEMPT_REQUEST)
        mutate(document)
        request = _write_json(tmp_path / f"{name}.json", document)
        assert _cancel(request, database) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.out == ""
        assert json.loads(output.err)["kind"] == "ProblemReport"
        with EventStore(database, create=False) as store:
            assert store.verify_integrity() == 4


def test_duplicate_event_id_is_not_retried_or_rewritten(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    document = load_document(RUN_REQUEST)
    document["event"]["id"] = "evt.1.run.queued"
    request = _write_json(tmp_path / "duplicate.json", document)
    assert _cancel(request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["type"] == "DuplicateEventError"
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 4


def test_hostile_unknown_field_does_not_echo_key_or_value(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    document = load_document(RUN_REQUEST)
    document["secret-field\n\x1b[31m"] = "sk-secret-value"
    request = _write_json(tmp_path / "hostile.json", document)
    assert _cancel(request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    problem = json.loads(output.err)
    assert problem["errors"][0]["path"] == ""
    assert "secret-field" not in output.err
    assert "sk-secret-value" not in output.err
    assert "\x1b" not in output.err
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 4


def test_target_union_error_path_points_to_source_document(
    tmp_path: Path,
    capsys: object,
) -> None:
    document = load_document(ATTEMPT_REQUEST)
    document["target"].pop("attemptId")
    request = _write_json(tmp_path / "missing-attempt.json", document)
    database = tmp_path / "missing.db"
    assert _cancel(request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["path"] == "/target/attemptId"
    assert not database.exists()


def test_hostile_target_tag_is_not_echoed(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    document = load_document(RUN_REQUEST)
    document["target"]["kind"] = "secret-target\n\x1b[31m"
    request = _write_json(tmp_path / "hostile-target.json", document)
    assert _cancel(request, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["path"] == "/target"
    assert problem["errors"][0]["message"] == (
        "Input should select a supported cancellation target"
    )
    assert "secret-target" not in output.err
    assert "\x1b" not in output.err
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 4


def test_corrupt_database_is_not_modified_or_reported_as_cancelled(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    database.write_bytes(b"not sqlite")
    before = database.read_bytes()
    assert _cancel(RUN_REQUEST, database) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert output.out == ""
    assert problem["errors"][0]["type"] == "EventStoreSchemaError"
    assert database.read_bytes() == before


def test_concurrent_requests_share_old_head_and_one_conflicts(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    database = tmp_path / "research.db"
    _seed_running(database)
    first = load_run_cancellation_request(RUN_REQUEST)
    second_document = load_document(RUN_REQUEST)
    second_document["event"]["id"] = "evt.8.run.cancel.requested"
    second = type(first).model_validate(second_document)
    barrier = Barrier(2, timeout=5)
    original_append = EventStore.append

    def synchronized_append(
        store: EventStore,
        document: dict[str, Any],
        *,
        expected_last_sequence: int | None = None,
    ) -> object:
        barrier.wait()
        return original_append(
            store,
            document,
            expected_last_sequence=expected_last_sequence,
        )

    monkeypatch.setattr(EventStore, "append", synchronized_append)  # type: ignore[attr-defined]

    def submit(request: object) -> str:
        with EventStore(database, require_existing=True) as store:
            try:
                request_cancellation(store, request)  # type: ignore[arg-type]
            except EventSequenceConflictError:
                return "conflict"
            return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(submit, (first, second)))
    assert outcomes == ["conflict", "ok"]
    with EventStore(database, create=False) as store:
        assert store.verify_integrity() == 5
