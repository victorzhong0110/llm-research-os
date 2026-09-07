# Worker protocol v0alpha1

> Status: Experimental semantic contract (ADR-0009, ADR-0043)  
> First transport: worker-initiated JSON long poll on loopback HTTP  
> Domain version: `v0alpha1`

The Worker protocol is independent of byte transport. M2-0 binds it to
loopback HTTP in-process (ADR-0043). Isolated control-plane and Worker
processes use loopback HTTPS/JSON with a pinned CA (ADR-0044). That
loopback TLS path is not a cross-machine proof. Non-loopback HTTPS remains
ADR-0021.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative.

## 1. Facts

Sparse EventStore types (payloads MUST NOT contain HMAC tokens, script
bodies, logs, or metrics):

| Type | Actor kind | Meaning |
|---|---|---|
| `worker.registered` | human | Worker identity and advertised runtime/accelerators |
| `work.queued` | system | Execution object waiting for a lease (`imageDigest`, nested `config`/`inputs`, `configDigest`) |
| `work.leased` | system | Attempt leased to one Worker until `expiresAt` |
| `work.claimed` | system | Worker accepted the lease (idempotent) |
| `work.completed` | system | Result and artifact digests |
| `work.failed` | system | Brick-level failure, not unknown |
| `work.lease.expired` | system | Observed expiry; complete is forbidden |
| `authorization.grant.recorded` | human | HMAC grant identity plus authorization citation and execution binding (see grant protocol) |
| `authorization.grant.revoked` | human | Grant can no longer start work or record a new result |
| `authorization.grant.consumed` | system | Nonce spent on a lease |

Heartbeats MUST NOT be facts. Logs and metrics belong in artifacts; events
MAY cite their digests. High-frequency series MUST use CAS `MetricChunk`
objects ([metric chunk v0alpha1](metric-chunk-v0alpha1.md)); they MUST NOT
append one EventStore fact per sample. `researchos m2 bench` measures 10k
and 100k EventStore timings and is not an SLA (ADR-0047).

## 2. Lease rules

- Idempotent claim: the same `(taskId, attemptId, workerId)` returns the
  same `leaseId` while the lease is active. The second poll MUST set
  `resumed=true`. Resume MUST NOT spawn the brick again. Claim-interface
  idempotency is not execution idempotency.
- A different Worker MUST NOT claim an active lease.
- After `expiresAt`, complete MUST fail closed (`lease-expired`).
- Required accelerators MUST be a subset of the Worker's advertisement.
- Poll MUST re-check the execution object against the grant. A swapped
  brick, config, inputs, or runtime MUST fail `execution-binding-mismatch`
  and MUST NOT start a process.
- Complete and fail MUST bind the token to the recorded grant and lease:
  `projectId`, `workerId`, `grantId`, `taskId`, `runId`, `attemptId`,
  `nonce`, `imageDigest`, `configDigest`, and expiry. A token for another
  task MUST fail `grant-task-mismatch`.
- After revoke or token/grant expiry: a matching terminal complete/fail
  remains idempotent; a new result MUST be refused (`grant-revoked` /
  `grant-expired`).
- Recovery MUST NOT re-run a claimed attempt whose result is unknown, and
  MUST NOT mark success without a matching completed fact. Same-attempt
  resume after unknown is `attempt.recovered`. An inspectable CPU
  checkpoint in CAS may complete that recovered attempt; continuing from
  the checkpoint is a new execution object.

## 3. Loopback binding

- Listen address MUST be a loopback IP. `0.0.0.0` / public binds fail closed.
- Worker authenticates with `Authorization: Bearer` session (`ws1` HMAC).
- Poll: `POST /v0alpha1/work/poll` with `grantToken`. `204` means no work.
  `200` includes `imageDigest`, `configDigest`, `config`, `inputs`,
  `runtime`, and `resumed`.
- Heartbeats: `POST /v0alpha1/work/heartbeat`. Transport liveness only;
  MUST NOT append EventStore facts. A `200` JSON response includes
  `cancelRequested` (a recorded request, not an observed stop).
- Poll `200` includes `cancelRequested`. After a cancel request, poll MUST
  NOT open a new lease. An already-claimed lease is returned with
  `resumed=true` and MUST NOT spawn. The Worker MAY stop a recorded
  execution identity; it MUST NOT report `cancel-observed` until that
  process or container has been reaped or inspect-confirmed. Missing
  identity stays `execution-unobserved`. `attempt.cancelled` /
  `run.cancelled` are recorded from that observation. A finished brick
  MAY still `work.completed`.
- Complete of an uploaded artifact that never recorded `work.completed`
  is retried. Reconcile drives Run/Attempt from the lease: completed
  work succeeds the Attempt; unknown without a completed fact stays
  unknown; a CAS object alone is not success.
- Complete: `POST /v0alpha1/work/complete`. Fail: `POST /v0alpha1/work/fail`.
- Artifact upload: `POST /v0alpha1/artifacts`; response is digest only.
- Artifact download: `GET /v0alpha1/artifacts/sha256/<64 lowercase hex>`
  with `X-ResearchOS-Grant`. For `python-sandbox` work the digest MUST
  equal the grant `imageDigest`. For `oci-container` work the digest MUST
  equal `inputs.brickDigest`. The Worker MUST hash the bytes and refuse a
  mismatch.
- Isolated processes (ADR-0044) MUST use HTTPS with a pinned loopback CA,
  a private Worker CAS, and MUST NOT open the control-plane SQLite file.
  In-process HTTP is a test adapter. Loopback tests MUST NOT be described
  as cross-machine verification.

## 4. CPU helper (not a kernel sandbox)

The image field is `imageDigest` (`sha256:` + 64 hex) and
`imageMediaType: researchos.python-brick/v0alpha1` or
`researchos.oci-image/v0alpha1`. M2-0 materializes a python-brick object
into a temp dir and runs host Python JSON-stdio (`-I`, allowlisted
env, wall-clock). Stdout and stderr byte limits apply **while pipes are
read**, not after exit. POSIX process groups are killed and reaped. A
wall-clock timeout or a process killed with a signal (`returncode < 0`) is
`UNKNOWN`, not `failed`. A non-zero brick exit is `failed`. This is not
`NativeProcessRuntime`, not runc, and not kernel network or filesystem
isolation (TM-043). It MUST NOT be described as a general-purpose sandbox
for arbitrary code.

## 4a. CPU OCI runtime

`runtime: oci-container` with `imageMediaType: researchos.oci-image/v0alpha1`
is `OCIContainerRuntime` (ADR-0045). `imageDigest` is the OCI image
identity. Tags and pull-by-name are forbidden. The CAS python brick is
`inputs.brickDigest`. Network MUST be `denied`. Allowed mounts are `/in`
(read-only brick), `/tmp`, and `/out`. The container user is UID/GID
65534. Launch uses `--cidfile` and MUST NOT use `--rm` so stop can
`inspect` then `rm` (ADR-0050). The host bind root for `/in` is mode 0755 with brick file 0444 so
nobody can traverse it; it MUST NOT be 0700, 0777, or run as root
(ADR-0049). Secrets inject only as `SecretRef`
env slots. The first adapter is docker with `--pull=never`. A docker CLI
without an engine MUST fail `oci-runtime-missing`. Tests MUST NOT mock a
successful container. Ordinary pytest MAY skip `oci_live` when no engine
is present. Designated Linux OCI CI (`RESEARCHOS_OCI_REQUIRED=1`) MUST
fail if the engine, image build, or live brick is missing. Host Python
remains the trusted helper path.
A Worker registered as `python-sandbox` MUST NOT lease OCI work.

## 4b. Stop, fault, and recovery

Cancel request is not observed stop (ADR-0046, ADR-0050). After
`*.cancel.requested`, poll MUST NOT open a new lease. A resumed claim
MUST NOT spawn. Observed stop is `work.failed` with `cancel-observed`
only after the recorded executor is confirmed gone, then
`attempt.cancelled` / `run.cancelled`. A finished brick MAY still
`work.completed`; that fact wins over a retained request. Heartbeats
MUST NOT append facts; they MUST be polled during execute so a cancel
request can be observed. A Worker records a 0600 execution identity
(pid/pgid plus Linux starttime, or OCI container id from `--cidfile`).
`docker run` MUST NOT use `--rm` before inspect. PID reuse MUST NOT
stop another task. After a successful brick and artifact upload, the
Worker writes a pending complete receipt. Disconnect before
`work.completed` retries that complete and MUST NOT re-execute. Unknown or lost work, including
`execution-unobserved`, MUST NOT be marked success or auto-rerun.
A second Worker client MUST NOT spawn while the original executor is
still running. Timeout/kill stay unknown; the Worker drops a reaped
identity so a later cancel cannot rewrite unknown as cancelled.
Live CPU fault cases (ADR-0051) MUST assert process or container state;
calling `work.failed` without that observation is not a stop.
Container stop is not cloud-instance stop. Same-attempt resume after
unknown is `attempt.recovered`. An inspectable CPU checkpoint in CAS may
complete that recovered attempt; continuing from the checkpoint is a new
execution object.

## 5. Conformance

```bash
uv run pytest tests/test_worker_protocol.py tests/test_worker_faults.py \
  tests/test_worker_isolate.py tests/test_worker_oci.py \
  tests/test_worker_recovery.py tests/test_worker_supervise.py \
  tests/test_worker_live_faults.py
uv run researchos m2 prove examples/m2-checkpoint /tmp/m2.db --format json
uv run researchos m2 oci examples/m2-oci-checkpoint /tmp/m2-oci.db --format json
```

The OCI command fails closed (`oci-runtime-missing` or `oci-image-missing`)
when this host has no live engine or the planned digest is not present.
That failure is not a mocked success.
