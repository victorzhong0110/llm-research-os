# ADR-0024: Pure Run and Attempt State Machine

- Status: Accepted
- Date: 2026-08-29

## Context

Charter §13.1 draws a Draft→Reviewed diagram labeled as experimental revision state
(provisional). That diagram must not be reused as the Run/Attempt execution state machine.
Charter §13.2 already requires unknown/lost to stay distinct from failure, retries to create
new attempts, and `Completed` not to mean a hypothesis was supported.

ADR-0014 froze the ResearchEvent envelope without a type catalog or run state machine.
ADR-0015 made events the append-only fact source and left projections rebuildable. ADR-0018
keeps retry distinct from research iteration. ADR-0023 blocked SimulatedRuntime on a tested
state machine that keeps failed, cancelled, lost and unknown distinct.

M0 therefore needs a bounded, pure reducer before workers, leases or dashboards can interpret
execution facts.

## Decision

Adopt a pure `RunStateProjection` over verified ResearchEvents:

- The aggregate key is `(data.projectId, data.runId)`.
- `initial_state()` is `None`. `apply()` is a pure function of one event and a frozen snapshot.
- The reducer performs no I/O, clock, random, network or process effects and does not emit events.
- Only the listed v0alpha1 lifecycle types change or confirm status. Other types stay auditable
  no-ops.
- Stream identity remains undecided; `streamid` / `streamversion` are not inputs to the reducer.
- `maxAttempts` in `1`–`32` is an immutable M0 Run policy snapshot, not a ResearchSpec field.
- `retryHint` is not authorization. A retry requires a new `attempt.queued` and `retryDecisionId`.
- `lost` / `unknown` are unresolved. They cannot be retried or guessed as cancelled.
- `cancellationRequested` is monotonic and is not the cancelled outcome.
- Attempt outcome is not Run outcome; `run.completed` / `run.failed` / `run.cancelled` are
  explicit.
- `run.reviewed` is an audit record after a terminal Run status. It does not change `RunStatus`
  and does not mean a research conclusion was established.

This slice does not freeze the complete ResearchEvent type catalog or persist a SQL
projection. ADR-0025 adds the atomic RunControl append boundary that applies this
reducer before EventStore CAS. ADR-0026 uses both to emit a single simulated
lifecycle; it does not change these transition rules or persist snapshots.

## Consequences

- Rebuild, checkpoint/resume and EventStore replay converge on the same snapshot.
- Adapters cannot hide transitions behind undeclared types.
- Memory is bounded by at most 32 Attempt snapshots.
- Worker timeout, lease loss and decision authority remain later slices. They must emit the
  explicit events defined here rather than mutating projection state.

## Validation

Valid traces cover success plus review, explicit retry, unknown/lost recovery, cancellation
racing with completion, and requested cancellation. Invalid traces cover illegal first events,
inferred Run completion, retry while lost/unknown, reused Attempt IDs, retry forks, ordinal
skips, unrequested cancel, guessing lost as cancelled, terminal rewrites, non-terminal review,
binding drift, sequence errors and closed-payload failures. External snapshots/checkpoints
that violate the same status, retry-chain, or cursor invariants are rejected. Tests also prove
checkpoint/resume equality, EventStore rebuild determinism, project-scoped `runId`, heartbeat
non-inference, unrelated-type no-ops and bounded retained state.

## References

- [Run/Attempt State v0alpha1](../protocols/run-attempt-state-v0alpha1.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
- [ADR-0014 CloudEvents-Compatible ResearchEvent](0014-cloudevents-compatible-research-event.md)
- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0018 Explicit Bounded Loops](0018-explicit-bounded-loops.md)
- [ADR-0023 Inert Manifests and Pure Dry-Run](0023-inert-manifests-and-pure-dry-run.md)
- [ADR-0025 Atomic RunControl Append Boundary](0025-atomic-run-control-append-boundary.md)
- [ADR-0026 Deterministic SimulatedRuntime](0026-deterministic-simulated-runtime.md)
