# ADR-0015: SQLite Event Source, Rebuildable Projections, and Artifact Addressing

- Status: Accepted
- Date: 2026-08-28

## Context

ResearchEvent is the audit fact for research, planning and later execution. Treating mutable
`runs` or dashboard rows as the source of truth would erase failure history and make recovery
dependent on whichever projection happened to survive. Storing only opaque JSON would preserve
history but would make ordered replay, duplicate rejection and basic integrity checks needlessly
fragile.

M0 is a local, single-host control plane. It needs an inspectable fact source before a run state
machine or SimulatedRuntime can be trusted, but it does not need a remote database, broker or
multi-writer service.

## Decision

Adopt decision `6-DBC`: SQLite stores append-only facts; query tables are rebuildable projections;
artifact bytes are content-addressed outside the database and only indexed by SQLite.

The first schema migration implements the event-source foundation only:

- `schema_migrations` records ordered database migrations and their reference-definition digest;
- `events` stores the complete canonical ResearchEvent JSON, a tagged SHA-256 digest and indexed
  identity, stream, type, time, project, Run/Attempt and causality columns;
- `(event_id)` and `(stream_id, stream_version)` are unique;
- UPDATE, DELETE and conflicting INSERT/REPLACE operations are rejected by triggers;
- reads revalidate the ResearchEvent, canonical encoding, digest and duplicated index columns;
- a full integrity scan also runs SQLite integrity checks and rejects gaps in global sequence.

The store accepts an event draft containing every v0alpha1 field except `sequence`,
`sequencetype` and `streamversion`. It does not generate `id`, `time`, `streamid` or domain data.
Inside one `BEGIN IMMEDIATE` transaction it:

1. rejects a duplicate event ID;
2. assigns the next global Integer `sequence`, starting at `1`;
3. assigns the next version for the caller's opaque `streamid`, starting at `0`;
4. validates the complete ResearchEvent again;
5. appends the canonical event and its digest.

`streamid` granularity remains a protocol question: the store treats it as an opaque caller-owned
identity and does not decide whether it denotes a project, Run, Attempt or another aggregate.
Likewise, `correlationid` and `causationid` are indexed but are not foreign keys while cross-stream,
forward-reference and self-causation rules remain undecided.

Each database has the `LROS` SQLite application ID and an explicit `user_version`. Connections
enable foreign keys, recursive triggers, `synchronous=FULL` and WAL. `BEGIN IMMEDIATE` obtains the
single SQLite write transaction before reading sequence heads, preventing two local connections
from allocating the same values. Database paths must be regular, non-symlink files. Operators must
place them on a local filesystem; SQLite WAL is not supported across network filesystems.

This migration deliberately does **not** add projections, query/replay CLI commands,
`spec_revisions`, artifact tables, a run state machine or SimulatedRuntime. Those arrive as later
versioned migrations and cannot become a second fact source.

## Consequences

- A persisted event is complete external-contract JSON and can be exported without reconstructing
  store-owned ordering fields.
- Sequence allocation is serialized, while WAL permits readers to continue during a writer.
- Correcting a fact requires a new event; the supported API cannot mutate or delete an old one.
- Store reads are bounded and fail closed when JSON, digests or indexed columns disagree.
- The digest uses the current Python reference canonicalization. It is not a stable cross-language
  signing format; a later ADR must decide normative canonicalization before external verification.
- Triggers and digests protect against bugs and detectable corruption, not a malicious host with
  arbitrary database-file access. There is no signature, external anchor or deletion-proof hash
  chain in this slice.
- Payload size/depth limits remain an accepted local-M0 risk until the ResearchEvent contract
  freezes them or the store adds an explicitly non-normative operational limit.

## Validation

Tests cover new/reopened databases, WAL and migration headers, atomic global/per-stream allocation,
concurrent connections, duplicate rollback without sequence gaps, trigger-protected immutability,
canonical JSON and digest verification, index disagreement, missing sequence detection, bounded
reads, symlink rejection and fail-closed handling of unrelated databases.

## References

- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- [SQLite write-ahead logging](https://www.sqlite.org/wal.html)
- [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html)
- [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html)
- [Chapter 18 decision 6-DBC](../chapter-18-decision-guide-v0.1.md)
