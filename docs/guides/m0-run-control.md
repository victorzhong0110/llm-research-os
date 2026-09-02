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

Each `rebuild()`, including the one at the start of every `append()`, does two
verified passes over the **global** log, then folds only this Run:

1. `replay_events(..., freeze_high_water=True)` first calls
   `EventStore.verify_integrity()`. That scan runs `PRAGMA integrity_check`,
   reads every stored event in sequence order, re-parses canonical JSON,
   re-validates the ResearchEvent contract, recomputes the `sha256:` digest, and
   checks index columns. The returned count is the frozen high-water mark.
2. The iterator then pages `read_events` up to that mark. Each page verifies
   every row again through the same decoder. `page_size` bounds **memory**, not
   CPU or I/O: the second pass is still Θ(N) in the global event count.
3. `RunStateProjection.apply` folds only events for the configured
   `(projectId, runId)`. Folding is linear in this Run, but it happens after
   the two global verification passes.

Therefore:

- One `append` against a store of N events costs Θ(N) verification work.
- Filling a store from empty to N events exclusively through `RunControl.append`
  costs Θ(N²) verification work: the *k*-th append re-verifies the previous
  *k* − 1 facts.
- A CAS conflict retry pays the same full rebuild against the new head.
- Cost tracks the **global** sequence, not this Run's event count. Events for
  other projects, Runs, or authorization audits still sit on the scanned prefix.

This is the correct M0 default for a local, single-host control plane. It is
not a SQLite write-path defect. If append latency grows with store size, start
here, not with WAL settings.

### Applicable scale

- Intended for local development, tests, and small research logs: tens to low
  thousands of events. A SimulatedRuntime success path writes six lifecycle
  facts; each of those six rebuilds the whole prefix.
- Do not use M0 RunControl as a high-throughput ingest path. Around 10⁵ events,
  every append re-verifies the entire history twice. That slowdown is this
  cost model, and it will keep growing with N.
- `events verify` is the same full `verify_integrity` scan.
  `events replay` freezes a high-water mark the same way. Neither is a cheaper
  substitute for `rebuild()`.

### What this slice does not add

M0 does **not** remember a verified `(sequence, last digest)` checkpoint, skip
`verify_integrity` on a later rebuild, or persist a Run projection table.
Charter decision `6-DBC` and [ADR-0015](../adr/0015-sqlite-event-source-projections-and-artifacts.md)
still treat persistent projections as rebuildable consumers, not as a second
fact source.

A later slice may introduce a verified high-water cache or a projection table.
If it does, that work needs its own ADR and must:

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
- `RunSnapshot` is a rebuildable in-memory projection. RunControl does not
  persist it and does not add a Run table.
- JSON Schema for `RunSnapshot` is available as
  `researchos schema --contract run-state`.

This boundary is not a runtime. [SimulatedRuntime](m0-simulated-runtime.md)
calls `append()` for one built-in simulated task; it still does not mint
identity or retry CAS. The [Run Cancellation CLI](m0-run-cancellation-cli.md)
is a second narrow caller that appends one request fact and never claims the
target stopped.
