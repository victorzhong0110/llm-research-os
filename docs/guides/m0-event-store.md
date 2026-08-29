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

with EventStore("research.db") as store:
    stored = store.append(draft)
    print(stored.event.sequence)
    print(stored.event.streamversion)
```

The caller must omit:

- `sequence`;
- `sequencetype`;
- `streamversion`.

The store assigns them atomically. It never generates the caller-owned event `id`, occurrence
`time`, `streamid`, actor or domain payload.

## Read primitives

```python
with EventStore("research.db") as store:
    one = store.get_event("evt.example.1")
    page = store.read_events(after_sequence=0, limit=100)
    verified_count = store.verify_integrity()
```

Every read revalidates canonical JSON, the ResearchEvent contract, its SHA-256 digest and indexed
columns. `read_events` is a bounded storage primitive. Query and replay CLI commands consume it
through paged reads and never load the whole store into memory.

`EventStore(path)` creates a versioned database when the path is missing.
`EventStore(path, create=False)` opens an existing database with SQLite `mode=ro` and fails without
creating a file if the path does not exist. Query commands use that existing-only mode.

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
