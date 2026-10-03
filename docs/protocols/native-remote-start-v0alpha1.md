# Remote native start recording v0alpha1 (R08 slice)

`POST /v0alpha1/native/start` records the controller side of a future Worker's
pre-import barrier. It does not start a process or verify a remote OS process.
A consumed grant, reviewed preparation, Worker-local durable process identity
and actual barrier handling remain execution requirements. A receipt alone is
not permission to import user code or start another process.

## Binding and state

The closed `NativeStartRequest` carries a lease ID, the existing preparation
receipt and a JCS digest of the Worker's local identity record. It carries no
PID, host path, caller spec, registry, shell command or arbitrary task. The
controller reconstructs the request from existing grant/queue facts, checks its
actual trusted spec/registry through the kernel, and compares every preparation
binding and file citation with controller-scoped material. It checks declared
interpreter identity without requiring the controller to have Worker packages.
The preparation receipt remains `launchAllowed: false` with zero effects.

The lease must be fully claimed, consumed by the same grant, active and owned
by this Worker for the exact task/Run/Attempt. Cancellation, revocation, expiry,
terminal state, a foreign lifecycle prefix, and unknown Attempt all refuse.
The exact existing remote queue/start/Attempt prefix is revalidated. No fresh
claim, Run, retry or replacement identity is created by this endpoint.

Under the existing cross-controller publication lock, an exclusive owner-only
journal binds the complete start document, Worker and grant. Held directory
and no-follow regular single-link file checks, exact bounded bytes and file/
directory fsync precede `attempt.started`. Existing journals must match exactly;
a partially written or substituted journal is never repaired. Missing journal
for an already-running Attempt refuses. A journal prefix left before fact append
can finish the same recording, not change identity or dispatch a new task.
Live authority and Run outcome are checked again after journal I/O and before
returning the receipt.

The receipt binds the full journal digest, lease and persisted event ID/sequence.
It has literal `launchAllowed: false`. `attempt.started` records the controller
start boundary; this is not evidence that user code ran or that a process stopped.
Worker identity digests are authenticated Worker reports, not controller-side
OS observations. A future executor must verify the local identity and fixed
barrier itself, release only the already-created child, and refuse redispatch
when a claim is resumed or local execution intent already exists.

## Wire bounds and recovery

Only pinned HTTPS origins are supported. Require exactly one session/grant,
content type and length header; reject suffixes, query strings and request
content/transfer encodings. The request ceiling is 16 KiB; socket timeout is
10 seconds. The client retries only the same immutable document at most three
times for interrupted transport, checks the receipt's exact binding and reads
at most 4097 bytes. Authorization and malformed acknowledgements are not retried.
A lost response never invokes poll, process launch or a replacement submission.

Schemas are registered as `native-start-request` and `native-start-receipt`.
Examples include valid documents and invalid remote-PID/launch-credential forms.
No existing schema, profile, authorization meaning or accepted evidence changes.

## Evidence boundary

Real local TLS tests cover exact replay, controller restart, partial journal,
lost response, unsafe files, authority drift and conservative unknown handling.
They deliberately prohibit process creation by this endpoint. This is a required
integration boundary, not a completed remote executor, Ray project-task job,
CUDA/Kaggle validation, two-host fault acceptance or Checkpoint B closure.
