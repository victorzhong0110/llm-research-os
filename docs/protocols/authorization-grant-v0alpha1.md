# Authorization grant v0alpha1

> Status: Experimental Worker consume credential (Issue #53, ADR-0043)  
> JSON Schema: `schemas/authorization-grant-request/v0alpha1.schema.json`

This is not a JWT and not SimulatedRuntime consume. SimulatedRuntime still
cites local `{eventId, sequence}` of `plan.authorization.evaluated`
(ADR-0042). Worker execution consumes an HMAC grant bound to one worker,
one attempt, and one execution object.

## 1. Recorded fact

`authorization.grant.recorded` payload:

- `grantId`, `workerId`, `taskId`, `nonce`, `expiresAt`, `keyId`
- `authorizationEventId`, `authorizationSequence` — citation of one
  `plan.authorization.evaluated` fact on this EventStore
- `imageDigest` (`sha256:`) and `configDigest` (`jcs-sha256:`) — the
  execution object
- Envelope `runId` / `attemptId` are required

The cited evaluation MUST exist, MUST be `authorized=true`, MUST match the
project, MUST have a human actor, and MUST list `execute.local` in
`requiredCapabilities`. Citing a `simulate` authorization MUST fail
`authorization-capability-mismatch`.

Grant recording MUST rebuild the cited plan from the caller-supplied
ResearchSpec and registry at a shared trust boundary used by
`WorkerPlane.record_grant` and `researchos grants record`. Request, grant,
and queue agreeing with each other is not sufficient. The rebuilt plan
MUST match the cited event's spec/registry/plan/decision digests, project,
revision, and workflow. `taskId` is the **planned** graph node id and MUST
exist in that plan. `runId` and `attemptId` are the **runtime** attempt
identity. The grant `imageDigest` / `configDigest` MUST equal the planned
task's execution object. Script A's authorization MUST NOT issue an
executable grant for script B. Changing config, inputs, runtime, planned
task, or revision MUST fail closed.

The HMAC token MUST NOT be stored on the event (TM-007).

Token form: `rg1.<urlsafe-b64-json>.<hex-hmac-sha256>` over canonical
claims `{v, keyId, grantId, grantEventId, workerId, taskId, attemptId,
runId, nonce, exp, projectId, imageDigest, configDigest}`. Verify with
`hmac.compare_digest`. Unknown `keyId` fails closed.

## 2. Expiry, revoke, consume, results

- `exp` / `expiresAt` in the past → `grant-expired` for poll and for a
  **new** complete/fail
- `authorization.grant.revoked` → later poll and new complete/fail fail
  `grant-revoked`
- A matching terminal complete/fail after revoke or expiry MUST return the
  existing fact (idempotent). A different result MUST fail closed.
- A token whose `taskId` / `runId` / `attemptId` does not match the lease
  MUST fail `grant-task-mismatch`
- `authorization.grant.consumed` binds `nonce` to one `leaseId`. A second
  consume with another lease is `grant-replay`. The same lease is
  idempotent.

CLI: `researchos grants record SPEC REQUEST DATABASE --registry PATH`
rebuilds the plan, then appends the recorded fact. It does not print the
token. Recording without a matching `execute.local` evaluation, or with an
execution object that is not the planned task, fails closed.

## 3. Conformance

```bash
uv run pytest tests/test_worker_protocol.py
uv run researchos schema --contract authorization-grant-request --check \
  schemas/authorization-grant-request/v0alpha1.schema.json
```
