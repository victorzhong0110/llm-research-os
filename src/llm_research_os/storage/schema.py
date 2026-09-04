"""Versioned SQLite schema for the append-only event source and rebuildable query tables."""

from __future__ import annotations

from dataclasses import dataclass

from llm_research_os.canonical import legacy_content_digest

APPLICATION_ID = 0x4C524F53  # ASCII "LROS"
SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class SchemaMigration:
    """One ordered schema migration and the digest of its SQL statements."""

    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def digest(self) -> str:
        return legacy_content_digest(
            [normalize_schema_sql(statement) for statement in self.statements]
        )


V1_MIGRATION = SchemaMigration(
    version=1,
    name="m0-append-only-events",
    statements=(
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
    ),
)

V2_MIGRATION = SchemaMigration(
    version=2,
    name="m1-verified-high-water-and-query-tables",
    statements=(
        """
        CREATE TABLE integrity_checkpoint (
            slot INTEGER PRIMARY KEY CHECK (slot = 1),
            high_water INTEGER NOT NULL
                CHECK (high_water BETWEEN 0 AND 2147483647),
            last_event_digest TEXT,
            schema_digest TEXT NOT NULL CHECK (
                length(schema_digest) = 71
                AND substr(schema_digest, 1, 7) = 'sha256:'
                AND substr(schema_digest, 8) NOT GLOB '*[^0-9a-f]*'
            ),
            verified_event_count INTEGER NOT NULL
                CHECK (verified_event_count BETWEEN 0 AND 2147483647),
            recorded_at TEXT NOT NULL,
            CHECK (
                (
                    high_water = 0
                    AND last_event_digest IS NULL
                    AND verified_event_count = 0
                )
                OR (
                    high_water > 0
                    AND verified_event_count = high_water
                    AND last_event_digest IS NOT NULL
                    AND length(last_event_digest) = 71
                    AND substr(last_event_digest, 1, 7) = 'sha256:'
                    AND substr(last_event_digest, 8) NOT GLOB '*[^0-9a-f]*'
                )
            )
        ) STRICT
        """,
        """
        CREATE TABLE run_projections (
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            last_sequence INTEGER NOT NULL
                CHECK (last_sequence BETWEEN 1 AND 2147483647),
            snapshot_json TEXT CHECK (
                snapshot_json IS NULL OR json_valid(snapshot_json)
            ),
            snapshot_digest TEXT CHECK (
                snapshot_digest IS NULL OR (
                    length(snapshot_digest) = 71
                    AND substr(snapshot_digest, 1, 7) = 'sha256:'
                    AND substr(snapshot_digest, 8) NOT GLOB '*[^0-9a-f]*'
                )
            ),
            PRIMARY KEY (project_id, run_id),
            CHECK (
                (snapshot_json IS NULL AND snapshot_digest IS NULL)
                OR (snapshot_json IS NOT NULL AND snapshot_digest IS NOT NULL)
            )
        ) STRICT
        """,
        """
        CREATE TABLE spec_revisions (
            project_id TEXT NOT NULL,
            revision INTEGER NOT NULL
                CHECK (revision BETWEEN 1 AND 2147483647),
            spec_digest TEXT NOT NULL CHECK (
                (
                    substr(spec_digest, 1, 7) = 'sha256:'
                    AND length(spec_digest) = 71
                    AND substr(spec_digest, 8) NOT GLOB '*[^0-9a-f]*'
                )
                OR (
                    substr(spec_digest, 1, 11) = 'jcs-sha256:'
                    AND length(spec_digest) = 75
                    AND substr(spec_digest, 12) NOT GLOB '*[^0-9a-f]*'
                )
            ),
            first_seen_sequence INTEGER NOT NULL
                CHECK (first_seen_sequence BETWEEN 1 AND 2147483647),
            PRIMARY KEY (project_id, revision)
        ) STRICT
        """,
        """
        CREATE TABLE artifacts (
            digest TEXT PRIMARY KEY CHECK (
                (
                    substr(digest, 1, 7) = 'sha256:'
                    AND length(digest) = 71
                    AND substr(digest, 8) NOT GLOB '*[^0-9a-f]*'
                )
                OR (
                    substr(digest, 1, 11) = 'jcs-sha256:'
                    AND length(digest) = 75
                    AND substr(digest, 12) NOT GLOB '*[^0-9a-f]*'
                )
            ),
            byte_length INTEGER CHECK (byte_length IS NULL OR byte_length >= 0),
            first_seen_sequence INTEGER NOT NULL
                CHECK (first_seen_sequence BETWEEN 1 AND 2147483647)
        ) STRICT
        """,
        """
        CREATE TABLE artifact_links (
            digest TEXT NOT NULL,
            event_sequence INTEGER NOT NULL
                CHECK (event_sequence BETWEEN 1 AND 2147483647),
            role TEXT NOT NULL CHECK (length(role) BETWEEN 1 AND 64),
            PRIMARY KEY (digest, event_sequence, role),
            FOREIGN KEY (digest) REFERENCES artifacts (digest)
        ) STRICT
        """,
        "CREATE INDEX spec_revisions_digest_idx ON spec_revisions (spec_digest)",
        "CREATE INDEX artifact_links_sequence_idx ON artifact_links (event_sequence)",
    ),
)

MIGRATIONS = (V1_MIGRATION, V2_MIGRATION)
MIGRATION_NAME = V1_MIGRATION.name
MIGRATION_STATEMENTS = tuple(
    statement for migration in MIGRATIONS for statement in migration.statements
)


def normalize_schema_sql(value: str) -> str:
    """Normalize insignificant SQL whitespace for schema-definition comparison."""

    return " ".join(value.split())


def _schema_object_key(statement: str) -> tuple[str, str]:
    words = normalize_schema_sql(statement).split(" ", 3)
    return words[1].lower(), words[2]


def _definitions_for(statements: tuple[str, ...]) -> dict[tuple[str, str], str]:
    return {
        _schema_object_key(statement): normalize_schema_sql(statement) for statement in statements
    }


V1_EXPECTED_SCHEMA_DEFINITIONS = _definitions_for(V1_MIGRATION.statements)
V1_EXPECTED_SCHEMA_OBJECTS = frozenset(V1_EXPECTED_SCHEMA_DEFINITIONS)
EXPECTED_SCHEMA_DEFINITIONS = _definitions_for(MIGRATION_STATEMENTS)
SCHEMA_DEFINITION_DIGEST = legacy_content_digest(
    [normalize_schema_sql(statement) for statement in MIGRATION_STATEMENTS]
)
EXPECTED_SCHEMA_OBJECTS = frozenset(EXPECTED_SCHEMA_DEFINITIONS)
FROZEN_V1_MIGRATION_DIGEST = (
    "sha256:dfdfe1bc8233723bfd164f488779428eeae72e4d4b0efa7128abf25e333bd1f1"
)


def expected_migration_history() -> list[tuple[int, str, str]]:
    """Return the ordered ``(version, name, statement digest)`` rows for this schema."""

    return [(migration.version, migration.name, migration.digest) for migration in MIGRATIONS]
