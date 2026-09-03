# ADR-0037: M0 Kernel-Proof Closure

- Status: Accepted
- Date: 2026-09-03

This record does not reopen ADR-0008 or ADR-0034. It closes the M0 kernel-proof
milestone inside the ADR-0034 native-process erratum. M1 and M2 remain the next
accepted milestones.

## Context

Charter §14.2 defined M0 as a kernel proof: ResearchSpec, events, local storage,
SimulatedRuntime, CLI, failure/retry/cancel/unknown tests, and a deterministic
proposal/approval sample, with no paid GPU. ADR-0034 later replaced the milestone
assignment of `NativeProcessRuntime` with non-launchable `NativeProcessPreflight`.

Those capabilities now exist as tested code, versioned schemas and living
threat-model rows. Several constitutional ADRs (0005–0007, 0009) were accepted
in the charter but still lacked standalone records. Several implementation ADRs
(0023, 0025–0033, 0035–0036) were still marked Proposed after they had landed on
`main`.

Leaving M0 unmarked would keep later slices arguing about whether the kernel
proof is open. Treating SQLite artifact indexes, authenticated launch tokens or
a real native executor as part of this closure would erase ADR-0015 remainders
and ADR-0034.

## Decision

M0 kernel proof is closed on 2026-09-03.

### Delivered in this milestone

- ResearchSpec, BlockManifest and ResearchEvent `v0alpha1`, including generated
  JSON Schema and valid/invalid examples.
- Pure deterministic dry-run (ADR-0023).
- SQLite append-only EventStore with query, verify and replay. Persistent SQL
  projections and SQLite artifact-index tables are **not** included.
- Local content-addressed artifact objects and their explicit put/verify CLI.
- Pure Run/Attempt reducer, atomic RunControl append boundary, deterministic
  SimulatedRuntime, simulated-run CLI and cancellation-request CLI.
- Exact three-digest plan-authorization gate, non-credential authorize CLI,
  audit-only `plan.authorization.evaluated` recorder, read-only lineage query,
  and in-process `RunSnapshot.digests.decisionDigest` written by SimulatedRuntime.
- Native surface limited to `NativeProcessPreflight`
  (`launchAllowed=false`, `isolation=not-enforced`, `execution=not-executed`).
- CLI create/validate/simulate/cancel/view-events/artifact/authorize/preflight
  paths, including the CLI package split and typed simulation/cancellation
  problem codes.
- Failure, retry, cancel and unknown paths covered by tests. The deterministic
  proposal/approval sample is the plan-authorization gate plus T0 simulate, not
  a live model adapter.
- Short ADRs 0005, 0006, 0007 and 0009 written. Implementation ADRs listed
  above accepted as M0 deliverables.

### Explicitly not in this closure

These remain later work. They MUST NOT be described as M0 complete:

- `NativeProcessRuntime`, `OCIContainerRuntime`, remote Workers, paid GPU.
- Treating `plan.authorization.evaluated` as a launch credential; signatures,
  expiry, revocation; `{eventId, sequence}` citations; any runtime consuming
  that audit fact. Issue #19 stays open for those M1 items.
- Authenticated actors, typed `SecretRef`, interpreter identity and enforced
  isolation.
- SQLite artifact index, GC, persistent projection materialization
  (ADR-0015 remainder).
- RunControl verified high-water cache, ResearchEvent payload size/depth caps,
  DCO/CLA, TM-018 corpus expansion, L3 parameter evolution (Issue #26).

### Status changes this record authorizes

| Record | Change |
|---|---|
| ADR-0005, 0006, 0007, 0009 | Record status: pending → written. Decision already accepted. |
| ADR-0023, 0025–0033, 0035, 0036 | Decision status: Proposed → Accepted. Scope unchanged. |
| ADR-0015 | Unchanged. Artifact SQL index and persistent projections still pending. |
| ADR-0008 / 0034 | Unchanged. Native executor still not an M0 deliverable. |
| Issue #19 | Remains open. M0 recorded in-process `decisionDigest` only. |
| Issue #26 | Remains open and outside M0. |

## Consequences

- Charter §14.2 keeps the original list and the ADR-0034 erratum, then records
  this closure adjacent to them. History is not rewritten.
- README current-status and the threat-model header MUST say the kernel proof
  is closed and MUST keep listing residual M0 risks.
- Later executable capability (native process, Worker, model adapter, budget
  consumption) needs its own ADR, threat-model review and tests. It cannot land
  as “finishing M0”.
- `authorized`, preflight success, lineage matches and `decisionDigest` remain
  non-credentials.

## Validation

Independently checkable:

1. `main` contains the delivered surfaces above and not NativeProcessRuntime,
   OCI, Workers or paid-GPU adapters.
2. `researchos schema --check-all`, ruff, mypy, pytest and `uv build` pass on
   that tree.
3. Successful native preflight reports still deny launch.
4. No runtime reads `plan.authorization.evaluated` as executable authority.
5. Issue #19 and #26 remain open.

## References

- [Project charter v0.1 §14.2](../charter-v0.1.md)
- [ADR-0008 Native Process and OCI Runtimes](0008-native-process-and-oci-runtimes.md)
- [ADR-0015 SQLite Event Source](0015-sqlite-event-source-projections-and-artifacts.md)
- [ADR-0034 M0 Scope Clarification](0034-m0-scope-clarification.md)
- [ADR-0036 In-process Run decisionDigest](0036-in-process-run-decision-digest.md)
- [Issue #19](https://github.com/victorzhong0110/llm-research-os/issues/19)
- [Issue #26](https://github.com/victorzhong0110/llm-research-os/issues/26)
- [Living threat model](../security/threat-model.md)
