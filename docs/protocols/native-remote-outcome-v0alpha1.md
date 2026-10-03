# Remote native outcome v0alpha1 (R08 slice)

`POST /v0alpha1/native/outcome` reconciles the single existing remote Attempt.
The closed request embeds the original `NativeStartRequest`, an observation
(`running`, `exited`, `unknown`) and outcome (`completed`, `failed`, `cancelled`,
`unknown`). Terminal outcomes require `exited` in both Python and JSON Schema.
No PID, host path, alternate request or launch authority is accepted.

## Binding and fact precedence

The controller verifies the signed consumed grant, claimed lease, Worker/task/
Run/Attempt binding and original immutable start journal. All existing remote
queue/start events must match exactly. This is observational reconciliation of
previously consumed authority, including after expiry; it cannot extend authority
or launch work. It does not require new spec submission or controller access to
Worker process IDs. Reports are authenticated Worker statements, not independent
controller OS measurements. This preserves the existing trusted Worker boundary.

Completion additionally requires existing verified `work.completed`, bounded CAS
bytes, SHA-256, canonical task output and the exact result digest. It appends
`attempt.succeeded` and `run.completed`. Failure requires normal live result
authority or the same persisted `native-task-failed` Work fact. Cancellation
requires existing cancel intent (including a revoked grant converted into
`run.cancel.requested`) and the existing observed-cancellation Work operation.
A completed Work result is replayable after cancellation/expiry; pending output
cannot bypass cancelled or revoked authority. A failed/cancelled Work fact cannot
be replaced by a competing phase.

Terminal reports receive exclusive owner-only, no-follow, single-link journals
with exact bounded bytes and file/directory fsync before lifecycle append. Each
phase has its own binding name so a refused phase cannot poison a valid phase.
Partially appended matching terminal facts replay with stable event IDs. Existing
terminal state requires its original journal; corrupt/substituted/missing state
is refused without repair. The publication lock is shared with start/output.

`unknown/running` passively acknowledges the original start, without a new fact.
Other unknown observations append/replay `attempt.unknown`. They cannot downgrade
a terminal Run or permit another launch. The receipt binds full report digest,
lease, disposition and last persisted event/sequence; `launchAllowed` is false.

## Wire bounds

Pinned HTTPS, literal route, exactly one session/grant and content length/type,
no content/transfer encodings, 16 KiB requests and a 10-second socket bound apply.
The client reads at most 4097 bytes and checks the exact lease, binding digest,
event and disposition. Up to three retries replay only the identical body on
interrupted transport. Refusal or malformed acknowledgement never polls or starts
work. Registered schemas: `native-outcome-request`, `native-outcome-receipt`.
Examples: `examples/native-remote-outcome/`.

## Execution and evidence scope

The programmatic Worker executor is documented in
[the guide](../guides/native-remote-execution.md). It uses the existing reviewed
Python native profile and independent private CAS/state. It is not a sandbox or
Ray project-task driver. Required unsupported isolation/checkpoint restore is
refused. Real local TLS/controller fixtures are not GPU or two-host evidence.
The designated Linux gate requires an actual child, real CPU result and observed
process-group stop; Checkpoint B acceptance still requires the selected hosts.
