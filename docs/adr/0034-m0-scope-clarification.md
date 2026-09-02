# ADR-0034: M0 Scope Clarification for Native Process Execution

- Status: Accepted
- Decision date: 2026-09-02

This record does not reopen ADR-0008. It supersedes only the milestone assignment
“`NativeProcessRuntime` is an M0 deliverable” in charter §14.2. The long-term dual-runtime
architecture (native process plus OCI) remains accepted.

## Context

Charter v0.1 §14.2 listed `NativeProcessRuntime` among the M0 kernel-proof deliverables.
That original commitment is still the historical baseline.

The accepted M0 security boundary is narrower. ADR-0008 already states that M0 implements only a
pure `NativeProcessPreflight` for a conservative single-task Python profile, and that the actual
native executor requires a separate reviewed slice. NativeProcessPreflight, ADR-0030–0032 and the
living threat model all treat a preflight report as review data, not launch permission:

- `launchAllowed=false`
- `isolation=not-enforced`
- `execution=not-executed`
- no interpreter resolution or start
- no task-module import
- no child-process creation or supervision
- no signals
- no network, secret, GPU or paid action
- the report is not an authorization credential

The current `plan.authorization.evaluated` fact is audit-only. ADR-0032 records that no runtime
consumes it, and that it is not a signed, authenticated or revocable launch token.

Leaving charter §14.2 unannotated would silently contradict README, ADR-0008 and the threat model.
Charter §0 requires an ADR when an accepted decision changes.

## Decision

For M0, replace the milestone assignment of `NativeProcessRuntime` with `NativeProcessPreflight`.

- M0 native-process scope stops at the existing non-launchable preflight contract.
- A real `NativeProcessRuntime` is deferred until after M0. The earliest later placement is a
  separate M1 security-review slice. This ADR does not commit a delivery date.
- `OCIContainerRuntime` remains an M2 direction, as already decided in charter §14.4 and ADR-0008.
- This is a security-scope correction, not a cancellation of native-process support.

## M0 closure boundary

M0 is closed for native process execution when all of the following are true and independently
checkable:

1. Charter §14.2 still shows the original `NativeProcessRuntime` line as history, with this
   erratum adjacent.
2. The implemented native surface is `NativeProcessPreflight` only. Successful reports keep
   `launchAllowed=false`, `isolation=not-enforced` and `execution=not-executed`.
3. No M0 command resolves an interpreter, imports a task module, creates or supervises a
   subprocess, sends a signal, or performs network, secret, GPU or paid work for a native task.
4. Plan authorization remains an exact three-digest gate. The optional
   `plan.authorization.evaluated` event remains unauthenticated, `authority=audit-only` and
   `execution=not-executed`. No runtime consumes it as executable authority.
5. The only M0 executable path that writes lifecycle facts is the zero-side-effect
   `SimulatedRuntime` after that in-process gate.
6. `OCIContainerRuntime`, remote Workers and a real `NativeProcessRuntime` are absent from the
   M0 deliverable set.

Adjacent M0 kernel-proof work already accepted elsewhere (ResearchSpec, ResearchEvent, SQLite
facts, local artifact objects, Run/Attempt, RunControl, authorization CLI, cancellation CLI) is
unchanged by this erratum.

## Deferred execution gates

A future `NativeProcessRuntime` must not start until the existing ADR and threat-model gates are
satisfied, including:

- authenticated, durable execution authorization that a runtime consumes; the current audit-only
  `plan.authorization.evaluated` event is not that credential
- typed `SecretRef` and a general redaction / output policy
- immutable identity binding for interpreter, runner, entrypoint and no-shell argv
- enforceable workspace, network, environment and resource isolation
- stdout/stderr, timeout, termination grace, cancellation races and child-process supervision
- durable execution receipts in Run/Attempt, events and artifact lineage
- a new threat-model review before any executable process path is merged

These gates are restated from ADR-0008, ADR-0030–0032, NativeProcessPreflight and the threat
model. This ADR does not invent a new protocol.

## Consequences

- Readers of the charter can trace the original M0 list and the later security correction.
- README, ADR index, ADR-0008 and this record now agree: M0 does not deliver a native executor.
- Contributors must not treat preflight success, `authorized` status, or an audit event as
  permission to spawn a process.
- NativeProcessRuntime remains the accepted local supervised-process direction after the gates
  above. OCI remains the portable Linux/CUDA / high-risk path and an M2 capability.

## Impact on the original charter commitment

| Original §14.2 item | Effect of this ADR |
|---|---|
| `NativeProcessRuntime` as an M0 deliverable | Milestone assignment superseded. The line is retained as history. M0 substitute is `NativeProcessPreflight`. |
| Dual-runtime architecture (`NativeProcessRuntime` and `OCIContainerRuntime`) | Unchanged. Still ADR-0008. |
| `OCIContainerRuntime` in M2 | Unchanged. |
| No paid GPU in M0 | Unchanged. |

This is an accepted-baseline correction under charter §0. It does not rewrite §14.2 history, does
not move OCI into M0 or M1, and does not schedule the native executor.

## References

- [Issue #18](https://github.com/victorzhong0110/llm-research-os/issues/18)
- [Project charter v0.1 §14.2](../charter-v0.1.md)
- [ADR-0008 Native Process and OCI Runtimes](0008-native-process-and-oci-runtimes.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
- [ADR-0031 Explicit Non-Credential Plan Authorization CLI](0031-explicit-plan-authorization-cli.md)
- [ADR-0032 Audit-only Plan Authorization Events](0032-audit-only-plan-authorization-events.md)
- [NativeProcessPreflight protocol](../protocols/native-process-preflight-v0alpha1.md)
- [M0 Native Process Preflight guide](../guides/m0-native-process-preflight.md)
- [Living threat model](../security/threat-model.md)
