from __future__ import annotations

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.spec.io import load_document
from llm_research_os.storage import (
    DuplicateEventError,
    EventAppendError,
    EventIntegrityError,
    EventStore,
    EventStoreError,
    EventStoreSchemaError,
)
from llm_research_os.storage.schema import (
    APPLICATION_ID,
    MIGRATION_NAME,
    MIGRATION_STATEMENTS,
    SCHEMA_DEFINITION_DIGEST,
    SCHEMA_VERSION,
)

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"
FIXED_TIME = datetime(2026, 8, 28, 6, 0, 0, 123456, tzinfo=UTC)


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
        migration = connection.execute(
            "SELECT version, name, schema_digest FROM schema_migrations"
        ).fetchone()
        assert migration == (SCHEMA_VERSION, MIGRATION_NAME, SCHEMA_DEFINITION_DIGEST)

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
        assert first.digest == content_digest(
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
    ("after_sequence", "limit"),
    [(-1, 10), (True, 10), (0, 0), (0, 1_001), (0, True)],
)
def test_reads_reject_invalid_bounds(
    tmp_path: Path,
    after_sequence: int,
    limit: int,
) -> None:
    with EventStore(tmp_path / "research.db", clock=_clock) as store, pytest.raises(ValueError):
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
            (content_digest(document), "rewritten.type"),
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
        canonical_json(document),
        content_digest(document),
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


def test_default_constructor_still_creates_a_new_database(tmp_path: Path) -> None:
    database = tmp_path / "created.db"
    with EventStore(database, clock=_clock) as store:
        assert store.verify_integrity() == 0
    assert database.is_file()
