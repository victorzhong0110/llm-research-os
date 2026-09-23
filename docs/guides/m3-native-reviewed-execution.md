# M3 reviewed native execution contract (R03)

Validation-only contract for one reviewed Python task. Normative record:
[Native reviewed execution v0alpha1](../protocols/native-reviewed-execution-v0alpha1.md).
Constraint record:
[ADR-0065](../adr/0065-reviewed-native-execution-authority.md).

This package does **not** start user code. `researchos native run` remains the
fixed `restricted-v0alpha1` noop. `execute.native` is registered and is not an
alias for `execute.local`, `process.native`, `execute.oci`, `execute.gpu`, or
`execute.mps`. No Worker runtime honors the new capability. A successful
validation report is not a launch credential, and `launchAllowed` is constantly
false in the generated report schema.

## What the validator checks

`llm_research_os.execution.native_reviewed` parses a bounded JSON request and
compares it with a caller-supplied verified-prefix citation and optional grant
contract view. Caller-supplied prefix citations, prepared citations, and grant
booleans are contract fixtures only in R03. Before using a report for any
preparation or launch decision, an R04 or R05 adapter must independently
rebuild and verify the real facts and bytes. This package does not implement
those adapters.

1. Unknown fields, noncanonical digests, duplicate input names, path-shaped
   entrypoints or interpreters, and unsupported OS / architecture / ABI fail
   closed.
2. Project, revision, workflow, task, Run, Attempt, Worker, actor, and the
   cited `plan.authorization.evaluated` digests must match the citation.
   `execute.local` or `process.native` is not accepted as `execute.native`.
   An application receipt or AI proposal is not an authorization decision.
3. Code bundle, entrypoint, inputs, config digest, interpreter, dependency
   lock, and inventory must match both the citation and the prepared bytes.
4. Network, filesystem, and memory isolation are **not enforced** on this
   profile. A required restriction is refused. An advisory restriction is
   reported as `not-enforced` plus an explicit unsupported token. Wall-clock
   and output ceilings are recorded as requested and `not-enforced`; R03 has
   no runner that implements them.
5. Grant expiry, revocation, HMAC failure, nonce replay, and a consumed or
   resumed claim are contract checks only. The grant also binds the same
   project, Run, task, Attempt, Worker, bundle, and config as the request.
   The validator does not consume a nonce or spawn a second process.

The canonical `configDigest` is the JCS digest of the execution object
(`profile`, platform, code, inputs, environment, limits, restrictions). Grant
`imageDigest` binds the reviewed bundle (`sha256:`). Old media types such as
`researchos.python-brick/v0alpha1` cannot satisfy that binding.

## Examples

Valid Linux and macOS requests, with reports that identify unsupported
network, filesystem, and memory restrictions:

- `examples/native-reviewed-execution/valid/linux-request.json`
- `examples/native-reviewed-execution/valid/darwin-request.json`

Invalid documents live under `examples/native-reviewed-execution/invalid/`.
Grant fixtures under `invalid/grants/` are contract checks, not Worker
sessions.

Schemas are generated from the Pydantic models and registered as
`native-reviewed-execution-request` and `native-reviewed-execution-report`.
Do not edit the JSON Schema files by hand.

## Platform evidence

Supported request pairs are `linux/x86_64`, `linux/aarch64`, `darwin/x86_64`,
and `darwin/arm64`, with CPython ABI `cp312`, `cp313`, or `cp314` matching the
declared 3.12/3.13/3.14 version. `observe_host_feasibility()` reports the
machine running the validator. On that host, network, filesystem, memory,
process-group, wall-clock, and output-byte enforcement are all false, and
`launch_implemented` is false. A macOS request validated on Linux is a
contract check, not a live macOS execution. Real entrypoint execution remains
R05. Issue #53 stays open.
