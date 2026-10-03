# Reviewed native remote claim boundary (v0alpha1)

This R08 slice binds the existing `POST /v0alpha1/work/poll` native claim to
controller-owned, actual `ResearchSpec` and `BlockRegistry` inputs. It reuses the
existing Worker poll request/response and existing Run/Attempt events; there is
no new JSON document, schema, launch credential or authority ledger.

## Preconditions and binding

Native polling requires TLS, a verified Worker session, the recorded live
HMAC grant and an explicit `NativeControllerContext(spec, registry)` configured
by the trusted controller operator. The controller does not accept a spec,
registry, authorization decision or host PID from the Worker request body.
Without this context, native claims refuse before Run facts or grant consumption.
The default server remains compatible with other Worker runtimes.

The native request is reconstructed from the immutable queue/grant and cited
human authorization event. `require_authorized_execution_binding` rebuilds the
actual plan using the controller's spec and registry and checks project,
revision, workflow, planned task, spec/registry/plan/decision digests and execution
object. Metadata or a matching request digest alone cannot substitute for this.

The native poll body has exactly `workerId`, `grantToken` and integer
`waitSeconds: 0`; query suffixes, extra fields, duplicate required headers and
content/transfer encodings refuse. Poll bodies are bounded to 4096 bytes and a
10-second socket timeout. The TLS listener remains loopback-only for SSH tunnel
forwarding. No database or signing/private TLS key is exported to the Worker.

## Journal, consumption and replay

The controller holds the existing private cross-controller publication lock,
shared with native output publication. It appends `run.queued`, `run.started`
and `attempt.queued` with `maxAttempts: 1`, ordinal 1 and no retry lineage.
Stable IDs use `evt.native.remote.{runId}.{attemptId}.{type}`. An existing
local/foreign Run cannot be taken over. Replay verifies the recorded event data
against the full expected binding rather than merely trusting a matching ID.
Each new lifecycle append retains RunControl's expected-head CAS semantics.

The Attempt stays **queued**. These facts record dispatch preparation, not a
process start, import, successful result or observed stop. The existing Worker
plane then leases, claims and consumes its existing grant. Live material
scope is checked again after lifecycle I/O so intervening cancellation or
revocation prevents consumption.

A controller restart replays a matching partial Run journal. If a Worker lease
already exists, including an incompletely claimed persisted lease, every
successful replay returns `resumed: true`. It never turns that lease into fresh
launch permission. Terminal Runs refuse. An unknown/running Attempt without an
existing lease also refuses. A lost successful claim response therefore returns
the original lease with `resumed: true` on retry. The future remote executor must
never start user code from a resumed claim.

## Remaining scope

This slice does not create Worker processes, record process identities, reconcile
remote completion into Run success, or implement process recovery. No controller
PID observation can stand in for a Worker-local observation. The existing scoped
output protocol still records only its bound Worker completion receipt.
Remote launch/recovery and new two-host native evidence remain open. CPU remote
connectivity/execution, GPU runtime availability and remote GPU integration are
separate evidence dimensions; success in one does not imply the others. R08 and
Checkpoint B are not accepted by this slice; R09 remains frozen.
