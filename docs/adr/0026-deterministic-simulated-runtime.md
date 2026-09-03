# ADR-0026: Deterministic SimulatedRuntime

- Status: Accepted
- Date: 2026-08-30

## Context

ADR-0023 made BlockManifests inert and dry-run a pure compiler. ADR-0024 froze a
Run/Attempt reducer that keeps failed, cancelled, lost and unknown distinct.
ADR-0025 made `RunControl` the only trusted write gate over EventStore.

M0 still needed one vertical loop that a researcher can run without GPU, network,
or arbitrary code:

ResearchSpec → TrustedKernel dry-run → ready ExecutionPlan → SimulatedRuntime →
RunControl → EventStore → RunSnapshot replay.

NativeProcessRuntime, OCI, Workers, metrics and artifacts would enlarge the
trusted kernel before the lifecycle facts, recovery prefix and fail-closed
unknown path were proven. This slice therefore executes only the built-in
`simulated.experiment@0.1.0` task, identified by the canonical Manifest
digest rather than by id/version alone.

Open questions that remain out of scope: `streamid` granularity, the complete
ResearchEvent type catalog, `correlationid` / `causationid` rules,
`retryDecisionId` authority, Worker timeout/heartbeat, automatic `run.failed`
when `maxAttempts` is exhausted, and payload size/depth limits.

## Decision

Introduce `SimulatedRuntime` as a trusted-kernel scheduler for one ready
single-task plan:

- The constructor binds `(store, registry, project_id, run_id)`. `run(spec,
  request)` is the only entry.
- `projectId` and `experimentRevision` come from a defensive JSON snapshot of
  the ResearchSpec. `workflowId`, `runId`, `attemptId`, `source`, `subject`,
  `streamid`, actor id, and every event `id` / `time` are caller-owned. The
  runtime does not call a clock, UUID, or random generator, and does not mint
  `correlationid` / `causationid`.
- The same isolated snapshot is used for dry-run, workflow/task selection,
  `outcome` reading, project/revision binding, and `run.queued` digests.
  `copy.deepcopy()` is not used. After preflight the caller may mutate the
  original object; the written path does not change.
- The registry must already be sealed. Dry-run is recomputed and the full
  `(specDigest, registryDigest, planDigest)` triple is bound. A blocked report
  or internally inconsistent plan/report fails with zero EventStore writes.
- The only supported plan is one top-level `simulated.experiment@0.1.0`
  TaskBlock bound to the canonical built-in Manifest fingerprint, no edges, no
  approval/loop, no top-level `spec.resources` (including unreferenced
  entries), no `resourceRefs` or `policyRequirements`, manifest runtime
  `simulated` with empty permissions, and an explicit string `outcome` of
  `success`, `failure`, or `unknown`. Missing `outcome` is not success. `seed`
  is bound data only; it does not seed a PRNG. A sealed registry that
  substitutes the same id/version or adds permissions fails closed with zero
  EventStore writes.
- Before reading `outcome` or appending facts, the runtime passes the ready
  report through ADR-0030's exact three-digest authorization gate. Its fixed
  T0 policy grants only the canonical `simulate` capability; it grants no
  permission or approval requirement. The returned `decisionDigest` is written
  on `run.queued` and rebuilt onto `RunSnapshot.digests`. The runtime does not
  read `plan.authorization.evaluated` events.
- Every fact is written through `RunControl.append()`. SimulatedRuntime does
  not INSERT into SQLite, persist a Run table, write ArtifactStore, or emit
  `run.reviewed`. `maxAttempts` is fixed at `1`. This slice does not retry and
  does not issue `retryDecisionId`.
- Success emits exactly `run.queued` → `run.started` → `attempt.queued` →
  `attempt.started` → `attempt.succeeded` → `run.completed`. Failure replaces
  the last two events with `attempt.failed` / `run.failed` and
  `reasonCode: simulation.outcome.failure`. Unknown emits `attempt.unknown`
  with `reasonCode: simulation.outcome.unknown` and then stops: the Run stays
  unknown and is not guessed as failed, lost, cancelled, or success.
- All remaining drafts, including ids and times, are validated against
  ResearchEvent and folded in memory before the first SQLite write. Duplicate
  ids fail closed at that boundary. A later bad identity cannot leave a partial
  prefix of this invocation.
- `run()` resumes from a legal EventStore prefix after re-checking identity,
  revision, workflow, digests, `maxAttempts`, and Attempt id. Terminal
  `completed` / `failed` return the existing snapshot with zero new facts,
  even if a prior Run cancellation request remains on the snapshot. Unknown,
  lost, cancelled, a nonterminal Run-level `cancellationRequested`, an active
  Attempt cancellation request, or a latest cancelled Attempt return
  unresolved without inferring an outcome.
- `EventSequenceConflictError` is not caught or retried. Duplicate, integrity,
  and schema errors keep their EventStore meanings.

Simulated `completed` means the controlled lifecycle finished. It is not model
training success, valid metrics, or a supported hypothesis.

This slice does not add a SimulatedRuntime JSON Schema, a run CLI,
NativeProcessRuntime, multi-node scheduling, data-edge values, loop unrolling,
cancel/heartbeat/lost policy, or SQLite schema changes.

Implementation follow-up: ADR-0027 adds a strict external SimulationRequest
Schema and a CLI wrapper without changing the runtime decision above.

## Consequences

- Interruptions leave a legal event prefix. Reopening the database and calling
  `run()` continues from replay rather than inventing a compensating fact.
- Two writers that preflight the same frozen global head still conflict inside
  RunControl. The loser must not be treated as success and must not mint a new
  event id.
- Unsupported plans, other runtime types, and missing `outcome` fail before any
  lifecycle event exists, so they cannot be mistaken for a simulated result.
- Extending to multiple nodes, loops, cancellation policy, metrics, artifacts,
  and NativeProcessRuntime requires new ADRs. Those slices must keep unknown
  distinct and must not treat simulated completion as scientific success.

## Validation

Tests cover the three event sequences and EventStore replay equality, global
sequence assignment, non-zero `streamversion`, digest binding, missing and
malformed `outcome` with zero writes and no secret echo, blocked dry-run,
non-simulated runtimes, multi-task/edge/approval/loop/resource/policy rejection
including unreferenced `spec.resources`, substituted and permission-bearing
`simulated.experiment@0.1.0` manifests, Attempt cancel-requested and cancelled
prefixes, completed/failed-after-cancel races, caller and nested-container
mutation after freeze, pre-write identity validation, resume from every legal
prefix, terminal idempotence, mismatched existing Runs, bounded CAS with
`Barrier(2, timeout=5)` and no automatic retry, integrity/duplicate
fail-closed, side-effect tripwires, and `examples/valid/minimal.yaml` success.

## References

- [M0 SimulatedRuntime](../guides/m0-simulated-runtime.md)
- [Run/Attempt State v0alpha1](../protocols/run-attempt-state-v0alpha1.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0023 Inert Manifests and Pure Dry-Run](0023-inert-manifests-and-pure-dry-run.md)
- [ADR-0024 Pure Run and Attempt State Machine](0024-run-attempt-state-machine.md)
- [ADR-0025 Atomic RunControl Append Boundary](0025-atomic-run-control-append-boundary.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
