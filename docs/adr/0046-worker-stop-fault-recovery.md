# ADR-0046: Worker stop, fault, and recovery

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0008, ADR-0024, ADR-0028, ADR-0043,
ADR-0044, or ADR-0045. It binds Worker leases to Run/Attempt recovery.
It is not paid GPU and not M2 acceptance.

## Context

M2-0 distinguished sandbox `UNKNOWN` from `failed`, refused to spawn on a
resumed claim, and retried a complete-fact write without re-executing.
`runs cancel` still only appends `*.cancel.requested` (ADR-0028). Worker
leases and Run snapshots could diverge: an artifact in CAS without
`work.completed`, or `work.completed` without `attempt.succeeded`.

Unknown work must not be auto-rerun or marked success. Checkpoint resume
has to be inspectable on CPU before a training adapter.

## Decision

1. **Cancel request is not observed stop.** `runs cancel` remains a request
   fact. A Worker poll MUST NOT open a new lease after that request. An
   already-claimed lease is resumed with `cancelRequested=true` and MUST
   NOT spawn. The Worker fails the lease with `cancel-observed` after the
   process is reaped. `attempt.cancelled` / `run.cancelled` are recorded
   only from that observation. A brick that already finished may still
   `work.completed`; completed wins over a retained request (TM-028).
2. **Heartbeats stay off the log.** Heartbeat MAY return
   `cancelRequested` as transport JSON. It MUST NOT append facts.
3. **Reconcile.** `work.completed` with a still-running Attempt appends
   `attempt.succeeded` / `run.completed`. A CAS artifact without
   `work.completed` MUST NOT succeed the Attempt. `work.failed` with
   `cancel-observed` plus a request appends cancelled outcomes. Unknown
   without a completed fact stays unknown.
4. **Checkpoint.** Same-attempt resume is `attempt.recovered` after
   unknown/lost, then explicit complete of an inspectable checkpoint
   artifact already in CAS. The resumed claim MUST NOT spawn the brick
   again. Continuing from that checkpoint is a new authorized execution
   object (new inputs), not an automatic rerun of the unknown attempt.

## Consequences

- Control-plane restart rebuilds the Worker fold and Run snapshot from
  the EventStore. HMAC reuse remains ADR-0044.
- Disk-full upload, expired lease, revoke, and duplicate complete stay
  fail-closed as in ADR-0043.
- Live GPU preemption is not this slice.

## Validation

1. Cancel request leaves status running with `cancellationRequested`.
2. Observed stop records `cancel-observed` then cancelled outcomes.
3. Timeout/kill stay `UNKNOWN`; reconcile refuses success.
4. Uploaded artifact without `work.completed` retries complete, never
   re-executes, never infers success.
5. CPU checkpoint JSON is inspectable; continuation uses the inspected
   step, not a silent rerun.

## References

- [ADR-0024](0024-run-attempt-state-machine.md)
- [ADR-0028](0028-explicit-run-cancellation-request.md)
- [ADR-0043](0043-m2-loopback-worker-and-hmac-grants.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
