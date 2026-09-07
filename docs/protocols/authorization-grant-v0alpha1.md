# Authorization grant v0alpha1

> Status: Experimental Worker consume credential (Issue #53, ADR-0043)  
> JSON Schema: `schemas/authorization-grant-request/v0alpha1.schema.json`

This is not a JWT and not SimulatedRuntime consume. SimulatedRuntime still
cites local `{eventId, sequence}` of `plan.authorization.evaluated`
(ADR-0042). Worker execution consumes an HMAC grant bound to one worker and
one attempt.

## 1. Recorded fact

`authorization.grant.recorded` payload:

- `grantId`, `workerId`, `taskId`, `nonce`, `expiresAt`, `keyId`
- Envelope `runId` / `attemptId` are required

The HMAC token MUST NOT be stored on the event (TM-007).

Token form: `rg1.<urlsafe-b64-json>.<hex-hmac-sha256>` over canonical
claims `{v, keyId, grantId, grantEventId, workerId, taskId, attemptId,
runId, nonce, exp}`. Verify with `hmac.compare_digest`. Unknown `keyId`
fails closed.

## 2. Expiry, revoke, consume

- `exp` / `expiresAt` in the past → `grant-expired`
- `authorization.grant.revoked` → later poll/complete fail `grant-revoked`
- `authorization.grant.consumed` binds `nonce` to one `leaseId`. A second
  consume with another lease is `grant-replay`. The same lease is
  idempotent.

CLI: `researchos grants record REQUEST DATABASE` appends the recorded fact
only. It does not print the token.

## 3. Conformance

```bash
uv run pytest tests/test_worker_protocol.py
uv run researchos schema --contract authorization-grant-request --check \
  schemas/authorization-grant-request/v0alpha1.schema.json
```
