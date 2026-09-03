# ADR-0007: Append-Only Facts and Rebuildable Projections

- Status: Accepted
- Date: 2026-08-21

## Context

Dashboards, leases and mutable run rows become a second source of truth unless
the control plane treats facts as append-only and projections as disposable.
Charter P5 and P8 already require reconstructible history, explicit unknown
states, and events-before-boards. Chapter 18 decision 6-DBC chose SQLite as a
hybrid of append-only events, rebuildable projections and content-addressed
artifacts.

ADR-0014 and ADR-0015 implement that hybrid for the event store and a local
file object layer. This record states the constitutional rule those ADRs
serve, including that a projection cache is never authoritative.

## Decision

Already-happened facts MUST NOT be silently rewritten. Corrections are new
events. Deletes, if ever supported, are tombstones or key destruction plus a
new fact, not UPDATE/DELETE of history.

Projections, snapshots, CLI reports and UI boards are rebuildable consumers.
A complete fold, a checkpoint/resume fold, and EventStore replay MUST agree.
RunControl MUST NOT persist a Run table as a competing source of truth.

Large bodies live in content-addressed artifacts; events keep references and
metadata. Secrets MUST NOT ride in widely logged envelope attributes.

SQLite artifact index tables, persistent projection materialization, and a
verified high-water cache for RunControl remain later slices. They MUST keep
this rebuild-equals-truth rule.

## Consequences

- Adapters cannot hide a state change behind an undeclared type or a mutated
  row.
- Unknown, lost, failed and cancelled stay distinct because they are facts,
  not dashboard inferences.
- A host administrator who rewrites the database file is outside the M0
  threat model; there is no signature chain in this milestone.

## Validation

EventStore triggers reject UPDATE/DELETE/REPLACE. Run/Attempt replay tests
prove fold/checkpoint/EventStore equality. RunControl rebuilds from verified
events before every append. Artifact CLI reports are not durable SQL metadata.

## References

- [Project charter v0.1 §5 P5, P8 and §8.3](../charter-v0.1.md)
- [Chapter 18 decision 6-DBC](../chapter-18-decision-guide-v0.1.md)
- [ADR-0014 CloudEvents-Compatible ResearchEvent](0014-cloudevents-compatible-research-event.md)
- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0024 Pure Run and Attempt State Machine](0024-run-attempt-state-machine.md)
