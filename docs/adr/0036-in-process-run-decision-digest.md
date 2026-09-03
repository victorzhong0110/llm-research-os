# ADR-0036: In-process Plan Authorization Decision Digest on RunSnapshot

- Status: Accepted
- Implemented for review: 2026-09-03

## Context

ADR-0030's gate already computes a deterministic `decisionDigest` before
SimulatedRuntime writes any lifecycle fact. ADR-0032 made a recomputed copy of
that decision durable as an audit-only `plan.authorization.evaluated` event.
ADR-0035 reconstructs those audit facts for a plan identity.

None of those slices recorded which in-process decision a Run actually passed.
`RunSnapshot.digests` carried only `spec`, `registry` and `plan`. Issue #19
still needed a way to answer “which authorization identity gated this Run?”
without treating an audit event as launch authority.

Citing `{eventId, sequence}` of `plan.authorization.evaluated` from the
lifecycle reducer would bind execution identity to the audit log. ADR-0034
forbids any runtime from consuming that event as executable authority.

## Decision

SimulatedRuntime keeps the in-process `authorize_plan` result and writes its
`decisionDigest` on `run.queued`. The pure reducer copies that optional field
onto `RunSnapshot.digests.decisionDigest`.

Rules:

1. The value is the same tagged semantic digest the gate already returns. It is
   not recomputed by the reducer and not read from EventStore authorization
   events.
2. `run.queued` remains the immutable binding event. After it, `decisionDigest`
   MUST NOT change. Later lifecycle types stay no-ops for this field.
3. The field is optional on the generic Run/Attempt contract. Traces that never
   passed a gate may omit it. JSON `null` is invalid; omit the key or supply a
   tagged digest.
4. SimulatedRuntime always writes the field. Resume requires the rebuilt
   snapshot to carry the same digest the current gate recomputes. A missing or
   different value is a mismatched existing Run.
5. The field is a gate-evaluation identity. It is not a signature, expiry,
   revocation, authenticated actor, audit-event citation, or launch token.
6. `authorizations find` remains a separate read-only join. A snapshot digest
   MAY be used as that query's optional filter. A match still does not prove
   the Run consumed the listed fact.

This slice does not add `authorizationRef`, does not fold
`plan.authorization.evaluated` into Run state, and does not change
NativeProcessPreflight or NativeProcessRuntime.

## Consequences

- A SimulatedRuntime snapshot can answer which in-process decision identity
  gated the Run, and EventStore replay rebuilds the same snapshot.
- Generic conformance traces without a gate remain valid.
- Authenticated credentials, event citations, expiry, revocation and runtime
  consumption of audit facts remain blocked and need their own ADR plus
  threat-model review.

## References

- [Issue #19](https://github.com/victorzhong0110/llm-research-os/issues/19)
- [Run/Attempt State v0alpha1](../protocols/run-attempt-state-v0alpha1.md)
- [ADR-0024 Pure Run and Attempt state machine](0024-run-attempt-state-machine.md)
- [ADR-0026 Deterministic SimulatedRuntime](0026-deterministic-simulated-runtime.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
- [ADR-0032 Audit-only Plan Authorization Events](0032-audit-only-plan-authorization-events.md)
- [ADR-0034 M0 Scope Clarification](0034-m0-scope-clarification.md)
- [ADR-0035 Read-only Plan Authorization Lineage Query](0035-read-only-plan-authorization-lineage.md)
