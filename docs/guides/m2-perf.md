# M2 EventStore performance baseline

Measure append, replay, Worker claim-path rebuild, and static report at
10k and 100k events. Protocol: [Metric chunk v0alpha1](../protocols/metric-chunk-v0alpha1.md).
Constraint record: [ADR-0047](../adr/0047-eventstore-performance-and-metric-sampling.md).

This path does **not** close Issue #38, does not spend GPU, and is not
an SLA.

`researchos m2 usage` is the Worker/RunControl path
([M2 usage](m2-usage.md), ADR-0052). Do not treat this EventStore fill as
that measurement.

## Bench

The database path must not already exist. Fill uses `EventStore.append`
(not `WorkerControl.append`). Heartbeats in this fill are stand-in
foreign facts so the Worker fold can skip them; production heartbeats
still MUST NOT enter the log.

```bash
uv run researchos m2 bench research-bench-10k.db \
  --events 10000 --format json
uv run researchos m2 bench research-bench-100k.db \
  --events 100000 --format json
```

JSON kind is `M2PerfBaseline`. Fields are wall seconds, peak RSS, report
size, and lineage event count. Host numbers vary; do not check them in
as golden files. Lineage MUST stay on the one `run.queued` fact, not the
fill volume.

## Report lineage

After `researchos m2 prove`, the static report cites spec, registry, plan,
Worker runtime, image, config, and output artifact digests by `eventId`.

```bash
uv run researchos report run.worker.cpu \
  --database research-m2.db \
  --format markdown
```

The report is a projection. Replay `events` to audit.
