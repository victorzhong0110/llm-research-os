# M0 SQLite Event Store

## What this slice proves

The local control plane can turn a valid ResearchEvent draft into one durable, globally ordered
fact without trusting a dashboard or allowing the supported API to overwrite history.

It does **not** project Run state, replay a workflow, write artifacts or execute a block.

## Minimal use

```python
from llm_research_os.storage import EventStore

draft = {
    # Complete ResearchEvent v0alpha1 fields, except the three store-owned fields below.
}
next_draft = {
    # Another caller-owned event id; same omitted store-owned fields.
}

with EventStore("research.db") as store:
    stored = store.append(draft)
    print(stored.event.sequence)
    print(stored.event.streamversion)
    head = store.last_sequence()
    stored = store.append(next_draft, expected_last_sequence=head)
```

The caller must omit:

- `sequence`;
- `sequencetype`;
- `streamversion`.

The store assigns them atomically. It never generates the caller-owned event `id`, occurrence
`time`, `streamid`, actor or domain payload.

`expected_last_sequence` is a Python API precondition on the current global event head. It is
not a ResearchEvent field, JSON Schema property, or SQLite column, and `streamversion` is not
used as a Run-aggregate concurrency token in this slice.

- `None` (the default) keeps the existing unconditional append.
- `0` requires that the store currently has no events.
- `1` through `2147483647` requires that `MAX(sequence)` equals that value.

Bools, strings, floats, negatives and values above that upper bound are rejected before the
append transaction starts. A mismatch raises `EventSequenceConflictError` with
`expected_last_sequence` and `actual_last_sequence` attributes. The store does not retry;
the caller must replay, re-validate state, and append with a fresh head. If the event ID
already exists, `DuplicateEventError` is raised first even when the expected head is also
stale.

This is a coarse-grained CAS: two concurrent appends that share a stale global head conflict
even when they use different `streamid` values. Stream identity remains an open protocol
question.

## Read primitives

```python
with EventStore("research.db") as store:
    one = store.get_event("evt.example.1")
    page = store.read_events(after_sequence=0, limit=100)
    verified_count = store.verify_integrity()
    head = store.last_sequence()
```

Every read revalidates the frozen SQLite schema v1 canonical JSON (`legacy_canonical_json()`),
the ResearchEvent contract, its `sha256:` event digest and indexed columns. That on-disk encoding
is not the ADR-0033 JCS semantic-digest algorithm. `read_events` is a bounded storage primitive.
Query and replay CLI commands consume it through paged reads and never load the whole store into
memory.

`last_sequence()` returns the current global event head as a concurrency token. An empty store
returns `0`. It reads `MAX(sequence)`, not an event count, and does not replace
`verify_integrity()`.

`EventStore(path)` creates a versioned database when the path is missing.
`EventStore(path, create=False)` opens an existing database with SQLite `mode=ro` and fails without
creating a file if the path does not exist. Query commands use that existing-only mode.
`EventStore(path, require_existing=True)` is the writable counterpart: it uses SQLite `mode=rw`,
requires the exact initialized schema before writable connection settings are enabled, and never
creates a missing path. Run cancellation requests use this mode.

## Integrity scan cost

`verify_integrity()` and every `read_events` page revalidate canonical JSON, the ResearchEvent
contract, digest and index columns. That is the safety default: a corrupted or rewritten row
must not become a trusted fact.

`RunControl.rebuild()` therefore pays a full integrity scan **plus** a second verified replay of
the frozen prefix. Filling a store through that boundary is Θ(N) per append and Θ(N²) to reach
N events. The cost is documented in [M0 RunControl](m0-run-control.md#write-cost-model). M0 does
not cache the high-water mark; `last_sequence()` is only a CAS token and is not a substitute for
the scan.

## Query and replay CLI

```bash
uv run researchos events get research.db evt.example.1 --format json
uv run researchos events list research.db --after-sequence 0 --limit 100 --format json
uv run researchos events replay research.db --after-sequence 0 --page-size 100
uv run researchos events verify research.db --format json
```

- `get` prints one verified ResearchEvent.
- `list` returns one bounded page in global sequence order.
- `replay` prints JSON Lines, one complete event per line. It freezes the high-water sequence with
  `verify_integrity()` before the first line, so later appends are omitted from that run.
- `verify` runs the full integrity scan and reports the event count.
- Missing event IDs exit `1`. Database, input and integrity errors exit `2` with a ProblemReport
  on stderr.
- These commands do not accept SQL, sort expressions or field expressions, and they do not append.

In-memory projection folds consume already-verified ordered events. Persistent projection tables
are not part of this slice.

## Operational boundary

- Keep the database and its `-wal`/`-shm` files together on a local filesystem.
- Do not place the database on NFS, SMB, cloud-synced folders or another network filesystem.
- Copy or back up a live WAL database only through a SQLite-aware backup/checkpoint procedure.
- Treat direct SQL access as administrative access. The supported store API is append/read only,
  but a host administrator can always replace the database file or disable its triggers.
- Do not place secrets or document bodies in events. Persist only allowed metadata and references.
