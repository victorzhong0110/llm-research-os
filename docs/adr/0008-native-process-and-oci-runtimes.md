# ADR-0008: Native Process and OCI Runtimes

- Status: Accepted
- Accepted in: Project charter v0.1
- Standalone record transcribed: 2026-09-01

## Context

Research workloads span two materially different execution environments. Local development,
Apple MPS and explicitly installed custom Python code need a lightweight supervised process path.
Linux/CUDA training, arbitrary code and portable high-risk workloads need a stronger packaging and
isolation boundary. Requiring OCI for every local helper would make the local path unnecessarily
heavy, while treating every workload as a host process would grant arbitrary code the control
plane's trust and ambient authority.

The protocol therefore needs one task meaning that can be implemented by more than one runtime,
without pretending that the two runtimes provide the same isolation. A manifest declaration is
inert data and cannot itself grant permission to start either runtime.

## Decision

Support both runtime families behind Worker semantics that remain independent of transport:

- `NativeProcessRuntime` is the local supervised-process path for Apple MPS, reviewed custom code
  and workloads that cannot or should not use a container.
- `OCIContainerRuntime` is the portable Linux/CUDA path and the default boundary for high-risk
  training or arbitrary-code execution. Images will be selected by immutable digest, not a mutable
  tag alone.

Both paths must consume an immutable planned task, exact manifest and configuration digests,
explicit authorization, bounded resources and an executor-specific preflight. They must preserve
separate completed, failed, cancelled, lost and unknown outcomes. Runtime adapters do not mint
approval merely because a plan is `ready` or a manifest names an entrypoint.

The conservative M0 native profile is narrower than the eventual runtime:

- exactly one isolated Python task;
- a fixed JSON-object-over-stdio runner protocol;
- `shell=false` with fixed trusted-runner argument construction;
- denied network, an empty environment allowlist and a requested isolated temporary workspace;
- explicit wall-time, stdout, stderr and termination-grace ceilings;
- no ports, host resources, secret scope, paid action or additional permission;
- an entrypoint included only through its digest in the public review report.

M0 implements only a pure `NativeProcessPreflight` for that profile. Its report deliberately says
`launchAllowed=false`, `isolation=not-enforced` and `execution=not-executed`. It does not resolve an
interpreter, create a workspace, import a module, open an artifact, spawn a process, send a signal,
persist a receipt or enforce the requested constraints. The actual native executor requires a
separate reviewed slice. OCI execution remains an M2 capability and is not approximated by the
native preflight.

## Consequences

- Local and container execution can share plan, event and Worker semantics without sharing an
  unsafe implementation or overstating equivalent isolation.
- Native execution remains possible where OCI is unavailable, but its narrower trust and host
  exposure must be explicit in policy and audit data.
- High-risk workloads can require OCI or a remote Worker even when a native adapter exists.
- The control plane can review a complete native launch shape before any executable code is added.
- Secret injection, authenticated and durable authorization, interpreter identity, enforceable
  isolation, artifact materialization, lifecycle persistence, cancellation races and output
  handling remain gates for the future executor.

## Validation

The current preflight slice tests exact four-digest binding, authorization re-evaluation, sealed
registry identity, single-task selection, the fixed capability/runtime/protocol profile, every
resource limit, report digest tampering, non-echo of configuration and entrypoint values, and
tripwires for imports, processes, signals, network and persistence.

## References

- [Project charter v0.1](../charter-v0.1.md)
- [NativeProcessPreflight protocol](../protocols/native-process-preflight-v0alpha1.md)
- [M0 Native Process Preflight guide](../guides/m0-native-process-preflight.md)
- [ADR-0003 Minimal Trusted Kernel](0003-minimal-trusted-kernel.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
