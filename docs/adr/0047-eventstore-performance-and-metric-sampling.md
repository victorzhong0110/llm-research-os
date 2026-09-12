# ADR-0047: EventStore performance baseline and metric sampling

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0015, ADR-0041, ADR-0043, or ADR-0046.
It does not change the SQLite fact store, does not introduce a message
cluster, and is not a GPU or M2-acceptance claim.

## Context

Replay, Worker claim, and static reports must remain correct as the log
grows. Filling a Worker fold by replaying every event, including
transport heartbeats, is Θ(N) per claim rebuild. Materializing every
event in a Run report lineage does the same for memory. Per-optimizer-step
`training.step` facts would grow the log without adding scientific
identity.

Heartbeats already MUST NOT enter EventStore (ADR-0041, ADR-0046). The
remaining work is to keep claim/report folds off the foreign-type scan
and to put high-frequency series in CAS.

## Decision

1. **Keep SQLite.** 10k and 100k event measurements use `EventStore.append`,
   `replay_events`, `WorkerControl.rebuild`, and `build_run_report`.
   Bottlenecks are fixed in those paths. This slice does not replace
   SQLite or add a queue.
2. **Typed fold reads after a verified high-water.** `read_events` may
   filter `event_types` and `until_sequence`. That filter MAY skip
   sequences and is not a substitute for `replay_events`. Worker rebuild
   uses `WORKER_EVENT_TYPES`. Reports still replay the contiguous prefix
   so authorization consume cannot see live rows after freeze, but they
   retain only the matching Run's events in lineage.
3. **Metric chunks live in CAS.** `MetricChunk` JSON is content-addressed.
   Caps: 1024 samples per chunk, 32 chunks per attempt. Facts MAY cite
   digests. They MUST NOT append one EventStore row per sample.
   SimulatedRuntime `training.step` `{kind: synthetic, step: 1}` is
   unchanged.
4. **Bench receipts are not SLA.** `researchos m2 bench` records wall
   time and peak RSS for 10000 or 100000 events. Host numbers are not
   golden files.

## Consequences

- Claim-path rebuild cost is the Worker-type subset, not heartbeat
  volume.
- A 100k-event store still reports one Run without a 100k-row lineage.
- Training adapters that emit per-step series MUST use metric chunks.

## Validation

1. 10k and 100k `m2 bench` receipts exist; lineage stays one Run event.
2. Worker rebuild passes `WORKER_EVENT_TYPES` and still folds a Worker
   registered after foreign heartbeats.
3. 10k metric samples become 10 CAS chunks; 32×1024+1 samples fail
   `metric-chunk-limit`.
4. `researchos report` after `m2 prove` cites spec, runtime, image,
   config, and output artifact digests.

## References

- [ADR-0041](0041-verified-high-water-cache-and-query-tables.md)
- [ADR-0046](0046-worker-stop-fault-recovery.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Metric chunk v0alpha1](../protocols/metric-chunk-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
