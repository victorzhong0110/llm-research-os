from __future__ import annotations

import json
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from llm_research_os.canonical import legacy_canonical_json, legacy_content_digest
from llm_research_os.spec.io import load_document
from llm_research_os.storage import (
    DuplicateEventError,
    EventAppendError,
    EventIntegrityError,
    EventSequenceConflictError,
    EventStore,
    EventStoreError,
    EventStoreSchemaError,
)
from llm_research_os.storage.schema import (
    APPLICATION_ID,
    EXPECTED_SCHEMA_DEFINITIONS,
    EXPECTED_SCHEMA_OBJECTS,
    MIGRATION_STATEMENTS,
    SCHEMA_DEFINITION_DIGEST,
    SCHEMA_VERSION,
    V1_MIGRATION,
    expected_migration_history,
    normalize_schema_sql,
)

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"
FIXED_TIME = datetime(2026, 8, 28, 6, 0, 0, 123456, tzinfo=UTC)
FROZEN_SCHEMA_DEFINITION_DIGEST = (
    "sha256:426fff7eaf173d703e1c0910b1237558bf99aac4d187a39f96bab55a563e202b"
)
FROZEN_V1_MIGRATION_DIGEST = (
    "sha256:dfdfe1bc8233723bfd164f488779428eeae72e4d4b0efa7128abf25e333bd1f1"
)


def _clock() -> datetime:
    return FIXED_TIME


def _event_draft(index: int = 1, *, stream_id: str = "project.example") -> dict[str, Any]:
    document = load_document(EXAMPLES / "valid" / "minimal.json")
    document.pop("sequence")
    document.pop("sequencetype")
    document.pop("streamversion")
    document["id"] = f"evt.store.{index}"
    document["streamid"] = stream_id
    document["time"] = f"2026-08-28T06:00:{index % 60:02d}Z"
    data = document["data"]
    assert isinstance(data, dict)
    data["projectId"] = "project.example"
    return document


def _trigger_statement(name: str) -> str:
    marker = f"CREATE TRIGGER {name}"
    return next(statement for statement in MIGRATION_STATEMENTS if marker in statement)


def test_store_initializes_versioned_wal_database_and_reopens(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        assert store.path == database
        assert store.schema_version == SCHEMA_VERSION
        assert store.verify_integrity() == 0
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    assert stat.S_IMODE(database.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        migrations = connection.execute(
            "SELECT version, name, schema_digest FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [tuple(row) for row in migrations] == expected_migration_history()
        assert SCHEMA_DEFINITION_DIGEST == FROZEN_SCHEMA_DEFINITION_DIGEST
        assert V1_MIGRATION.digest == FROZEN_V1_MIGRATION_DIGEST
        assert SCHEMA_DEFINITION_DIGEST.startswith("sha256:")
        assert not SCHEMA_DEFINITION_DIGEST.startswith("jcs-sha256:")

    with EventStore(database, clock=_clock) as reopened:
        assert reopened.verify_integrity() == 0


def test_append_assigns_global_sequence_and_per_stream_version(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    first_draft = _event_draft(1)
    with EventStore(database, clock=_clock) as store:
        first = store.append(first_draft)
        second = store.append(_event_draft(2))
        other_stream = store.append(_event_draft(3, stream_id="run.other"))

        assert (first.sequence, second.sequence, other_stream.sequence) == (1, 2, 3)
        assert (first.stream_version, second.stream_version) == (0, 1)
        assert other_stream.stream_version == 0
        assert first.event.sequence == "1"
        assert first.event.sequencetype == "Integer"
        assert first.recorded_at == "2026-08-28T06:00:00.123456Z"
        assert first.digest == legacy_content_digest(
            first.event.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        assert store.verify_integrity() == 3

    assert not {"sequence", "sequencetype", "streamversion"}.intersection(first_draft)


def test_store_rejects_caller_owned_sequence_fields(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        for field, value in (
            ("sequence", "1"),
            ("sequencetype", "Integer"),
            ("streamversion", 0),
        ):
            draft = _event_draft()
            draft[field] = value
            with pytest.raises(EventAppendError, match="event store assigns"):
                store.append(draft)
        assert store.verify_integrity() == 0


def test_invalid_and_duplicate_appends_do_not_consume_sequence(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        invalid = _event_draft(1)
        data = invalid["data"]
        assert isinstance(data, dict)
        data["payload"] = {"artifact": {"body": "inline"}}
        with pytest.raises(EventAppendError, match="failed ResearchEvent validation"):
            store.append(invalid)

        first = store.append(_event_draft(1))
        with pytest.raises(DuplicateEventError, match=r"evt\.store\.1"):
            store.append(_event_draft(1, stream_id="different.stream"))
        second = store.append(_event_draft(2))

        assert first.sequence == 1
        assert second.sequence == 2
        assert store.verify_integrity() == 2


def test_bounded_reads_verify_and_preserve_global_order(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        for index in range(1, 6):
            store.append(_event_draft(index))

        assert store.get_event("missing") is None
        assert store.get_event("evt.store.3").sequence == 3
        assert [item.sequence for item in store.read_events(limit=2)] == [1, 2]
        assert [item.sequence for item in store.read_events(after_sequence=2, limit=3)] == [3, 4, 5]
        assert store.read_events(after_sequence=5) == []


@pytest.mark.parametrize(
    ("after_sequence", "limit", "match"),
    [
        (-1, 10, "after_sequence is outside the supported sequence range"),
        (True, 10, "after_sequence must be an integer"),
        (0, 0, r"limit must be an integer in 1\.\."),
        (0, 1_001, r"limit must be an integer in 1\.\."),
        (0, True, r"limit must be an integer in 1\.\."),
    ],
)
def test_reads_reject_invalid_bounds(
    tmp_path: Path,
    after_sequence: int,
    limit: int,
    match: str,
) -> None:
    with (
        EventStore(tmp_path / "research.db", clock=_clock) as store,
        pytest.raises(ValueError, match=match),
    ):
        store.read_events(after_sequence=after_sequence, limit=limit)


def test_append_only_triggers_reject_update_delete_and_replace(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft())

    with sqlite3.connect(database, autocommit=True) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="cannot be updated"):
            connection.execute("UPDATE events SET event_type = 'rewritten' WHERE sequence = 1")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute("DELETE FROM events WHERE sequence = 1")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
            connection.execute(
                "INSERT OR REPLACE INTO events SELECT * FROM events WHERE sequence = 1"
            )

    with EventStore(database, clock=_clock) as store:
        assert store.verify_integrity() == 1


def test_read_detects_tampered_json_even_when_trigger_is_restored(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft())

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute("UPDATE events SET event_json = '{}' WHERE sequence = 1")
        connection.execute(_trigger_statement("events_reject_update"))

    with (
        EventStore(database, clock=_clock) as store,
        pytest.raises(EventIntegrityError, match="stored event JSON is invalid"),
    ):
        store.get_event("evt.store.1")


def test_read_detects_tampered_digest_and_index_columns(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft())

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = 1",
            ("sha256:" + ("0" * 64),),
        )
        connection.execute(_trigger_statement("events_reject_update"))

    with (
        EventStore(database, clock=_clock) as store,
        pytest.raises(EventIntegrityError, match="event digest mismatch"),
    ):
        store.get_event("evt.store.1")

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        document = _event_draft()
        document.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
        connection.execute(
            "UPDATE events SET event_digest = ?, event_type = ? WHERE sequence = 1",
            (legacy_content_digest(document), "rewritten.type"),
        )
        connection.execute(_trigger_statement("events_reject_update"))

    with (
        EventStore(database, clock=_clock) as store,
        pytest.raises(EventIntegrityError, match="index columns disagree"),
    ):
        store.get_event("evt.store.1")


def test_integrity_check_detects_sequence_gaps(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1))
        store.append(_event_draft(2))

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.execute(_trigger_statement("events_reject_delete"))

    with (
        EventStore(database, clock=_clock) as store,
        pytest.raises(EventIntegrityError, match="not contiguous"),
    ):
        store.verify_integrity()


def test_unknown_database_and_symlink_paths_fail_closed(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.db"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    with pytest.raises(EventStoreSchemaError, match="not an LLM Research OS event store"):
        EventStore(unrelated)

    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass
    link = tmp_path / "linked.db"
    link.symlink_to(database)
    with pytest.raises(EventStoreSchemaError, match="symbolic link"):
        EventStore(link)


def test_rewritten_same_name_trigger_fails_schema_verification(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute(
            """
            CREATE TRIGGER events_reject_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT 1;
            END
            """
        )

    with pytest.raises(EventStoreSchemaError, match="SQL definitions"):
        EventStore(database, clock=_clock)


def test_store_clock_must_be_timezone_aware(tmp_path: Path) -> None:
    def naive_clock() -> datetime:
        return datetime(2026, 8, 28, 6, 0, 0)

    with pytest.raises(EventStoreError, match="timezone-aware"):
        EventStore(tmp_path / "research.db", clock=naive_clock)


def test_concurrent_connections_allocate_without_duplicates(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass

    def append_one(index: int) -> tuple[int, int]:
        with EventStore(database, clock=_clock) as store:
            stored = store.append(_event_draft(index))
            return stored.sequence, stored.stream_version

    with ThreadPoolExecutor(max_workers=4) as executor:
        assigned = list(executor.map(append_one, range(1, 13)))

    assert sorted(sequence for sequence, _ in assigned) == list(range(1, 13))
    assert sorted(version for _, version in assigned) == list(range(12))
    with EventStore(database, clock=_clock) as store:
        assert store.verify_integrity() == 12
        rows = store.read_events(limit=100)
        assert [row.sequence for row in rows] == list(range(1, 13))


def test_concurrent_first_open_applies_migration_once(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    start = Barrier(4)

    def open_store(_: int) -> int:
        start.wait()
        with EventStore(database, clock=_clock) as store:
            return store.schema_version

    with ThreadPoolExecutor(max_workers=4) as executor:
        versions = list(executor.map(open_store, range(4)))

    assert versions == [SCHEMA_VERSION] * 4
    with EventStore(database, clock=_clock) as store:
        assert store.verify_integrity() == 0


def test_corrupt_database_initialization_wraps_sqlite_error(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"not a SQLite database")

    with pytest.raises(EventStoreSchemaError, match="could not initialize") as captured:
        EventStore(database, clock=_clock)

    assert isinstance(captured.value.__cause__, sqlite3.DatabaseError)


def test_existing_only_open_wraps_corrupt_database_without_modifying_it(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.db"
    payload = b"not a SQLite database\x00\xff"
    database.write_bytes(payload)
    with pytest.raises(EventStoreSchemaError, match="could not initialize") as captured:
        EventStore(database, create=False, clock=_clock)
    assert isinstance(captured.value.__cause__, sqlite3.DatabaseError)
    assert database.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [database]


def test_persisted_json_is_canonical_and_indexed(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        stored = store.append(_event_draft())

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT event_json, event_digest, event_id, stream_id, stream_version,
                   event_type, occurred_at, project_id, schema_version
            FROM events
            """
        ).fetchone()
    assert row is not None
    document = stored.event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert row == (
        legacy_canonical_json(document),
        legacy_content_digest(document),
        stored.event.id,
        stored.event.streamid,
        stored.event.streamversion,
        stored.event.type,
        stored.event.time,
        stored.event.data.project_id,
        stored.event.data.schema_version,
    )


def test_canonical_storage_preserves_explicit_optional_nulls(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    draft = _event_draft()
    draft["correlationid"] = None
    with EventStore(database, clock=_clock) as store:
        stored = store.append(draft)

    with sqlite3.connect(database) as connection:
        event_json = connection.execute("SELECT event_json FROM events").fetchone()[0]
    assert '"correlationid":null' in event_json
    assert stored.event.correlationid is None


def test_existing_only_open_does_not_create_a_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing.db"
    with pytest.raises(EventStoreSchemaError, match="does not exist"):
        EventStore(database, create=False, clock=_clock)
    assert not database.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_only_open_reads_an_initialized_database(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft())
    with EventStore(database, create=False, clock=_clock) as store:
        assert store.get_event("evt.store.1") is not None
        assert store.verify_integrity() == 1


def test_required_existing_writable_open_does_not_create_missing_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.db"
    with pytest.raises(EventStoreSchemaError, match="does not exist"):
        EventStore(database, require_existing=True, clock=_clock)
    assert not database.exists()
    assert list(tmp_path.iterdir()) == []


def test_required_existing_writable_open_appends_to_initialized_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass
    with EventStore(database, require_existing=True, clock=_clock) as store:
        stored = store.append(_event_draft())
        assert stored.sequence == 1
        assert store.verify_integrity() == 1


def test_required_existing_enables_trusted_schema_guard_before_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass
    observed: list[int] = []
    original_verify = EventStore._verify_schema

    def guarded_verify(store: EventStore) -> None:
        observed.append(store._connection.execute("PRAGMA trusted_schema").fetchone()[0])
        original_verify(store)

    monkeypatch.setattr(EventStore, "_verify_schema", guarded_verify)
    with EventStore(database, require_existing=True, clock=_clock):
        pass
    assert observed == [0]


def test_required_existing_writable_open_does_not_initialize_plain_file(
    tmp_path: Path,
) -> None:
    database = tmp_path / "plain.db"
    database.write_bytes(b"")
    with pytest.raises(EventStoreSchemaError, match="not an initialized"):
        EventStore(database, require_existing=True, clock=_clock)
    assert database.read_bytes() == b""


def test_required_existing_and_read_only_modes_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        EventStore(tmp_path / "research.db", create=False, require_existing=True)


def test_default_constructor_still_creates_a_new_database(tmp_path: Path) -> None:
    database = tmp_path / "created.db"
    with EventStore(database, clock=_clock) as store:
        assert store.verify_integrity() == 0
    assert database.is_file()


def _concurrent_appends(
    database: Path,
    *,
    expected_last_sequence: int | None,
    stream_ids: tuple[str, str] = ("project.example", "project.example"),
) -> list[tuple[str, object]]:
    start = Barrier(2, timeout=5)

    def append_one(index: int) -> tuple[str, object]:
        with EventStore(database, clock=_clock) as store:
            start.wait()
            try:
                stored = store.append(
                    _event_draft(index, stream_id=stream_ids[index - 1]),
                    expected_last_sequence=expected_last_sequence,
                )
                return ("ok", stored)
            except EventSequenceConflictError as exc:
                return ("conflict", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(append_one, (1, 2)))


def test_empty_store_accepts_expected_last_sequence_zero(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        assert store.last_sequence() == 0
        stored = store.append(_event_draft(1), expected_last_sequence=0)
        assert stored.event.sequence == "1"
        assert stored.sequence == 1
        assert store.last_sequence() == 1
        assert store.verify_integrity() == 1


def test_append_succeeds_with_current_global_head(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        first = store.append(_event_draft(1), expected_last_sequence=0)
        second = store.append(_event_draft(2), expected_last_sequence=first.sequence)
        assert second.event.sequence == "2"
        assert store.last_sequence() == 2


def test_stale_expected_head_conflicts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1), expected_last_sequence=0)
        with pytest.raises(EventSequenceConflictError) as captured:
            store.append(_event_draft(2), expected_last_sequence=0)
        assert captured.value.expected_last_sequence == 0
        assert captured.value.actual_last_sequence == 1


def test_future_expected_head_conflicts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1), expected_last_sequence=0)
        with pytest.raises(EventSequenceConflictError) as captured:
            store.append(_event_draft(2), expected_last_sequence=2)
        assert captured.value.expected_last_sequence == 2
        assert captured.value.actual_last_sequence == 1
        assert store.last_sequence() == 1


@pytest.mark.parametrize(
    "value",
    [True, False, "1", 1.0, -1, 2_147_483_648],
    ids=["bool-true", "bool-false", "str", "float", "negative", "above-max"],
)
def test_append_rejects_illegal_expected_last_sequence(tmp_path: Path, value: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        with pytest.raises(ValueError, match="expected_last_sequence"):
            store.append(_event_draft(1), expected_last_sequence=value)  # type: ignore[arg-type]
        assert store.last_sequence() == 0
        assert store.verify_integrity() == 0


def test_conflict_does_not_insert_or_advance_stream_or_sequence(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        first = store.append(_event_draft(1), expected_last_sequence=0)
        assert first.stream_version == 0
        with pytest.raises(EventSequenceConflictError):
            store.append(_event_draft(2), expected_last_sequence=0)
        assert store.get_event("evt.store.2") is None
        assert store.last_sequence() == 1
        assert store.verify_integrity() == 1
        retried = store.append(_event_draft(2), expected_last_sequence=1)
        assert retried.event.sequence == "2"
        assert retried.stream_version == 1
        assert store.last_sequence() == 2
        assert store.verify_integrity() == 2


def test_duplicate_event_id_outranks_stale_expected_head(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1), expected_last_sequence=0)
        with pytest.raises(DuplicateEventError, match=r"evt\.store\.1"):
            store.append(_event_draft(1, stream_id="different.stream"), expected_last_sequence=0)
        with pytest.raises(DuplicateEventError, match=r"evt\.store\.1"):
            store.append(_event_draft(1), expected_last_sequence=1)
        assert store.last_sequence() == 1
        assert store.verify_integrity() == 1


def test_concurrent_same_expected_head_exactly_one_wins(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass

    results = _concurrent_appends(database, expected_last_sequence=0)
    successes = [item for kind, item in results if kind == "ok"]
    conflicts = [item for kind, item in results if kind == "conflict"]
    assert len(successes) == 1
    assert len(conflicts) == 1
    stored = successes[0]
    conflict = conflicts[0]
    assert stored.event.sequence == "1"
    assert isinstance(conflict, EventSequenceConflictError)
    assert conflict.expected_last_sequence == 0
    assert conflict.actual_last_sequence == 1

    with EventStore(database, clock=_clock) as store:
        assert store.last_sequence() == 1
        assert store.verify_integrity() == 1
        present = {
            event_id
            for event_id in ("evt.store.1", "evt.store.2")
            if store.get_event(event_id) is not None
        }
        assert len(present) == 1


def test_concurrent_same_head_conflicts_across_different_streams(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass

    results = _concurrent_appends(
        database,
        expected_last_sequence=0,
        stream_ids=("stream.alpha", "stream.beta"),
    )
    successes = [item for kind, item in results if kind == "ok"]
    conflicts = [item for kind, item in results if kind == "conflict"]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert successes[0].stream_version == 0
    assert isinstance(conflicts[0], EventSequenceConflictError)
    assert conflicts[0].expected_last_sequence == 0
    assert conflicts[0].actual_last_sequence == 1

    with EventStore(database, clock=_clock) as store:
        assert store.last_sequence() == 1
        assert store.verify_integrity() == 1
        rows = store.read_events(limit=10)
        assert len(rows) == 1
        assert rows[0].event.streamid in {"stream.alpha", "stream.beta"}


def test_unconditional_append_still_allows_concurrent_writers(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock):
        pass

    results = _concurrent_appends(database, expected_last_sequence=None)
    assert [kind for kind, _ in results] == ["ok", "ok"]
    sequences = sorted(item.sequence for _, item in results)
    assert sequences == [1, 2]

    with EventStore(database, clock=_clock) as store:
        assert store.last_sequence() == 2
        assert store.verify_integrity() == 2


def test_last_sequence_empty_appended_and_reopened(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        assert store.last_sequence() == 0
        store.append(_event_draft(1))
        store.append(_event_draft(2))
        assert store.last_sequence() == 2
    with EventStore(database, clock=_clock) as reopened:
        assert reopened.last_sequence() == 2
    with EventStore(database, create=False, clock=_clock) as readonly:
        assert readonly.last_sequence() == 2


def test_last_sequence_is_max_not_event_count(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1))
        store.append(_event_draft(2))

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.execute(_trigger_statement("events_reject_delete"))

    with EventStore(database, clock=_clock) as store:
        count = store._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1
        assert store.last_sequence() == 2


def test_conflict_attributes_are_structured_and_readonly(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1), expected_last_sequence=0)
        with pytest.raises(EventSequenceConflictError) as captured:
            store.append(_event_draft(2), expected_last_sequence=0)

    error = captured.value
    assert isinstance(error, EventAppendError)
    assert error.expected_last_sequence == 0
    assert error.actual_last_sequence == 1
    with pytest.raises(AttributeError):
        error.expected_last_sequence = 9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        error.actual_last_sequence = 9  # type: ignore[misc]
    assert "SELECT" not in str(error)
    assert "sqlite" not in str(error).lower()


def test_last_sequence_wraps_sqlite_errors(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    store = EventStore(database, clock=_clock)
    store.close()
    with pytest.raises(
        EventStoreError, match="could not read the global event sequence"
    ) as captured:
        store.last_sequence()
    assert isinstance(captured.value.__cause__, sqlite3.Error)
    assert "SELECT" not in str(captured.value)


def test_cas_precondition_does_not_change_schema_or_event_contract(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        stored = store.append(_event_draft(1), expected_last_sequence=0)
        assert store.schema_version == SCHEMA_VERSION
        assert store._schema_objects() == EXPECTED_SCHEMA_OBJECTS
        definitions = {
            (str(row[0]), str(row[1])): normalize_schema_sql(str(row[2]))
            for row in store._connection.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        assert definitions == EXPECTED_SCHEMA_DEFINITIONS
        migrations = store._connection.execute(
            "SELECT version, name, schema_digest FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [tuple(row) for row in migrations] == expected_migration_history()
        assert SCHEMA_DEFINITION_DIGEST == FROZEN_SCHEMA_DEFINITION_DIGEST
        columns = [
            row[1] for row in store._connection.execute("PRAGMA table_info(events)").fetchall()
        ]
        assert "expected_last_sequence" not in columns
        document = stored.event.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert "expected_last_sequence" not in document

    with sqlite3.connect(database) as connection:
        event_json = connection.execute("SELECT event_json FROM events").fetchone()[0]
        persisted = json.loads(event_json)
    assert "expected_last_sequence" not in persisted
    assert persisted["sequence"] == "1"


def _write_v1_database(path: Path) -> None:
    applied_at = "2026-08-28T06:00:00.123456Z"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        for statement in V1_MIGRATION.statements:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, applied_at, schema_digest)
            VALUES (?, ?, ?, ?)
            """,
            (V1_MIGRATION.version, V1_MIGRATION.name, applied_at, V1_MIGRATION.digest),
        )
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()


def test_v1_database_upgrades_to_schema_v2(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _write_v1_database(database)
    with EventStore(database, require_existing=True, clock=_clock) as store:
        assert store.schema_version == SCHEMA_VERSION
        assert store.verify_integrity() == 0
        history = store._connection.execute(
            "SELECT version, name, schema_digest FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [tuple(row) for row in history] == expected_migration_history()
        assert store._schema_objects() == EXPECTED_SCHEMA_OBJECTS


def test_read_only_open_rejects_unmigrated_v1_database(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    _write_v1_database(database)
    with pytest.raises(EventStoreSchemaError, match="writable open to apply migration 2"):
        EventStore(database, create=False, clock=_clock)


def test_matching_checkpoint_skips_full_event_scan(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1))
        calls = {"count": 0}
        original = EventStore.verify_integrity

        def wrapped(self: EventStore) -> int:
            calls["count"] += 1
            return original(self)

        store.verify_integrity = wrapped.__get__(store, EventStore)  # type: ignore[method-assign]
        assert store.freeze_high_water() == 1
        assert calls["count"] == 0


def test_stale_or_tampered_checkpoint_falls_back_to_full_scan(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        first = store.append(_event_draft(1))
        store.append(_event_draft(2))
        store._connection.execute(
            """
            UPDATE integrity_checkpoint
            SET high_water = 1, last_event_digest = ?, verified_event_count = 1
            WHERE slot = 1
            """,
            (first.digest,),
        )
        assert store.freeze_high_water() == 2
        checkpoint = store.read_integrity_checkpoint()
        assert checkpoint is not None
        assert checkpoint.high_water == 2
        assert checkpoint.last_event_digest is not None
        assert checkpoint.last_event_digest != first.digest


def test_truncated_log_invalidates_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        store.append(_event_draft(1))
        store.append(_event_draft(2))
        assert store.freeze_high_water() == 2

    with sqlite3.connect(database, autocommit=True) as connection:
        connection.execute("DROP TRIGGER events_reject_delete")
        connection.execute("DELETE FROM events WHERE sequence = 2")
        connection.execute(_trigger_statement("events_reject_delete"))

    with EventStore(database, clock=_clock) as store:
        assert store.freeze_high_water() == 1
        checkpoint = store.read_integrity_checkpoint()
        assert checkpoint is not None
        assert checkpoint.high_water == 1


def test_wrong_schema_digest_on_checkpoint_forces_rescan(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database, clock=_clock) as store:
        stored = store.append(_event_draft(1))
        store._connection.execute(
            """
            UPDATE integrity_checkpoint
            SET schema_digest = ?
            WHERE slot = 1
            """,
            ("sha256:" + "ab" * 32,),
        )
        assert store.freeze_high_water() == 1
        checkpoint = store.read_integrity_checkpoint()
        assert checkpoint is not None
        assert checkpoint.schema_digest == SCHEMA_DEFINITION_DIGEST
        assert checkpoint.last_event_digest == stored.digest
