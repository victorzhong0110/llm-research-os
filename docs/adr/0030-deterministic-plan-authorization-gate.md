# ADR-0030: Deterministic Plan Authorization Gate

- Status: Proposed
- Date: 2026-09-01

## Context

ADR-0023 deliberately made a `ready` DryRunReport mean only that static planning completed.
Every planned task still records `authorization: not-evaluated`; BlockManifest capabilities and
permissions are declarations rather than grants, and planner-emitted approval requirements remain
`required-not-evaluated`. Treating `ready` as executable would let a low-level adapter bypass the
researcher's capability, budget and approval policy.

An authorization decision must also be invalidated when the exact ResearchSpec, sealed registry or
semantic plan changes. Matching only `planDigest` is insufficient because v0alpha1 deliberately
excludes `specDigest` from that digest.

## Decision

Add a pure trusted-kernel function, `authorize_plan(report, policy)`, with these rules:

- The DryRunReport is defensively serialized and semantically revalidated. Only a complete `ready`
  report can reach evaluation.
- Policy input binds the exact `(specDigest, registryDigest, planDigest)` triple. Any mismatch fails
  closed rather than producing a reusable decision.
- Declared capabilities and permissions are collected across every task, including symbolic loop
  bodies. Grants are least-privilege: duplicate, malformed, unknown or plan-unused entries are
  rejected instead of ignored.
- Each planner-emitted `policyRequirement.id` may have exactly one explicit `approved` or `denied`
  decision. Unknown or duplicate decision ids are rejected.
- A missing capability or permission grant is `denied`. An explicit requirement denial is also
  `denied`; denial takes precedence over unresolved requirements. Otherwise a missing requirement
  decision is `pending`. Only complete grants plus approvals yield `authorized`.
- Output is an immutable normalized result. Its `decision_digest` binds the digest triple and sorted
  per-capability, per-permission and per-requirement dispositions. Input ordering cannot change it.
- Error text and result objects never include task config, approval prompt bodies or rejected
  caller values.

The gate performs no authentication, clock/UUID generation, file/database write, ResearchEvent
append, network request, plugin/runtime invocation, GPU action or paid operation. The decision
digest is an in-process reference value, not a signed credential or durable approval receipt.

`SimulatedRuntime` now invokes the gate after its canonical-manifest checks and before reading the
simulated outcome or writing lifecycle facts. Its fixed T0 policy grants only the canonical
zero-side-effect `simulate` capability. Plans with permissions or policy requirements remain
unsupported and produce zero writes.

## Consequences

- `ready`, `pending`, `denied` and `authorized` are now distinct states in the trusted execution
  path. Only `authorized` is executable.
- A plan edit, registry substitution or ResearchSpec revision change invalidates the old policy
  binding even when another digest happens to remain unchanged.
- Exact grants catch stale and over-broad one-plan policy inputs. A future reusable organization
  policy may be broader, but it must compile to this exact plan-bound form before execution.
- M0 still has no external PlanAuthorizationRequest/Receipt Schema, authenticated approver,
  signature, expiry/revocation, persistent decision event, budget consumption ledger or CLI. Those
  require a later protocol slice before real runtimes or remote callers rely on authorization.

## Validation

Tests cover automatic authorization for the exact T0 capability, missing capability/permission
denial, pending/approved/denied requirements, denial precedence, nested-loop collection, all three
binding digests, blocked and tampered reports, duplicate/unknown/malformed policy input,
order-independent decision digests, plan-change invalidation, immutability, secret non-echo and
process/import/network/filesystem tripwires. SimulatedRuntime and CLI regression tests prove the
gate remains before the first EventStore write.

## References

- [M0 Plan Authorization](../guides/m0-plan-authorization.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
- [ADR-0023 Inert Manifests and Pure Dry-Run](0023-inert-manifests-and-pure-dry-run.md)
- [ADR-0026 Deterministic SimulatedRuntime](0026-deterministic-simulated-runtime.md)
