# Worker protocol v0alpha1

> Status: Experimental semantic contract (ADR-0009, ADR-0043)  
> First transport: worker-initiated JSON long poll on loopback HTTP  
> Domain version: `v0alpha1`

The Worker protocol is independent of byte transport. M2-0 binds it to
loopback HTTP. Non-loopback HTTPS remains ADR-0021.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative.

## 1. Facts

Sparse EventStore types (payloads MUST NOT contain HMAC tokens, script
bodies, logs, or metrics):

| Type | Actor kind | Meaning |
|---|---|---|
| `worker.registered` | human | Worker identity and advertised runtime/accelerators |
| `work.queued` | system | CAS image digest waiting for a lease |
| `work.leased` | system | Attempt leased to one Worker until `expiresAt` |
| `work.claimed` | system | Worker accepted the lease (idempotent) |
| `work.completed` | system | Result and artifact digests |
| `work.failed` | system | Brick-level failure, not unknown |
| `work.lease.expired` | system | Observed expiry; complete is forbidden |
| `authorization.grant.recorded` | human | HMAC grant identity (see grant protocol) |
| `authorization.grant.revoked` | human | Grant can no longer be consumed |
| `authorization.grant.consumed` | system | Nonce spent on a lease |

Heartbeats MUST NOT be facts. Logs and metrics belong in artifacts; events
MAY cite their digests.

## 2. Lease rules

- Idempotent claim: the same `(taskId, attemptId, workerId)` returns the
  same `leaseId` while the lease is active.
- A different Worker MUST NOT claim an active lease.
- After `expiresAt`, complete MUST fail closed (`lease-expired`).
- Required accelerators MUST be a subset of the Worker's advertisement.

## 3. Loopback binding

- Listen address MUST be a loopback IP. `0.0.0.0` / public binds fail closed.
- Worker authenticates with `Authorization: Bearer` session (`ws1` HMAC).
- Poll: `POST /v0alpha1/work/poll` with `grantToken`. `204` means no work.
- Heartbeats: `POST /v0alpha1/work/heartbeat`. Transport liveness only;
  MUST NOT append EventStore facts.
- Artifact bytes: `POST /v0alpha1/artifacts`; response is digest only.

## 4. CPU sandbox (OCI direction)

The image field is `imageDigest` (`sha256:` + 64 hex) and
`imageMediaType: researchos.python-brick/v0alpha1`. M2-0 unpacks the object
into an isolated temp dir and runs host Python JSON-stdio
(`-I`, allowlisted env, wall-clock). A wall-clock timeout or a process
killed with a signal (`returncode < 0`) is `UNKNOWN`, not `failed`. A
non-zero brick exit is `failed`. This is not `NativeProcessRuntime` and
not runc. A later OCI runtime MUST keep the same digest field.

## 5. Conformance

```bash
uv run pytest tests/test_worker_protocol.py tests/test_worker_faults.py
uv run researchos m2 prove examples/m2-checkpoint /tmp/m2.db --format json
```
