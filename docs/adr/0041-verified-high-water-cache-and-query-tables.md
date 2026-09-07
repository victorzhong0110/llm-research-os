# ADR-0041: Verified high-water cache and rebuildable SQLite query tables

- Status: Accepted
- Date: 2026-09-04

## Context

ADR-0015 made SQLite the append-only fact source and left persistent projections,
`spec_revisions`, and an artifact index for a later migration. ADR-0025 made
every `RunControl.append` rebuild from a full `verify_integrity` scan plus a
second verified replay. Filling a store of N events through that boundary is
Θ(N²). M0 kept that cost model for a local kernel proof.

M1 writes proposal, dissent, decision, `ai.call`, evidence, and budget events
into the same `events` table. The write-cost model in
[M0 RunControl](../guides/m0-run-control.md#write-cost-model) would otherwise
block that volume. Charter decision `6-DBC` still forbids treating a projection
row as a second fact source. TM-011 requires that remembered heads stay
untrusted until revalidated, with a full scan when sequence, last digest, or
schema disagree.

## Decision

Add SQLite schema v2 as a versioned migration on top of `m0-append-only-events`:

1. `integrity_checkpoint` is a singleton remembered high-water fingerprint:
   global sequence, last event digest (null when empty), schema definition
   digest, and verified event count. `EventStore.freeze_high_water()` always
   re-reads live `MAX(sequence)`, the last row's digest, and the running
   schema digest. A match skips the full event re-parse. A mismatch, a missing
   checkpoint, or a schema failure falls back to `verify_integrity()`, which
   rewrites the checkpoint. Append updates the checkpoint inside the same
   write transaction as the new event. The checkpoint is never authority.
2. `run_projections` caches one rebuildable `RunSnapshot` (or a null snapshot)
   per `(project_id, run_id)` together with the global sequence it was folded
   through. The row is a **performance hint and query-table consumer**, not a
   verified fold start. A digest of the cached JSON only proves the row agrees
   with itself; it does not prove derivation from the cited event prefix.
   `RunControl.rebuild` always folds the frozen prefix from sequence 0.
   A row whose `projectId`/`runId` disagree with the lookup key, whose
   `last_sequence` is impossible relative to the frozen head, or whose
   canonical JSON / digest / `RunSnapshot` parse fails, is dropped. EventStore
   does not import the reducer. A cache-write failure after a committed
   lifecycle fact does not fail the append; the fact stands and the cache is
   omitted.
3. `spec_revisions`, `artifacts`, and `artifact_links` are rebuildable indexes
   of digest references observed in events. They are replaced by
   `rebuild_query_tables()` from a frozen verified prefix. `artifacts put`
   still does not emit events; CLI object puts are not rows in this index.
   `byte_length` is null when the event only cited a digest.

Schema v1 databases upgrade on the next writable open. A read-only open of v1
fails closed. Fresh databases apply both migrations and record two
`schema_migrations` rows. Each row stores that migration's statement digest;
the combined schema digest is the freeze fingerprint.

This ADR does not add an external API, a Worker, or a second writer. It does
not make SimulatedRuntime mint `id` / `time` / `streamid`.

## Consequences

- One `RunControl.append` against a trusted matching **integrity checkpoint**
  skips the full `verify_integrity` scan (still Θ(prefix) to fold this Run
  from sequence 0). The Run snapshot cache is not a skip token for unread
  events: a self-consistent fabricated snapshot for the same Run at a valid
  high-water must not become preflight authority.
- Filling N events through RunControl is Θ(N) checkpoint work when the
  checkpoint stays valid, plus Θ(N²) fold work over the growing prefix.
- A host that tampers earlier events while leaving the last digest intact is
  still outside the threat model (ADR-0015: no malicious-host guarantee).
  Tampered, truncated, stale, and **missing** checkpoints have tests and must
  fall back to a full scan. A missing checkpoint row is not a schema failure.
- Query tables can be deleted and rebuilt from `events`. Treating them as facts
  remains a TM-011 violation.
- ADR-0025's M0 write-cost paragraph remains historically true for schema v1
  and for any caller that still invokes `verify_integrity()` on every rebuild.

## Validation

Tests cover v1→v2 upgrade, read-only refusal of v1, matching-checkpoint skip of
the full scan, stale/tampered/truncated/missing checkpoint fallback (writable
recreate, read-only verify without recreate), query-table rebuild after deleting
index rows, RunControl discard of a tampered or foreign-Run snapshot row,
rejection of a fabricated same-Run snapshot as fold authority, cache-write
failure after a committed append, and equality between a rebuilt Run projection
and a reducer fold of the same prefix.

## References

- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0025 Atomic RunControl Append Boundary](0025-atomic-run-control-append-boundary.md)
- [ADR-0038 Charter Errata after M0](0038-charter-errata-after-m0.md) E3 / E4 M1-0
- Issue #39
- [M0 RunControl](../guides/m0-run-control.md#write-cost-model)
- [Threat model TM-011](../security/threat-model.md)
