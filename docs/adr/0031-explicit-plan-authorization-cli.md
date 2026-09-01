# ADR-0031: Explicit Non-Credential Plan Authorization CLI

- Status: Proposed
- Date: 2026-09-01

## Context

ADR-0030 added a pure in-process authorization gate, but external callers still had no stable way
to provide an exact policy or inspect its normalized result. Ad hoc Python construction would make
field spelling, list semantics, exit codes and error handling caller-specific. Exposing the result
carelessly could also encourage a deterministic digest to be mistaken for an authenticated or
durable approval receipt.

This boundary must become inspectable before a NativeProcessRuntime is considered, while retaining
M0's zero-execution safety properties.

## Decision

Add two closed v0alpha1 documents and one local command:

- `PlanAuthorizationRequest` carries the exact `(specDigest, registryDigest, planDigest)` binding,
  explicit capability and permission grants, and explicit planner-requirement decisions.
- `PlanAuthorizationReport` carries the normalized result and decision digest. Literal fields say
  that approval is `not-authenticated`, the report is `not-persisted`, and execution is
  `not-executed`; all four side-effect counters are zero.
- `researchos authorize SPEC REQUEST` freezes and validates both local inputs, rebuilds the sealed
  registry, compiles a new DryRunReport, applies the request only to that report, and prints the
  versioned report.

Both schemas are alias-only, non-coercing and closed to unknown fields. Request collections must be
explicit JSON arrays. Duplicate grants and duplicate requirement IDs are rejected. Local loaders
reject duplicate mapping keys, YAML aliases and symbolic-link inputs.

The report model verifies sorted unique dispositions, status consistency, missing-access subsets,
disjoint requirement sets and a recomputed `decisionDigest`. The command returns `0` only for
`authorized`, `1` for a valid `pending` or `denied` report, and `2` for invalid input, planning,
registry or binding failures.

No actor field is accepted because this slice does not authenticate an actor. The command does not
create a receipt, append an event, open SQLite, write an artifact, invoke a runtime, import a block
entrypoint, contact a network, mint identity, evaluate an expression or execute a process.

## Consequences

- Researchers and future adapters can exchange one language-neutral, exact plan-bound policy input
  and independently validate the structural output.
- Re-running the same valid inputs yields the same normalized report and decision digest.
- A report can demonstrate what this reference evaluator computed, but cannot prove who approved
  it or that it remains valid after time, revocation or an external policy change.
- Real local processes, remote Workers and paid execution remain blocked on separate authority,
  secret, isolation, cancellation and durable-audit slices.

## Validation

Tests cover current Draft 2020-12 schemas, normative examples, alias-only strictness, duplicate and
malformed collections, semantic report tampering, all three dispositions and exit codes, exact
binding mismatch, nested-loop requirements, symlink rejection, secret non-echo, and tripwires for
process, import, network, EventStore, artifact-store and filesystem writes.

## References

- [PlanAuthorization protocol](../protocols/plan-authorization-v0alpha1.md)
- [M0 Plan Authorization CLI](../guides/m0-plan-authorization-cli.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
