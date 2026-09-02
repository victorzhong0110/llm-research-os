# PlanAuthorizationEventRequest v0alpha1

> Status: M0 reference contract
>
> Schema authority:
> `schemas/plan-authorization-event-request/v0alpha1.schema.json`

## Purpose

`PlanAuthorizationEventRequest` supplies the exact binding and caller-owned CloudEvents identity
needed to persist one `plan.authorization.evaluated` fact. The evaluator still recomputes the
decision from the ResearchSpec, sealed registry and separate `PlanAuthorizationRequest`.

The resulting event is durable audit data. It is not an authenticated approval, signature,
revocable receipt, lease or runtime launch token.

## Preconditions

The reference recorder fails closed unless:

1. the rebuilt `DryRunReport` is `ready` and `authorize_plan` produces a valid decision;
2. `projectId`, `experimentRevision` and `workflowId` exactly match that report;
3. the request's spec, registry, plan and decision digests exactly match the recomputed result;
4. the local EventStore already exists and its full schema, canonical JSON, indexes, ordering and
   event digests verify;
5. the requested event can be appended at the verified global head without a CAS conflict.

Malformed, stale, broadened, duplicate, corrupt or concurrent input is an error. The command never
repairs a store, retries a conflict, changes the decision, or mints caller-owned identity.

## Request document

The request is alias-only, closed to unknown properties and strict about JSON types. Semantic
digests use `jcs-sha256:<64 lowercase hex>` from current producers; protocol models also accept
historical `sha256:<64 lowercase hex>` on input and MUST fail closed if that legacy tag is
compared with a recomputed JCS digest. `evidenceRefs` is an explicit duplicate-free JSON
array.

Normative example:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "PlanAuthorizationEventRequest",
  "projectId": "example-minimal",
  "experimentRevision": 1,
  "workflowId": "workflow.simulation",
  "binding": {
    "specDigest": "jcs-sha256:3aef52d942c807c1661ea3e10e856b74b7b209e7f7a8a92c47cd183fcb045af0",
    "registryDigest": "jcs-sha256:d97eed822c9897500e581f5014bb04e7adb985f7d03aa184d0f0a3ecacec741a",
    "planDigest": "jcs-sha256:a50b5b56f595258c9cd30090f0acc96bdd0987c7c32412008a1dac6eb68ccd1b",
    "decisionDigest": "jcs-sha256:4d298b128a047cfb6d2498126d1821fca254ed1d482a71f9a538f858c4b8f82c"
  },
  "source": "https://researchos.dev/projects/example-minimal",
  "subject": "authorization.example-minimal.revision-1",
  "streamid": "authorization.example-minimal",
  "actor": {
    "id": "researcher.alice"
  },
  "event": {
    "id": "evt.authorization.example-minimal.1",
    "time": "2026-09-02T05:00:00Z"
  },
  "evidenceRefs": []
}
```

`actor.id` is claimed audit metadata. Local operating-system access to the request and database is
the current authority boundary; the value is not authenticated.

## Stored event

The store assigns `sequence`, `sequencetype` and `streamversion`. The command fixes:

- `type=plan.authorization.evaluated`;
- the ResearchEvent v0alpha1 data Schema and JSON content type;
- project/revision scope with null `runId`, `attemptId` and `blockId`;
- a normalized payload containing workflow ID, four-digest binding, status, the authorization
  boolean and every capability, permission and requirement disposition;
- `approvalAuthentication=not-authenticated`, `authority=audit-only` and
  `execution=not-executed`.

`authorized` only mirrors the deterministic status inside the audit fact. The literal
`authority=audit-only` prevents this protocol from claiming that persistence upgraded the caller's
identity or granted a runtime capability.

Both positive and negative evaluations are facts. `pending` and `denied` are recorded rather than
silently discarded when their requests are otherwise valid.

## CLI behavior

```bash
researchos authorizations record \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  examples/plan-authorization-events/valid/minimal.json \
  research.db --format json
```

| Exit | Meaning |
|---:|---|
| `0` | An `authorized` evaluation fact was committed |
| `1` | A valid `pending` or `denied` evaluation fact was committed |
| `2` | Input, binding, planning, integrity, identity or CAS failed; no requested fact was committed |

JSON success output is the exact stored ResearchEvent and validates against the existing
ResearchEvent Schema. It can be retrieved independently with `events get` or `events replay`.

## Explicit non-goals

This protocol does not authenticate an actor, sign, expire or revoke a decision, create a missing
database, persist a Run projection, link a Run to the event, import a block entrypoint, execute a
runtime, send a signal, access a network, upload an artifact, retry a conflict or reach a scientific
conclusion. A future executable runtime must add and review an authenticated authorization
consumption rule; mere event existence is insufficient.
