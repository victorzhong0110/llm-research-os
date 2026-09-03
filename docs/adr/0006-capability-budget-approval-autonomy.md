# ADR-0006: Capability-, Budget-, and Approval-Based Autonomy

- Status: Accepted
- Date: 2026-08-21

## Context

Autonomy labels such as L1–L5 are useful UI presets, but they are not a
permission system. Granting “the model is large, therefore it may provision a
GPU” or relying on the model to respect a budget would violate charter P3.
Chapter 18 decision 15-AUC already chose per-capability authorization with
budgets and approvals, progressive exposure, and no size-based privilege.

M0 implements a deterministic plan-authorization gate and a T0 `simulate`
capability. It does not implement live budget consumption, authenticated
approvers, or L1–L5 presets. The accepted rule still needs a standalone
record so later runtimes cannot widen autonomy by renaming a preset.

## Decision

Real permission is the intersection of declared capabilities, numeric budgets
and explicit approvals. L1–L5, if introduced, are only preset bundles of those
primitives. They are not additional authority.

- Capabilities are least-privilege and plan-bound. Unused, unknown, duplicate
  or malformed grants fail closed.
- Budgets are counts, money, duration, GPU quantity, data scope, egress and
  similar caps attached to a capability. Protocol declarations are not runtime
  enforcement until a later slice proves consumption accounting.
- Approvals are exact, revocable grants for a stated requirement. They are not
  implied by `ready`, by a native preflight report, or by an audit-only
  authorization event.
- “Give the AI full control” means auto-approving inside an already declared
  envelope. It does not mint secrets, network, or unbounded spend.

Authenticated actors, signatures, expiry, revocation and runtime consumption
of durable approval facts remain separate security work.

## Consequences

- Future Worker and NativeProcessRuntime slices MUST consume the same
  capability/budget/approval primitives rather than a model-size or preset
  label.
- M0 SimulatedRuntime may execute only the exact T0 `simulate` grant after
  `authorize_plan` returns `authorized`.

## Validation

M0 tests cover exact three-digest binding, unused/unknown grants, nested
requirement decisions, and T0 SimulatedRuntime integration. Budget consumption
and authenticated approval remain untested executable gates.

## References

- [Project charter v0.1 §5 P3 and §9.4](../charter-v0.1.md)
- [Chapter 18 decision 15-AUC](../chapter-18-decision-guide-v0.1.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
- [Living threat model](../security/threat-model.md)
