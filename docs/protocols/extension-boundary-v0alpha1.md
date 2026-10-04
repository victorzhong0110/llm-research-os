# Extension mechanism and permission boundary (R14)

Status: Partial reviewed Python boundary. Exact integration and final checks are
recorded at [#136](https://github.com/victorzhong0110/llm-research-os/pull/136).
Full R14 and Checkpoint D are not accepted.
Requirements: [M3 plan R14](../plans/m3-development-plan.md#r14-minimal-extension-mechanism-and-permission-boundary).

## What this is

A small real extension surface with an explicit boundary, not a plugin framework.
It proves the boundary with a real adapter rather than leaving it as a
description.

## A manifest is data

Loading a manifest is inert. It is read with `O_NOFOLLOW`, size-bounded, parsed
as JSON, and validated — nothing is imported, evaluated, or fetched. An
`entryModule` is a *string to be run later, explicitly*. Two tests write a
marker file from the entry module and assert it does not exist after load, both
for a valid manifest and for one that is refused.

## A declared permission is a request, not a grant

Permissions form a closed set. A manifest naming anything outside it is
**refused at load time**, never silently narrowed — quietly dropping a
permission would hide a capability the author expected to have.

`NEVER_GRANTED` names capabilities this host will never provide, whatever a
manifest asks: `execution.launch`, `control.write`, `events.write`,
`artifacts.write`, `authority.create`, `secrets.read`, `network.outbound`. A
manifest asking for one is refused with `permission-never-granted`, which is
more useful than a timeout.

Compatible permission names are read-only: `artifacts.read`, `events.read`,
`evidence.read`, `ledger.read`, `metrics.read`. Parsing grants no capability
handles: public grantedPermissions is empty. The OS file/network permissions of
reviewed same-user code are not confined by these declarations.

## Compatibility is refused, not assumed

`contractVersion` must be a version this host implements. An unknown or
incompatible version is refused before anything else is trusted.

## Resource limits are bounded; untrusted code is refused

One reviewed same-user adapter may run in a subprocess with bounded message
size, wall-clock duration, stdout and stderr, and POSIX resource limits. It
receives the request on stdin and its own identity in the environment. It never
receives a control-store connection, a Worker credential, or the caller's
environment.

**A limit is a bound, not a sandbox.** The registry refuses `trust="untrusted"`
with `trust-unsupported`, because this host implements no verified isolation
profile and pretending otherwise would be the exact claim the plan forbids.

### The enforced set is probed, not assumed

macOS rejects `RLIMIT_AS`. A limit that cannot be applied is not a limit, so
`effective_limits()` probes the platform once and
`ExtensionRegistry.capability_surface()` reports the set that is *actually
enforced* — on macOS that is `cpuSeconds` and `openFiles`, not the three the
host asks for. Reporting the requested set would over-claim.

## A crash or a hang cannot damage the control plane

Adapter crash, exit-code failure, wall-clock timeout, and oversized output are
each bounded and each leave the registry intact; a test runs a crashing
extension and then resolves a healthy one.

Output is capped while reading. Overflow stops the owned process group and
returns error with outputLimitExceeded=true; byte counts describe retained text.
No Python preexec_fn runs in a forked multithreaded host. A dedicated bounded
pipe records each invocation's actually applied limits.

## Disable and uninstall

Disable makes `resolve` and registry `run` refuse the extension. Registry `run`
requires reviewed-same-user trust; inert installation does not authorize dispatch. Uninstall removes the registry
entry and **does not delete the manifest file**: that file is the operator's,
and this surface does not delete what it did not create.

The registry is bounded (32 by default) and the enabled set has a content
digest, so a plan can bind to exactly which extensions were present.

## What is not delivered

- **No evaluator or provider extension point is exercised with a real external
  extension.** The boundary is proven with one inline reviewed adapter. Adding a
  registry of extension *types* (bricks, evaluators, providers) with a real
  third-party extension is not done. Recorded as a gap.
- **No `researchos extensions` CLI command**; the surface is currently a Python
  API only.
- **The existing `BlockRegistry` is not merged into this one.** The two remain
  separate: blocks are declared in a spec, extensions are installed from disk.
  Recorded as a gap rather than a silent duplication.

## Out of scope, by the plan's own words

No marketplace, no automatic third-party installs, and subprocess separation is
never described as a malicious-code sandbox.

The versioned input and all public output documents are registered as
`extension-document` under `researchos schema`. Manifests must be regular files,
bounded finite JSON, and immutable snapshots. Registry identity also binds trust.
Disable affects future dispatch only; it does not cancel an in-flight adapter.
