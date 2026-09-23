# ADR-0065: Reviewed native Python authority and platform boundary

- Status: Accepted for the R03 contract; no real native runner is accepted
- Date: 2026-09-23

## Context

R02 provides project-bound application operations and durable receipts. M0
`NativeProcessPreflight` is non-launching. The M3 slice 1
`restricted-v0alpha1` runtime runs a fixed noop helper after local
authorization consumption, but never imports the declared entrypoint and
never records a Worker grant or Run/Attempt lifecycle. M2 `execute.local`
grants authorize the existing host Python brick, whose environment is not a
general code sandbox. Neither permission is sufficient for a new reviewed
native entrypoint. An application receipt and a detached Ed25519 audit
attestation are also not launch credentials.

R03 fixes the meaning of a real native profile before R04 prepares immutable
inputs and R05 consumes authority and launches it. This ADR establishes a
contract, not an implementation or live-host result. It supplements ADR-0008,
ADR-0043, ADR-0050, ADR-0054, and ADR-0063 without changing their historical
acceptance.

## Decision

### Trust and platform

The first real profile is `native-reviewed-python/v0alpha1`, on a local,
user-owned Linux or macOS host with POSIX process-group supervision. It
executes a **specific reviewed Python entrypoint** and a pinned environment.
The researcher trusts that code and its reviewed dependency closure with the
host user's privileges. It is not a sandbox for arbitrary untrusted code.
Windows, SSH execution, GPU training, arbitrary shell commands, plugin
loading, dynamic package installation at launch, and mutable import paths are
outside this profile. A platform not explicitly supported and verified by
the eventual runner fails closed. Declaring the profile in a document does
not make it executable.

The existing `restricted-v0alpha1` noop profile and M0 preflight keep their
current meaning and command names. They MUST NOT be promoted to real-entrypoint
evidence. The macOS/MPS training profile and OCI profiles remain separate.

### Authority and identity

Introduce a distinct `execute.native` capability for the reviewed profile.
It is not an alias for `execute.local`, `process.native`, `execute.oci`,
`execute.gpu`, or `execute.mps`. Existing authorizations for those capabilities
MUST NOT be widened retroactively. R03 schemas and feasibility tests may
register the new capability; no executor may honor it until R04/R05 satisfy
the preparation and consumption rules below. The existing `process.native`
preflight may be cited as a non-launching review, never substituted for the
Worker grant.

Every request MUST bind project, immutable spec revision, workflow, planned
task node, Run and Attempt; the authorized spec, registry, plan and decision
digests; a reviewed code bundle and entrypoint; all executable configuration
and input artifact digests; an interpreter and dependency/environment
inventory; profile version; and closed resource ceilings. The planned task's
execution object and the Worker grant's `imageDigest` and `configDigest`
MUST represent the same exact versioned object. The digest mapping and any
new media type MUST be explicit and deterministic; a file path, tag, Python
version string, or application receipt alone is not an executable identity.
Unknown or absent binding fields fail closed. R04 must make these immutable
bytes verifiable through preparation and the last check before process start;
it must not claim that hashing a mutable path alone prevents substitution.

Authorization uses the existing EventStore citation of a human, authorized
`plan.authorization.evaluated` fact, then the existing Worker grant/session,
lease, claim, expiry, revocation, nonce-consumption, and Run/Attempt lifecycle.
The grant is bound to `execute.native`, the exact planned task and execution
object, one Worker and one Attempt. No second token format, authorization
database, independent task ledger, or signature-based launch authority is
introduced. A stale, foreign, substituted, expired, revoked, or replayed
grant MUST NOT start user code. An R02 receipt records an application
operation; it cannot issue a Worker grant by itself.

The **launch linearization point** is the atomic Worker claim/consume
transition for the matching lease and grant, after all binding and current
revocation checks, and before any process capable of importing user code is
spawned. Revocation committed before that transition denies launch. After
that transition, revocation becomes a cancellation request plus observation;
it cannot be reported as proof that the process never started or has stopped.
An idempotent resumed claim MUST NOT spawn again. If the controller or Worker
crashes between consumption, process creation, and durable execution identity,
the attempt remains unknown until reconciled; no automatic rerun is allowed.
R05/R06 must supply the durable intent, identity and real observation evidence
for that interval. `cancel-observed` requires confirmed stop of the execution
group; an unverifiable PID, failed probe, or vanished identity is unknown.

### Isolation claims

Every report separates **requested**, **enforced**, and **unsupported**
restrictions for network access, filesystem access, and memory. The initial
reviewed host process has no guaranteed network or filesystem isolation:
an empty/allowlisted environment, closed working directory, and `shell=false`
do not deny sockets, host file reads, subprocesses, or dynamic imports.
Process-group supervision, wall-clock and output byte bounds may be reported
as enforced only when the runner actually provides and tests them. Memory
limits cannot be reported as enforced from a requested number or a best-effort
monitor alone. The implementation must state platform-specific enforcement
and verify it. If policy requires a restriction the selected host/profile
cannot enforce, preparation and launch both refuse before user code starts.
There is no silent downgrade from required to advisory. Where no isolation is
required, the report visibly records `not-enforced` and the user-owned,
reviewed-code trust assumption. No credentials or unrelated control-plane
SQLite/CAS root may be exposed to the child through arguments, environment,
mounts, or a shared writable directory.

### Artifact and evidence meaning

The R03 request and report contract is specified in
[Native reviewed execution v0alpha1](../protocols/native-reviewed-execution-v0alpha1.md).
R03 report outcomes are validation/refusal only; `launchAllowed` is false
until an R05 runner is implemented and reviewed. A preflight success is not
a Run start. R04 proves prepared code and environment identity; R05 proves
real execution, bounded output, verified CAS artifacts and lifecycle facts;
R06 proves stop and recovery. Claims for SSH or a second host wait for R07/R08.

## Consequences and acceptance

- The implementer delivers versioned strict request/report models, generated
  schemas and valid/invalid examples, plus feasibility checks for Linux and
  macOS. Unknown fields, stale/substituted bindings, wrong capability,
  expiry, revocation, replay, unsupported profile/platform and required
  unenforceable isolation each have a fail-closed case. Negative tests must
  assert that no user entrypoint is imported or process started.
- R03 may add a pure validator, protocol documents, examples and tests. It
  must not use a successful R03 validation as permission to launch real code.
  R04/R05 each remain separately reviewable packages.
- The implementer reports the exact platform and environment under test and
  which restrictions are actually enforced. No CI skip or noop proves a real
  native task. Issue #53 stays open until the applicable later real execution
  and recovery evidence is reviewed.
- Any changed authority mapping, profile boundary or acceptance rule requires
  a proposed successor ADR and planning review, not a silent implementation
  shortcut.

## References

- [M3 plan, R03–R06](../plans/m3-development-plan.md)
- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0043](0043-m2-loopback-worker-and-hmac-grants.md)
- [ADR-0050](0050-observed-execution-identity.md)
- [ADR-0054](0054-process-observation-tristate.md)
- [ADR-0063](0063-m3-native-process-runtime-slice-1.md)
- [Worker grant contract](../protocols/authorization-grant-v0alpha1.md)
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53)
