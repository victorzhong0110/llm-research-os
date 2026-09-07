# ADR-0043: M2-0 loopback Worker protocol and HMAC grants

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0008, ADR-0009, ADR-0021, or ADR-0042. It
records the M2-0 constraint set for a free CPU Worker loop. It is not M1
checkpoint closure, not a paid GPU run, and not NativeProcessRuntime.

## Context

Charter §8.4 and ADR-0009 keep Worker meaning independent of transport.
Chapter 18 5-WA chose worker-initiated HTTPS/JSON long polling as the first
binding experiment (ADR-0021 deferred). M1 local consume is `{eventId,
sequence}` on this EventStore and is not a launch JWT (ADR-0042). Issue #53
asked for signatures, expiry, and revocation before remote consume.

A first remote slice that required Docker, runc, CUDA, or a cloud GPU would
block verification of identity, lease, idempotency, revocation, and unknown
recovery. Heartbeats written as EventStore facts would make fold cost
Θ(N²) (ADR-0041).

## Decision

M2-0 implements one semantic Worker plane plus a **loopback-only** HTTP
long-poll binding.

1. **Identity.** `worker.registered` is a human fact. The Worker is not a
   local human actor upgraded into a credential.
2. **Grant.** `authorization.grant.recorded` stores grant identity, worker,
   task/attempt, nonce, expiry, `keyId`, a citation of one authorized
   `plan.authorization.evaluated` fact (`authorizationEventId` /
   `authorizationSequence`), and the execution object (`imageDigest` +
   `configDigest`). The cited evaluation MUST be `authorized=true` on this
   store, MUST match the project, and MUST include `execute.local` in
   `requiredCapabilities`. A `simulate` authorization MUST NOT record an
   execution grant. The HMAC token is issued in process and MUST NOT appear
   on events (TM-007). Claims also bind `projectId`, `imageDigest`, and
   `configDigest`. The token is `rg1` HMAC, not JWT.
   `authorization.grant.revoked` and `authorization.grant.consumed` (nonce)
   fail closed on replay. SimulatedRuntime still uses local `{eventId,
   sequence}` consume.
3. **Lease.** `work.queued` / `work.leased` / `work.claimed` /
   `work.completed` / `work.failed` / `work.lease.expired`. Queued work
   carries the same execution object as the grant. Claim of the same
   `(taskId, attemptId, workerId)` is idempotent and returns `resumed=true`
   after the first claim; resume MUST NOT spawn again. A foreign Worker
   cannot take an active lease. An expired lease cannot complete. A token
   bound to another task/run/attempt MUST NOT complete or fail this lease
   (`grant-task-mismatch`). After revoke or expiry, a matching terminal
   complete/fail remains idempotent; a new result is refused.
4. **Unknown vs failed.** A sandbox wall-clock timeout or lost process is
   `attempt.unknown` / sandbox `UNKNOWN`, not `failed`. A brick that exits
   non-zero is `failed`. Cancel requested is not observed stopped.
5. **Heartbeats.** Transport liveness only. They MUST NOT append EventStore
   facts (ADR-0041).
6. **Runtime.** The CPU path is a host-python JSON-stdio helper over a
   CAS-pinned brick (`researchos.python-brick/v0alpha1`). The plan task
   config IS the execution object (image digest, media type, runtime, nested
   config, inputs). `configDigest` is the JCS digest of that object. Image
   identity is a `sha256:` digest so a later OCI runtime can consume the
   same field. Replacing the brick, config, inputs, or runtime invalidates
   the old grant; poll MUST refuse and MUST NOT start a process. The helper
   applies stdout/stderr byte limits while reading pipes and reaps a POSIX
   process group. It is **not** kernel network or filesystem isolation, not
   a general-purpose code sandbox, not `NativeProcessRuntime`, and not
   `OCIContainerRuntime`. NativeProcessPreflight remains `launchAllowed=false`.
7. **Bind.** The HTTP adapter listens on loopback IPs only. Non-loopback
   binds fail closed. Worker sessions are HMAC `ws1` tokens. HTTPS and
   non-loopback transport remain ADR-0021.
8. **Accelerators.** Workers advertise `accelerators`. Work may require
   `cuda`. Missing advertisement refuses the lease. No paid GPU is spent.

### Explicitly not delivered

- Paid cloud GPU, billing adapters, or spending the ¥1000 envelope
- Docker / runc / ms-swift as a prerequisite of the CPU loop
- Non-loopback Worker transport (ADR-0021)
- JWT launch credentials
- NativeProcessRuntime (preflight stays non-launching)
- Charter v0.2, tag `v0.1.0-m1`, Issue #38 closure
- Editable canvas, plugin marketplace, Issue #26 self-evolution

## Consequences

- `researchos m2 prove` can record one loopback CPU loop and a static report
  that cites Worker, attempt, and artifact digest. The corpus plan is a
  single `researchos.python-brick` task authorized for `execute.local`.
- Control-plane restart with the same HMAC key can resume an unexpired
  lease from the log without re-running unknown work. Heartbeats are forgotten.
- SQLite schema stays v2. Lease state is a fold, not a new table.
- Host Python is a trusted local helper. It does not claim arbitrary-code
  isolation (TM-043).

## Validation

1. Protocol tests: HMAC mismatch, revoke, idempotent claim/complete, expired
   complete, accelerator refusal, loopback bind, heartbeat sequence
   unchanged, sandbox timeout or killed process → unknown, disconnect
   before complete leaves the lease open, disk-full complete refused,
   `simulate` authorization cannot record an execution grant, swapped brick
   cannot spawn, cross-task token cannot complete/fail, matching
   complete/fail after revoke remains idempotent, stdout cut during read,
   child process group reaped.
2. `researchos m2 prove examples/m2-checkpoint …` records `work.completed`
   and `run.completed`.
3. `researchos schema --check-all`, ruff, mypy, pytest, coverage ≥ 85%.
4. Issue #38 stays open. No `v0.1.0-m1` tag.

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0009](0009-worker-semantics-independent-of-transport.md)
- [ADR-0041](0041-verified-high-water-cache-and-query-tables.md)
- [ADR-0042](0042-m1-local-authorization-consume-and-closure.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Authorization grant v0alpha1](../protocols/authorization-grant-v0alpha1.md)
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
