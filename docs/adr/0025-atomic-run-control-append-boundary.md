# ADR-0025: Atomic RunControl Append Boundary

- Status: Proposed
- Date: 2026-08-30

## Context

ADR-0015 made SQLite the append-only fact source and added a coarse global-head
compare-and-set on `append(..., expected_last_sequence=...)`. ADR-0024 froze a
pure `RunStateProjection` that can reject illegal Run/Attempt transitions without
I/O. SimulatedRuntime still cannot execute: a caller who appends first and folds
afterwards can persist an illegal lifecycle event, and a caller who folds then
appends without CAS can commit a transition that was valid only against a stale
head.

M0 therefore needs a trusted-kernel boundary that connects frozen high-water
replay, reducer preflight, and global CAS. Stream identity, Worker timeout,
retry authorization, and automatic `run.failed` remain open and must not be
filled in here.

## Decision

Introduce `RunControl` as the atomic append boundary for the frozen v0alpha1
Run/Attempt lifecycle catalog:

- `rebuild()` consumes `replay_events(..., freeze_high_water=True)` and folds
  only the configured `(projectId, runId)`. The returned `last_sequence` is the
  frozen global EventStore head, not a Run-local count and not `streamversion`.
- Every `append(document)` rebuilds, rejects store-owned `sequence` /
  `sequencetype` / `streamversion`, requires the draft to belong to the
  configured Run, and accepts only PR #9 lifecycle types.
- RunControl does not generate `id`, `time`, `source`, `subject`, `streamid`,
  `correlationid`, `causationid`, actor, or payload.
- Preflight constructs a complete ResearchEvent with `sequence = frozen_head + 1`
  and `streamversion = 0` solely because the reducer is forbidden from depending
  on stream identity. That zero is not a prediction of the stored stream version.
- Illegal first events, jumps, payloads, attempts, retries, and identity drift
  fail before `EventStore.append`.
- A successful preflight calls `store.append(original_document,
  expected_last_sequence=frozen_head)`. `EventSequenceConflictError` is not
  caught or retried. The caller must invoke `append` again so replay and
  preflight run against the new head.
- The committed snapshot is produced by applying the store-returned event to the
  same frozen snapshot. EventStore remains the only fact source; snapshots are
  not persisted.

This slice does not add a run/start/stop CLI, SimulatedRuntime, a persistent
Run table, SQLite schema v2, or automatic conflict retry.

## Consequences

- Two concurrent writers that preflight against the same frozen head conflict
  even when they target different streams or different Runs.
- A lost CAS does not invent a new event id. If the winning event made the
  loser's transition illegal, a later caller retry is rejected by the reducer
  before write.
- `streamversion` can be non-zero on the committed event while the preflight
  snapshot still matches, because the reducer ignores stream identity.

## Validation

Tests cover empty rebuild, multi-project global heads, a legal success path
equal to EventStore replay, fail-closed illegal first events and jumps, payload
and identity errors that do not echo secrets, rejection of store-owned fields,
aggregate mismatch, non-lifecycle types, global-head sequence prediction,
non-zero `streamversion` snapshot equality, sequence exhaustion, integrity
fail-closed, bounded paging without retained history, concurrent CAS with
`Barrier(2, timeout=5)`, conflict-then-replay rejection, unchanged duplicate-id
precedence, and side-effect tripwires.

## References

- [Run/Attempt State v0alpha1](../protocols/run-attempt-state-v0alpha1.md)
- [M0 RunControl](../guides/m0-run-control.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
- [ADR-0014 CloudEvents-Compatible ResearchEvent](0014-cloudevents-compatible-research-event.md)
- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0024 Pure Run and Attempt State Machine](0024-run-attempt-state-machine.md)
