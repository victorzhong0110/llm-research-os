"""Local SQLite append-only storage for validated ResearchEvent facts."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from types import TracebackType
from typing import Any, Self, cast

from pydantic import ValidationError

from llm_research_os.canonical import legacy_canonical_json, legacy_content_digest
from llm_research_os.events.models import CLOUD_EVENTS_INTEGER_MAX, validate_event_document
from llm_research_os.storage.errors import (
    DuplicateEventError,
    EventAppendError,
    EventIntegrityError,
    EventSequenceConflictError,
    EventStoreError,
    EventStoreSchemaError,
)
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.schema import (
    APPLICATION_ID,
    EXPECTED_SCHEMA_DEFINITIONS,
    EXPECTED_SCHEMA_OBJECTS,
    MIGRATION_NAME,
    MIGRATION_STATEMENTS,
    SCHEMA_DEFINITION_DIGEST,
    SCHEMA_VERSION,
    normalize_schema_sql,
)

DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0
MAX_READ_PAGE_SIZE = 1_000
_MAX_WAL_RETRY_DELAY_SECONDS = 0.05
_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})
_SELECT_EVENT_COLUMNS = """
    SELECT sequence, event_id, stream_id, stream_version, event_type,
           occurred_at, recorded_at, project_id, run_id, attempt_id,
           correlation_id, causation_id, schema_version, event_json, event_digest
    FROM events
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _recorded_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventStoreError("event-store clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_expected_last_sequence(value: int | None) -> int | None:
    """Reject illegal CAS tokens before opening the append transaction."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected_last_sequence must be an integer")
    if value < 0 or value > CLOUD_EVENTS_INTEGER_MAX:
        raise ValueError("expected_last_sequence is outside the supported sequence range")
    return value


def _validate_database_path(path: str | Path) -> tuple[Path, bool]:
    source = Path(path).absolute()
    if str(path) == ":memory:":
        raise EventStoreSchemaError("the M0 event store requires a local filesystem path")

    try:
        metadata = os.lstat(source)
    except FileNotFoundError:
        parent = source.parent
        if not parent.is_dir():
            raise EventStoreSchemaError(
                f"database parent directory does not exist: {parent}"
            ) from None
        return source, True
    except OSError as exc:
        raise EventStoreSchemaError(f"could not inspect database path: {source}") from exc

    if stat.S_ISLNK(metadata.st_mode):
        raise EventStoreSchemaError(f"database path must not be a symbolic link: {source}")
    if not stat.S_ISREG(metadata.st_mode):
        raise EventStoreSchemaError(f"database path must be a regular file: {source}")
    return source, False


def _connect_sqlite(
    path: Path,
    *,
    create: bool,
    require_existing: bool,
    is_new: bool,
    timeout_seconds: float,
) -> sqlite3.Connection:
    if require_existing:
        if is_new:
            raise EventStoreSchemaError(f"database does not exist: {path}")
        try:
            return sqlite3.connect(
                f"{path.as_uri()}?mode=rw",
                timeout=timeout_seconds,
                autocommit=True,
                uri=True,
            )
        except sqlite3.OperationalError as exc:
            raise EventStoreSchemaError(f"could not open database for writing: {path}") from exc
    if create:
        return sqlite3.connect(path, timeout=timeout_seconds, autocommit=True)
    try:
        return sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            timeout=timeout_seconds,
            autocommit=True,
            uri=True,
        )
    except sqlite3.OperationalError as exc:
        if is_new:
            raise EventStoreSchemaError(f"database does not exist: {path}") from exc
        raise EventStoreSchemaError(f"could not open database: {path}") from exc


class EventStore:
    """A single-connection local event store.

    Callers provide every ResearchEvent field except ``sequence``, ``sequencetype`` and
    ``streamversion``. The store assigns those three fields atomically and returns the
    complete external-contract event that was persisted. Optional
    ``expected_last_sequence`` is a Python API precondition on the global event head,
    not a ResearchEvent field.

    ``EventStore(path)`` creates a versioned database when the path does not exist.
    ``EventStore(path, create=False)`` opens an existing database with SQLite
    ``mode=ro`` and fails without creating a file if the path is missing.
    ``EventStore(path, require_existing=True)`` opens an existing database with
    SQLite ``mode=rw`` and likewise refuses to create a missing path.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        create: bool = True,
        require_existing: bool = False,
        timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if type(require_existing) is not bool:
            raise TypeError("require_existing must be a boolean")
        if require_existing and not create:
            raise ValueError("require_existing=True cannot be combined with create=False")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._path, is_new = _validate_database_path(path)
        self._clock = clock
        try:
            self._connection = _connect_sqlite(
                self._path,
                create=create,
                require_existing=require_existing,
                is_new=is_new,
                timeout_seconds=timeout_seconds,
            )
            self._connection.row_factory = sqlite3.Row
            if create and is_new:
                os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            if require_existing:
                self._configure_connection_guards(timeout_seconds)
                self._initialize_or_verify_schema(allow_create=False)
                self._configure_connection_durability(timeout_seconds)
            else:
                self._configure_connection(timeout_seconds)
                self._initialize_or_verify_schema(allow_create=create)
        except sqlite3.Error as exc:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise EventStoreSchemaError(
                f"could not initialize event-store database: {self._path}"
            ) from exc
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    @property
    def path(self) -> Path:
        """Return the absolute database path."""

        return self._path

    @property
    def schema_version(self) -> int:
        """Return the supported database schema version."""

        return SCHEMA_VERSION

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._connection.close()

    def _configure_connection(self, timeout_seconds: float) -> None:
        self._configure_connection_guards(timeout_seconds)
        self._configure_connection_durability(timeout_seconds)

    def _configure_connection_guards(self, timeout_seconds: float) -> None:
        busy_timeout_ms = max(1, int(timeout_seconds * 1_000))
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA recursive_triggers = ON")
        self._connection.execute("PRAGMA trusted_schema = OFF")

    def _configure_connection_durability(self, timeout_seconds: float) -> None:
        self._connection.execute("PRAGMA synchronous = FULL")
        journal_mode = self._enable_wal(timeout_seconds)
        if journal_mode.lower() != "wal":
            raise EventStoreSchemaError("database does not support required SQLite WAL mode")
        foreign_keys = cast(
            int,
            self._connection.execute("PRAGMA foreign_keys").fetchone()[0],
        )
        if foreign_keys != 1:
            raise EventStoreSchemaError("SQLite foreign-key enforcement could not be enabled")

    def _enable_wal(self, timeout_seconds: float) -> str:
        """Enable WAL, retrying SQLite lock contention within the configured timeout."""

        deadline = monotonic() + timeout_seconds
        retry_delay = 0.001
        while True:
            try:
                row = self._connection.execute("PRAGMA journal_mode = WAL").fetchone()
                if row is None:
                    raise EventStoreSchemaError("SQLite returned no journal mode")
                return cast(str, row[0])
            except sqlite3.OperationalError as exc:
                error_code = getattr(exc, "sqlite_errorcode", None)
                primary_code = error_code & 0xFF if isinstance(error_code, int) else None
                if primary_code not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise EventStoreSchemaError("timed out while enabling SQLite WAL mode") from exc
                sleep(min(retry_delay, remaining))
                retry_delay = min(retry_delay * 2, _MAX_WAL_RETRY_DELAY_SECONDS)

    @contextmanager
    def _immediate_transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _initialize_or_verify_schema(self, *, allow_create: bool) -> None:
        application_id = cast(
            int,
            self._connection.execute("PRAGMA application_id").fetchone()[0],
        )
        if application_id == 0:
            # A concurrent creator may commit between separate header/schema reads.
            # Let the serialized transaction below re-check both from one write slot.
            if not allow_create:
                raise EventStoreSchemaError(
                    "database is not an initialized LLM Research OS event store"
                )
            self._create_schema()
        elif application_id != APPLICATION_ID:
            raise EventStoreSchemaError(
                f"database is not an LLM Research OS event store (application_id={application_id})"
            )
        self._verify_schema()

    def _create_schema(self) -> None:
        applied_at = _recorded_timestamp(self._clock())
        with self._immediate_transaction():
            application_id = cast(
                int,
                self._connection.execute("PRAGMA application_id").fetchone()[0],
            )
            objects = self._schema_objects()
            if application_id == APPLICATION_ID and objects:
                return
            if application_id != 0 or objects:
                raise EventStoreSchemaError(
                    "database is not an LLM Research OS event store "
                    f"(application_id={application_id})"
                )
            for statement in MIGRATION_STATEMENTS:
                self._connection.execute(statement)
            self._connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at, schema_digest)
                VALUES (?, ?, ?, ?)
                """,
                (SCHEMA_VERSION, MIGRATION_NAME, applied_at, SCHEMA_DEFINITION_DIGEST),
            )
            self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _schema_objects(self) -> frozenset[tuple[str, str]]:
        rows = self._connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        return frozenset((cast(str, row[0]), cast(str, row[1])) for row in rows)

    def _verify_schema(self) -> None:
        application_id = cast(
            int,
            self._connection.execute("PRAGMA application_id").fetchone()[0],
        )
        user_version = cast(
            int,
            self._connection.execute("PRAGMA user_version").fetchone()[0],
        )
        if application_id != APPLICATION_ID or user_version != SCHEMA_VERSION:
            raise EventStoreSchemaError(
                "unsupported event-store header: "
                f"application_id={application_id}, user_version={user_version}"
            )
        if self._schema_objects() != EXPECTED_SCHEMA_OBJECTS:
            raise EventStoreSchemaError("event-store schema objects do not match version 1")
        definitions = {
            (cast(str, row[0]), cast(str, row[1])): normalize_schema_sql(cast(str, row[2]))
            for row in self._connection.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        if definitions != EXPECTED_SCHEMA_DEFINITIONS:
            raise EventStoreSchemaError("event-store SQL definitions do not match version 1")
        try:
            migrations = self._connection.execute(
                "SELECT version, name, schema_digest FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise EventStoreSchemaError("could not read schema migration history") from exc
        expected = [(SCHEMA_VERSION, MIGRATION_NAME, SCHEMA_DEFINITION_DIGEST)]
        actual = [(cast(int, row[0]), cast(str, row[1]), cast(str, row[2])) for row in migrations]
        if actual != expected:
            raise EventStoreSchemaError("event-store migration history is unsupported or corrupt")
        quick_check = cast(
            str,
            self._connection.execute("PRAGMA quick_check").fetchone()[0],
        )
        if quick_check != "ok":
            raise EventStoreSchemaError(f"SQLite quick_check failed: {quick_check}")

    def append(
        self,
        document: dict[str, Any],
        *,
        expected_last_sequence: int | None = None,
    ) -> StoredEvent:
        """Validate and atomically append one store-sequenced ResearchEvent draft.

        ``expected_last_sequence`` is a Python API precondition, not a ResearchEvent
        field. ``None`` keeps the existing unconditional append. ``0`` requires an
        empty store. A positive Integer requires that exact global ``MAX(sequence)``.
        Conflicts are not retried; the caller must replay and re-validate.
        """

        expected_head = _validate_expected_last_sequence(expected_last_sequence)
        if type(document) is not dict:
            raise EventAppendError("event draft must be a JSON object")
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(document))
        if supplied:
            raise EventAppendError(
                "the event store assigns sequence, sequencetype and streamversion; "
                f"caller supplied: {supplied}"
            )

        preflight_document = dict(document)
        preflight_document.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
        try:
            preflight = validate_event_document(preflight_document)
        except ValidationError as exc:
            raise EventAppendError("event draft failed ResearchEvent validation") from exc

        with self._immediate_transaction():
            if (
                self._connection.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (preflight.id,),
                ).fetchone()
                is not None
            ):
                raise DuplicateEventError(f"event id already exists: {preflight.id}")

            last_sequence = cast(
                int,
                self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM events"
                ).fetchone()[0],
            )
            if expected_head is not None and expected_head != last_sequence:
                raise EventSequenceConflictError(expected_head, last_sequence)
            if last_sequence >= CLOUD_EVENTS_INTEGER_MAX:
                raise EventAppendError("global event sequence is exhausted")
            sequence = last_sequence + 1

            last_stream_version = cast(
                int,
                self._connection.execute(
                    "SELECT COALESCE(MAX(stream_version), -1) FROM events WHERE stream_id = ?",
                    (preflight.streamid,),
                ).fetchone()[0],
            )
            if last_stream_version >= CLOUD_EVENTS_INTEGER_MAX:
                raise EventAppendError(f"event stream version is exhausted: {preflight.streamid}")
            stream_version = last_stream_version + 1

            complete_document = dict(document)
            complete_document.update(
                {
                    "sequence": str(sequence),
                    "sequencetype": "Integer",
                    "streamversion": stream_version,
                }
            )
            try:
                event = validate_event_document(complete_document)
            except ValidationError as exc:
                raise EventAppendError("allocated event failed ResearchEvent validation") from exc

            stored_document = complete_document
            event_json = legacy_canonical_json(stored_document)
            digest = legacy_content_digest(stored_document)
            recorded_at = _recorded_timestamp(self._clock())
            try:
                self._connection.execute(
                    """
                    INSERT INTO events(
                        sequence, event_id, stream_id, stream_version, event_type,
                        occurred_at, recorded_at, project_id, run_id, attempt_id,
                        correlation_id, causation_id, schema_version, event_json, event_digest
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        event.id,
                        event.streamid,
                        event.streamversion,
                        event.type,
                        event.time,
                        recorded_at,
                        event.data.project_id,
                        event.data.run_id,
                        event.data.attempt_id,
                        event.correlationid,
                        event.causationid,
                        event.data.schema_version,
                        event_json,
                        digest,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise EventAppendError("SQLite rejected the append-only event row") from exc

        return StoredEvent(event=event, recorded_at=recorded_at, digest=digest)

    def last_sequence(self) -> int:
        """Return the current global event-head concurrency token.

        An empty store returns ``0``. This reads ``MAX(sequence)``, not an event
        count, and does not replace ``verify_integrity()``.
        """

        try:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events"
            ).fetchone()
        except sqlite3.Error as exc:
            raise EventStoreError("could not read the global event sequence") from exc
        if row is None:
            raise EventStoreError("could not read the global event sequence")
        return cast(int, row[0])

    def get_event(self, event_id: str) -> StoredEvent | None:
        """Read one event by immutable CloudEvents ID and verify its stored representation."""

        row = self._connection.execute(
            f"{_SELECT_EVENT_COLUMNS} WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._stored_event_from_row(row)

    def read_events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[StoredEvent]:
        """Read a bounded page in global append order, verifying every row."""

        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int):
            raise ValueError("after_sequence must be an integer")
        if after_sequence < 0 or after_sequence > CLOUD_EVENTS_INTEGER_MAX:
            raise ValueError("after_sequence is outside the supported sequence range")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_READ_PAGE_SIZE
        ):
            raise ValueError(f"limit must be an integer in 1..{MAX_READ_PAGE_SIZE}")
        rows = self._connection.execute(
            f"{_SELECT_EVENT_COLUMNS} WHERE sequence > ? ORDER BY sequence LIMIT ?",
            (after_sequence, limit),
        ).fetchall()
        return [self._stored_event_from_row(row) for row in rows]

    def verify_integrity(self) -> int:
        """Verify SQLite, schema, ordering, indexes, canonical JSON and every event digest."""

        self._verify_schema()
        integrity_rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        integrity_messages = [cast(str, row[0]) for row in integrity_rows]
        if integrity_messages != ["ok"]:
            raise EventIntegrityError(f"SQLite integrity_check failed: {integrity_messages}")

        cursor = self._connection.execute(f"{_SELECT_EVENT_COLUMNS} ORDER BY sequence")
        expected_sequence = 1
        count = 0
        while rows := cursor.fetchmany(256):
            for row in rows:
                stored = self._stored_event_from_row(row)
                if stored.sequence != expected_sequence:
                    raise EventIntegrityError(
                        "global event sequence is not contiguous: "
                        f"expected {expected_sequence}, found {stored.sequence}"
                    )
                expected_sequence += 1
                count += 1
        return count

    def _stored_event_from_row(self, row: sqlite3.Row) -> StoredEvent:
        event_json = cast(str, row["event_json"])
        try:
            decoded: object = json.loads(event_json)
            if not isinstance(decoded, dict):
                raise ValueError("stored event JSON root is not an object")
            document = cast(dict[str, Any], decoded)
            if legacy_canonical_json(document) != event_json:
                raise ValueError("stored event JSON is not canonical")
            event = validate_event_document(document)
        except (UnicodeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise EventIntegrityError("stored event JSON is invalid") from exc

        digest = legacy_content_digest(document)
        stored_digest = cast(str, row["event_digest"])
        if digest != stored_digest:
            raise EventIntegrityError(f"event digest mismatch: {event.id}")

        expected_columns: dict[str, object] = {
            "sequence": int(event.sequence),
            "event_id": event.id,
            "stream_id": event.streamid,
            "stream_version": event.streamversion,
            "event_type": event.type,
            "occurred_at": event.time,
            "project_id": event.data.project_id,
            "run_id": event.data.run_id,
            "attempt_id": event.data.attempt_id,
            "correlation_id": event.correlationid,
            "causation_id": event.causationid,
            "schema_version": event.data.schema_version,
        }
        mismatched = sorted(
            name for name, expected in expected_columns.items() if row[name] != expected
        )
        if mismatched:
            raise EventIntegrityError(
                f"event index columns disagree with canonical JSON for {event.id}: {mismatched}"
            )

        recorded_at = cast(str, row["recorded_at"])
        try:
            parsed_recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            canonical_recorded_at = _recorded_timestamp(parsed_recorded_at)
        except ValueError as exc:
            raise EventIntegrityError(f"recorded_at is invalid for {event.id}") from exc
        except EventStoreError as exc:
            raise EventIntegrityError(f"recorded_at is invalid for {event.id}") from exc
        if canonical_recorded_at != recorded_at:
            raise EventIntegrityError(f"recorded_at is not canonical UTC for {event.id}")
        return StoredEvent(event=event, recorded_at=recorded_at, digest=digest)
