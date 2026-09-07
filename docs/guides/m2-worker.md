# M2-0 Worker CLI

Loopback Worker registration, HMAC grants, and the CPU prove path.
Protocol: [Worker v0alpha1](../protocols/worker-v0alpha1.md),
[Authorization grant v0alpha1](../protocols/authorization-grant-v0alpha1.md).
Constraint record: [ADR-0043](../adr/0043-m2-loopback-worker-and-hmac-grants.md),
[ADR-0044](../adr/0044-isolated-control-plane-and-loopback-https.md).

This path does **not** close Issue #38, does not spend GPU, and does not
start NativeProcessRuntime.

## Register and grant

The database must already exist. Worker registration is a human fact.
Grant recording rebuilds the cited `execute.local` plan from spec and
registry, then binds the CAS execution object. `taskId` is the planned
graph node; `runId` / `attemptId` are the runtime attempt. It does not
print the HMAC token. Recording without that plan binding fails closed.

```bash
uv run researchos workers register \
  examples/m2-checkpoint/worker.json \
  research.db --format json
uv run researchos grants record \
  examples/m2-checkpoint/spec.yaml \
  examples/m2-checkpoint/grant.json \
  research.db \
  --registry examples/m2-checkpoint/block.json \
  --format json
```

## One-command CPU loop

```bash
uv run researchos m2 prove \
  examples/m2-checkpoint \
  research.db \
  --format json
```

The command creates an empty EventStore, consumes local plan authorization
for `execute.local`, registers the corpus Worker, records a grant bound to
the planned brick digest, queues a Run, serves loopback long poll, executes
the CAS-pinned `brick.py` only after re-checking that object, stores the
report object, appends `work.completed`, then `attempt.succeeded` /
`run.completed`. It reopens the store and requires the same events and
Markdown report.

Host Python is not kernel isolation. Byte limits apply while reading
stdout/stderr. A claimed lease that is resumed MUST NOT run again.

## Performance baseline

`researchos m2 bench` measures 10k or 100k EventStore append/replay/claim
/report. It is not GPU and not an SLA. See
[M2 performance baseline](m2-perf.md).
Cancel request is not observed stop
([ADR-0046](../adr/0046-worker-stop-fault-recovery.md)). `runs cancel`
records `*.cancel.requested` only. Poll does not open a new lease after
that request. A resumed claim returns `cancelRequested` and MUST NOT
spawn; the Worker fails the lease with `cancel-observed` only after the
recorded process or container is confirmed gone
([ADR-0050](../adr/0050-observed-execution-identity.md)). A resumed cancel
without that identity is `execution-unobserved`, not cancelled. Heartbeat
stays off the log and returns
`{"cancelRequested": true|false}` and is polled during execute. `work.completed` reconciles the Run
and Attempt; a CAS object without that fact is not success. Unknown work
stays unknown. An inspectable CPU checkpoint lives in
`examples/m2-checkpoint-resume/`.

CPU OCI execution is a separate path: [M2 CPU OCI](m2-oci.md),
[ADR-0045](../adr/0045-cpu-oci-container-runtime.md). `researchos m2 oci`
fails closed without a live digest-pinned image.

`--artifacts` selects the CAS root (created if missing). Default is
`<database-stem>-artifacts` beside the database.

Exit `0` is a recorded CPU loop, not scientific success and not GPU
completion. JSON stdout is `M2CheckpointReceipt` (ids and digests only).

## Isolated control plane and Worker

[ADR-0044](../adr/0044-isolated-control-plane-and-loopback-https.md) splits
the control plane and Worker into two processes, two working directories,
and two CAS roots. The Worker talks loopback HTTPS/JSON with a pinned CA.
This is **not** a cross-machine proof. `openssl` is required to mint the
loopback certificate.

```bash
uv run researchos workers serve research.db \
  --artifacts control-artifacts \
  --state control-state \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal
uv run researchos workers run worker/credential.json \
  --artifacts worker-artifacts
```

`workers serve` prints one JSON receipt (`url`, `tlsFingerprint`). Copy the
CA into the Worker directory and write a 0600 `WorkerCredential`. The Worker
MUST NOT receive the control-plane database path. Tokens MUST NOT appear in
logs. Reconnect retries transport disconnects; a resumed lease still MUST
NOT run again.
