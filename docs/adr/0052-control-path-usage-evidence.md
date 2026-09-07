# ADR-0052: Worker/RunControl usage evidence

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0044, ADR-0045, or ADR-0047. It does not
spend GPU, rent a machine, or claim M2 acceptance.

## Context

ADR-0047 fills EventStore with `run.heartbeat` stand-ins and measures
append/replay/claim-rebuild/report. That is a storage baseline. It is not
the Worker or RunControl path: it does not poll, complete, cancel, or
coordinate leases, and it does not mix research or budget facts.

Usage evidence for this slice must go through `WorkerControl` /
`WorkerPlane.poll` / `RunControl` cancellation, under mixed
`proposal.submitted` and `budget.limit.recorded` facts, and must record
log growth. A second process with a private CAS is the isolated Worker.
A missing docker engine is `skipped-no-runtime` on ordinary hosts and a
failure in designated Linux OCI CI (ADR-0049).

## Decision

1. **Control path, not fill.** `researchos m2 usage` MUST NOT call
   `EventStore.append` to invent heartbeat volume. Append, claim, complete,
   cancel, and coordinate go through WorkerPlane and RunControl.
2. **Concurrency is CAS-visible.** Concurrent claims use separate EventStore
   connections and retry `EventSequenceConflictError`. Receipts record retry
   counts. They are not SLA numbers.
3. **Cancel is requested, not observed stop.** A resumed poll with
   `cancelRequested=true` is the control-path measurement. This slice does
   not call `plane.fail("cancel-observed")` to fake a stop (ADR-0051).
4. **Isolated Worker + report cites.** A control-plane process and a Worker
   process MUST use different CAS roots. The static report MUST cite spec,
   registry, plan, runtime, image, config, and output artifact. Loopback
   HTTPS is not a cross-machine proof (ADR-0021).
5. **OCI is labeled.** Observed on a live engine; `skipped-no-runtime` when
   docker is absent and `RESEARCHOS_OCI_REQUIRED` is unset; fail closed when
   that env is `1`.

## Consequences

- `m2 bench` remains the 10k/100k EventStore fill (ADR-0047).
- `USAGE.json` carries `usedEventStoreAppendFill: false`.
- Issue #38 stays open. This is not GPU completion.

## Validation

1. Mixed log contains `proposal.submitted`, `budget.limit.recorded`,
   `work.claimed`, and `work.completed`, and MUST NOT contain `run.heartbeat`.
2. Foreign grant poll fails `grant-worker-mismatch`.
3. Isolated Worker CAS ≠ control-plane CAS; report cites the seven binding
   labels.
4. Ordinary hosts may skip OCI; designated Linux OCI CI must not.

## References

- [ADR-0044](0044-isolated-control-plane-and-loopback-https.md)
- [ADR-0047](0047-eventstore-performance-and-metric-sampling.md)
- [ADR-0049](0049-oci-nobody-bind-and-required-linux-ci.md)
- [ADR-0051](0051-live-cpu-fault-acceptance.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
