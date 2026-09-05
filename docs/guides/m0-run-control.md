# M0 RunControl

## What this slice proves

A lifecycle draft can be rejected by the pure Run/Attempt reducer **before** any
SQLite write, and a legal draft is appended only if the global event head is
still the head observed during that replay.

It does **not** start a runtime, execute a block, mint event identity, or retry
a compare-and-set conflict.

## Minimal use

```python
from llm_research_os.runs import RunControl
from llm_research_os.storage import EventStore

draft = {
    # Complete caller-owned ResearchEvent v0alpha1 fields.
    # Omit sequence, sequencetype and streamversion.
}

with EventStore("research.db") as store:
    control = RunControl(
        store,
        project_id="project.example",
        run_id="run.example",
    )
    head = control.rebuild()
    print(head.last_sequence, head.snapshot)
    result = control.append(draft)
    print(result.stored.event.sequence)
    print(result.snapshot.status)
```

`rebuild()` freezes the high-water mark with `replay_events(...,
freeze_high_water=True)`, consumes the whole global log, and folds only the
configured `(projectId, runId)`. An empty store returns head `0` and snapshot
`None`.

`last_sequence` is the global CAS token. It is not the number of events in this
Run and is not `streamversion`. Stream identity remains undecided.

## Write cost model

M0 prefers fail-closed integrity over incremental speed. That choice is
deliberate and has a known cost.

Each `rebuild()`, including the one at the start of every `append()`, freezes a
verified high-water mark and folds this Run:

1. `replay_events(..., freeze_high_water=True)` calls
   `EventStore.freeze_high_water()`. That re-reads live `MAX(sequence)`, the last
   event digest, and the schema digest. If they match the stored checkpoint, the
   full `verify_integrity` scan is skipped. If they disagree, the store falls
   back to `PRAGMA integrity_check` plus a complete event re-parse and rewrites
   the checkpoint (ADR-0041, TM-011).
2. Fold this Run from sequence 0 through that high-water mark. A cached
   `run_projections` row is **not** a fold start: canonical JSON plus digest
   only prove the row agrees with itself. Wrong `projectId`/`runId`, an
   impossible `last_sequence`, or a parse failure drops the row. The iterator
   pages `read_events` up to the frozen mark; each page still verifies every
   row through the decoder. `page_size` bounds **memory**.
3. `RunStateProjection.apply` folds only events for the configured
   `(projectId, runId)`. A successful rebuild or append rewrites the cached
   snapshot when the store is writable. A cache-write failure does not convert
   a committed fact into an append failure. The row is a consumer, not a fact.

Therefore:

- One `append` against a matching integrity checkpoint skips the full
  `verify_integrity` scan, then folds the frozen prefix from sequence 0.
- Filling a store from empty to N events exclusively through `RunControl.append`
  is Θ(N) checkpoint work while the checkpoint stays valid, plus Θ(N²) fold
  work over the growing prefix.
- A CAS conflict retry rebuilds against the new head; a mismatched or missing
  checkpoint pays a full scan once, then continues.
- Cost still tracks the **global** sequence. Events for other projects, Runs,
  or authorization audits still sit on the scanned prefix.

Schema v1 (M0) paid Θ(N) per append and Θ(N²) to fill N events. That model is
historical; do not use it to explain current append latency.

### Applicable scale

- Intended for local development, tests, and research logs that grow into the
  M1 event catalog (proposal, dissent, decision, `ai.call`, evidence, budget).
- `events verify` is still the full `verify_integrity` scan.
  `events replay` freezes a high-water mark through `freeze_high_water()`.
- Call `rebuild_query_tables()` after administrative SQL or when comparing
  `spec_revisions` / artifact index rows to the event prefix.

### What this slice does not add

Query tables and the high-water cache are rebuildable consumers. Charter
decision `6-DBC` and [ADR-0015](../adr/0015-sqlite-event-source-projections-and-artifacts.md)
still treat EventStore `events` as the only fact source.

[ADR-0041](../adr/0041-verified-high-water-cache-and-query-tables.md) requires:

- treat any remembered head as untrusted until revalidated;
- fall back to a full `verify_integrity` when the remembered sequence, last
  digest, or schema disagrees;
- ship adversarial tests for tampered, truncated, and stale checkpoints;
- keep EventStore as the only authority.

See [M0 Event Store](m0-event-store.md#integrity-scan-cost) for the shared scan
primitive.

## Append algorithm

Each `append(document)` starts over:

1. Replay and fold (`rebuild()`).
2. Isolate a JSON snapshot of the caller document. Later preflight and
   `EventStore.append` use that snapshot only; mutating the original object
   cannot change the persisted event.
3. Reject store-assigned `sequence`, `sequencetype`, or `streamversion` on the
   snapshot.
4. Reject a draft if the global sequence is exhausted.
5. Copy the snapshot and add only `sequence = str(frozen_head + 1)`,
   `sequencetype = Integer`, and `streamversion = 0`.
6. Validate that complete document as a ResearchEvent. Aggregate membership and
   lifecycle-type checks use the validated event, not the raw caller value.
7. Apply the validated event to the frozen snapshot.
8. Only then call `store.append(isolated_snapshot, expected_last_sequence=frozen_head)`.

`streamversion = 0` exists because the reducer must not consult stream
identity. It is not a forecast of the value the store will assign.

RunControl does not generate `id`, `time`, `source`, `subject`, `streamid`,
`correlationid`, `causationid`, actor, or payload.

## Conflicts

A concurrent writer that commits after this replay raises
`EventSequenceConflictError` with numeric `expected_last_sequence` and
`actual_last_sequence`. RunControl does not catch, sleep, or retry that error,
and it does not mint a replacement event id.

The caller must invoke `append` again. That second call rebuilds, re-validates
against the new head, and may now be rejected by the reducer if the winning
event made the transition illegal.

`DuplicateEventError`, `EventIntegrityError` and `EventStoreSchemaError` keep
their EventStore meanings and are not translated into success.

## Authority

- EventStore is the only fact source.
- `RunSnapshot` is a rebuildable projection. RunControl may cache it in
  `run_projections` after a full prefix fold; the cache is never fold
  authority. Identity, sequence, canonical JSON, and digest mismatches drop
  the row. A cache-write failure after a committed fact does not fail the
  append.
- JSON Schema for `RunSnapshot` is available as
  `researchos schema --contract run-state`.

This boundary is not a runtime. [SimulatedRuntime](m0-simulated-runtime.md)
calls `append()` for one built-in simulated task; it still does not mint
identity or retry CAS. The [Run Cancellation CLI](m0-run-cancellation-cli.md)
is a second narrow caller that appends one request fact and never claims the
target stopped.
