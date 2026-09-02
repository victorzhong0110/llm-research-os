"""Versioned SQLite schema for the M0 append-only event source."""

from __future__ import annotations

from llm_research_os.canonical import legacy_content_digest

APPLICATION_ID = 0x4C524F53  # ASCII "LROS"
SCHEMA_VERSION = 1
MIGRATION_NAME = "m0-append-only-events"

MIGRATION_STATEMENTS = (
    """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        applied_at TEXT NOT NULL,
        schema_digest TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE events (
        sequence INTEGER PRIMARY KEY
            CHECK (sequence BETWEEN 1 AND 2147483647),
        event_id TEXT NOT NULL UNIQUE,
        stream_id TEXT NOT NULL,
        stream_version INTEGER NOT NULL
            CHECK (stream_version BETWEEN 0 AND 2147483647),
        event_type TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        project_id TEXT NOT NULL,
        run_id TEXT,
        attempt_id TEXT,
        correlation_id TEXT,
        causation_id TEXT,
        schema_version TEXT NOT NULL,
        event_json TEXT NOT NULL CHECK (json_valid(event_json)),
        event_digest TEXT NOT NULL CHECK (
            length(event_digest) = 71
            AND substr(event_digest, 1, 7) = 'sha256:'
            AND substr(event_digest, 8) NOT GLOB '*[^0-9a-f]*'
        ),
        UNIQUE (stream_id, stream_version)
    ) STRICT
    """,
    "CREATE INDEX events_stream_sequence_idx ON events (stream_id, sequence)",
    "CREATE INDEX events_type_sequence_idx ON events (event_type, sequence)",
    "CREATE INDEX events_project_sequence_idx ON events (project_id, sequence)",
    """
    CREATE TRIGGER events_reject_update
    BEFORE UPDATE ON events
    BEGIN
        SELECT RAISE(ABORT, 'events are append-only and cannot be updated');
    END
    """,
    """
    CREATE TRIGGER events_reject_delete
    BEFORE DELETE ON events
    BEGIN
        SELECT RAISE(ABORT, 'events are append-only and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER events_reject_replacement
    BEFORE INSERT ON events
    WHEN EXISTS (
        SELECT 1
        FROM events
        WHERE sequence = NEW.sequence
           OR event_id = NEW.event_id
           OR (stream_id = NEW.stream_id AND stream_version = NEW.stream_version)
    )
    BEGIN
        SELECT RAISE(ABORT, 'events are append-only and cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER schema_migrations_reject_update
    BEFORE UPDATE ON schema_migrations
    BEGIN
        SELECT RAISE(ABORT, 'schema migration history cannot be updated');
    END
    """,
    """
    CREATE TRIGGER schema_migrations_reject_delete
    BEFORE DELETE ON schema_migrations
    BEGIN
        SELECT RAISE(ABORT, 'schema migration history cannot be deleted');
    END
    """,
)


def normalize_schema_sql(value: str) -> str:
    """Normalize insignificant SQL whitespace for schema-definition comparison."""

    return " ".join(value.split())


def _schema_object_key(statement: str) -> tuple[str, str]:
    words = normalize_schema_sql(statement).split(" ", 3)
    return words[1].lower(), words[2]


EXPECTED_SCHEMA_DEFINITIONS = {
    _schema_object_key(statement): normalize_schema_sql(statement)
    for statement in MIGRATION_STATEMENTS
}
SCHEMA_DEFINITION_DIGEST = legacy_content_digest(
    [normalize_schema_sql(statement) for statement in MIGRATION_STATEMENTS]
)

EXPECTED_SCHEMA_OBJECTS = frozenset(EXPECTED_SCHEMA_DEFINITIONS)
