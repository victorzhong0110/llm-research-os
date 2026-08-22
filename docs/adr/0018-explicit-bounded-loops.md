# ADR-0018: Explicit Bounded Research Loops

- Status: Accepted
- Date: 2026-08-21

## Context

Research needs iterative train-evaluate-revise behavior, but arbitrary graph cycles make termination, cost, recovery and audit semantics ambiguous.

## Decision

Every workflow graph is acyclic at its own level. Iteration is represented by an explicit `LoopBlock` containing a nested graph and a mandatory `maxIterations` value. A loop that declares or references paid or accelerated capability also requires `maxCost` and `maxWallTimeSeconds`.

The `until` condition uses the inert `researchos.expr/v0alpha1` declaration. M0 validates and records it but does not evaluate arbitrary user code. Retry and research iteration remain distinct concepts.

## Consequences

- Static validation can reject accidental cycles and unbounded cost paths.
- Nested attempts can later receive stable event and checkpoint semantics.
- Dynamic AI graph mutation creates a new ResearchSpec revision rather than silently modifying a running revision.

## Validation

Tests reject implicit cycles, unknown edge targets and accelerator-backed loops without cost and time caps.

## References

- [Argo Workflows retry semantics](https://argo-workflows.readthedocs.io/en/release-4.1/retries/)
- [Temporal error-handling patterns](https://docs.temporal.io/design-patterns/error-handling-patterns)
