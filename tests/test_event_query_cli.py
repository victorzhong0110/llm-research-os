from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from llm_research_os.cli import main
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore
from llm_research_os.storage.schema import MIGRATION_STATEMENTS

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


def _event_draft(
    index: int = 1,
    *,
    event_type: str = "run.started",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = load_document(EXAMPLES / "valid" / "minimal.json")
    document.pop("sequence")
    document.pop("sequencetype")
    document.pop("streamversion")
    document["id"] = f"evt.store.{index}"
    document["type"] = event_type
    document["streamid"] = "project.example"
    document["time"] = f"2026-08-28T06:00:{index % 60:02d}Z"
    data = document["data"]
    assert isinstance(data, dict)
    data["projectId"] = "project.example"
    if payload is not None:
        data["payload"] = payload
    return document


def _trigger_statement(name: str) -> str:
    marker = f"CREATE TRIGGER {name}"
    return next(statement for statement in MIGRATION_STATEMENTS if marker in statement)


def _populate(database: Path, count: int = 3) -> None:
    with EventStore(database) as store:
        for index in range(1, count + 1):
            event_type = "run.started" if index % 2 else "run.heartbeat"
            store.append(_event_draft(index, event_type=event_type))


def _fingerprint(database: Path) -> tuple[int, list[str]]:
    with EventStore(database, create=False) as store:
        events = store.read_events(after_sequence=0, limit=1000)
        return store.verify_integrity(), [item.event.sequence for item in events]


def test_events_get_json_preserves_aliases_and_explicit_nulls(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        draft = _event_draft()
        draft["correlationid"] = None
        data = draft["data"]
        assert isinstance(data, dict)
        data["runId"] = None
        store.append(draft)

    assert main(["events", "get", str(database), "evt.store.1", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["id"] == "evt.store.1"
    assert payload["specversion"] == "1.0"
    assert "schemaVersion" in payload["data"]
    assert "schema_version" not in payload["data"]
    assert payload["correlationid"] is None
    assert payload["data"]["runId"] is None
    assert payload["sequence"] == "1"


def test_events_get_missing_event_returns_one(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=1)
    assert main(["events", "get", str(database), "evt.missing", "--format", "json"]) == 1
    problem = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert problem["kind"] == "ProblemReport"
    assert problem["errors"][0]["type"] == "event-not-found"


def test_events_list_honors_limit_and_after_sequence(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=5)
    assert (
        main(
            [
                "events",
                "list",
                str(database),
                "--after-sequence",
                "2",
                "--limit",
                "2",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert [event["sequence"] for event in payload["events"]] == ["3", "4"]

    assert (
        main(
            [
                "events",
                "list",
                str(database),
                "--after-sequence",
                "5",
                "--format",
                "json",
            ]
        )
        == 0
    )
    empty = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert empty["events"] == []


def test_events_list_rejects_invalid_bounds(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=1)
    assert main(["events", "list", str(database), "--limit", "0", "--format", "json"]) == 2
    problem = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert problem["kind"] == "ProblemReport"
    assert main(["events", "list", str(database), "--after-sequence", "-1"]) == 2
    assert main(["events", "list", str(database), "--limit", "1001"]) == 2


def test_events_replay_pages_each_event_once(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=5)
    assert main(["events", "replay", str(database), "--page-size", "2"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line]  # type: ignore[attr-defined]
    events = [json.loads(line) for line in lines]
    assert [event["sequence"] for event in events] == ["1", "2", "3", "4", "5"]
    assert len({event["id"] for event in events}) == 5
    assert all("schemaVersion" in event["data"] for event in events)

    assert (
        main(["events", "replay", str(database), "--after-sequence", "3", "--page-size", "2"]) == 0
    )
    remaining = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()  # type: ignore[attr-defined]
        if line
    ]
    assert [event["sequence"] for event in remaining] == ["4", "5"]


def test_empty_database_query_commands(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert main(["events", "list", str(database), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"events": []}  # type: ignore[attr-defined]
    assert main(["events", "replay", str(database)]) == 0
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]
    assert main(["events", "verify", str(database), "--format", "json"]) == 0
    verify = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert verify == {"eventCount": 0, "valid": True}
    assert main(["events", "get", str(database), "evt.store.1"]) == 1


def test_missing_database_is_not_created(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "missing.db"
    assert main(["events", "list", str(database), "--format", "json"]) == 2
    problem = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert problem["kind"] == "ProblemReport"
    assert not database.exists()
    assert list(tmp_path.iterdir()) == []
    assert main(["events", "get", str(database), "evt.store.1", "--format", "json"]) == 2
    assert not database.exists()
    assert main(["events", "replay", str(database)]) == 2
    assert not database.exists()
    assert main(["events", "verify", str(database), "--format", "json"]) == 2
    assert not database.exists()
    assert list(tmp_path.iterdir()) == []


def test_verify_reports_count_and_fails_on_gaps(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=2)
    assert main(["events", "verify", str(database), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload == {"eventCount": 2, "valid": True}

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.execute(_trigger_statement("events_reject_delete"))

    assert main(["events", "verify", str(database), "--format", "json"]) == 2
    problem = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert problem["kind"] == "ProblemReport"
    assert "contiguous" in problem["errors"][0]["message"]


def test_query_commands_fail_on_digest_mismatch(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=1)
    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = 1",
            ("sha256:" + ("0" * 64),),
        )
        connection.execute(_trigger_statement("events_reject_update"))

    assert main(["events", "get", str(database), "evt.store.1", "--format", "json"]) == 2
    assert "digest" in json.loads(capsys.readouterr().err)["errors"][0]["message"]  # type: ignore[attr-defined]
    assert main(["events", "list", str(database), "--format", "json"]) == 2
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["events", "replay", str(database)]) == 2
    problem = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert problem["kind"] == "ProblemReport"


def test_text_event_output_escapes_control_characters(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    dangerous = "hello\x1b]52;c;payload\x07\nINJECTED"
    with EventStore(database) as store:
        store.append(_event_draft(payload={"note": dangerous}))

    assert main(["events", "get", str(database), "evt.store.1"]) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert "\\u001b]52;c;payload\\u0007\\nINJECTED" in output.out
    assert "\x1b" not in output.out
    assert "\nINJECTED" not in output.out


def test_query_commands_do_not_change_event_count_or_sequence(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=4)
    before = _fingerprint(database)
    commands = (
        ["events", "get", str(database), "evt.store.2", "--format", "json"],
        ["events", "list", str(database), "--limit", "2", "--format", "json"],
        ["events", "replay", str(database), "--page-size", "1"],
        ["events", "verify", str(database), "--format", "json"],
        ["events", "get", str(database), "evt.missing", "--format", "json"],
    )
    for command in commands:
        main(command)
        capsys.readouterr()  # type: ignore[attr-defined]
        assert _fingerprint(database) == before


def test_corrupt_database_returns_problem_report_for_all_event_commands(
    tmp_path: Path,
    capsys: object,
) -> None:
    database = tmp_path / "corrupt.db"
    payload = b"not a SQLite database\x00\xff arbitrary bytes"
    database.write_bytes(payload)
    before = database.stat().st_mtime_ns
    commands = (
        ["events", "get", str(database), "evt.store.1", "--format", "json"],
        ["events", "list", str(database), "--format", "json"],
        ["events", "replay", str(database)],
        ["events", "verify", str(database), "--format", "json"],
    )
    for command in commands:
        assert main(command) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.out == ""
        assert "Traceback" not in output.err
        assert "DatabaseError" not in output.err
        problem = json.loads(output.err)
        assert problem["kind"] == "ProblemReport"
        assert problem["valid"] is False
        assert database.read_bytes() == payload
        assert database.stat().st_mtime_ns == before
        assert list(tmp_path.iterdir()) == [database]


def test_replay_sequence_gap_fails_before_any_output(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    _populate(database, count=2)
    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.execute(_trigger_statement("events_reject_delete"))

    assert main(["events", "replay", str(database)]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    problem = json.loads(output.err)
    assert problem["kind"] == "ProblemReport"
    assert "contiguous" in problem["errors"][0]["message"]
