# PlanAuthorizationLineageQuery and PlanAuthorizationLineageReport v0alpha1

> Status: M0 reference contract
>
> Schema authority:
> `schemas/plan-authorization-lineage-query/v0alpha1.schema.json`
> `schemas/plan-authorization-lineage-report/v0alpha1.schema.json`

## Purpose

These documents reconstruct which recorded `plan.authorization.evaluated` facts
match one exact plan identity.

The reconstruction is read-only audit data. It is not an authenticated approval,
signature, revocable receipt, lease, Run citation or runtime launch token. It
does not choose a single fact as the authorization a Run used.

## Query document

The query is alias-only, closed to unknown properties and strict about JSON
types. Semantic digests use `jcs-sha256:<64 lowercase hex>` from current
producers; protocol models also accept historical `sha256:<64 lowercase hex>`
on input and MUST fail closed if that legacy tag is compared with a stored JCS
digest.

Required join key:

| Field | Meaning |
|---|---|
| `projectId` | Exact project identity of the recorded fact |
| `experimentRevision` | Exact revision of the recorded fact |
| `workflowId` | Exact workflow identity in the recorded payload |
| `binding.specDigest` | Exact ResearchSpec digest |
| `binding.registryDigest` | Exact sealed registry digest |
| `binding.planDigest` | Exact semantic plan digest |

`binding.decisionDigest` is optional. Omit it to return every recorded
evaluation of that plan identity. Supply it to restrict the candidate set to
one exact decision. JSON `null` is invalid; the field must be omitted or a
tagged digest.

Normative four-digest query:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "PlanAuthorizationLineageQuery",
  "projectId": "example-minimal",
  "experimentRevision": 1,
  "workflowId": "workflow.simulation",
  "binding": {
    "specDigest": "jcs-sha256:3aef52d942c807c1661ea3e10e856b74b7b209e7f7a8a92c47cd183fcb045af0",
    "registryDigest": "jcs-sha256:d97eed822c9897500e581f5014bb04e7adb985f7d03aa184d0f0a3ecacec741a",
    "planDigest": "jcs-sha256:a50b5b56f595258c9cd30090f0acc96bdd0987c7c32412008a1dac6eb68ccd1b",
    "decisionDigest": "jcs-sha256:4d298b128a047cfb6d2498126d1821fca254ed1d482a71f9a538f858c4b8f82c"
  }
}
```

Normative plan-identity query:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "PlanAuthorizationLineageQuery",
  "projectId": "example-minimal",
  "experimentRevision": 1,
  "workflowId": "workflow.simulation",
  "binding": {
    "specDigest": "jcs-sha256:3aef52d942c807c1661ea3e10e856b74b7b209e7f7a8a92c47cd183fcb045af0",
    "registryDigest": "jcs-sha256:d97eed822c9897500e581f5014bb04e7adb985f7d03aa184d0f0a3ecacec741a",
    "planDigest": "jcs-sha256:a50b5b56f595258c9cd30090f0acc96bdd0987c7c32412008a1dac6eb68ccd1b"
  }
}
```

A current `RunSnapshot` already names the required join key. It does not name a
`decisionDigest` or authorization event. Using the plan-identity query against
that snapshot therefore returns a candidate set, not proof that the Run used
one of those facts.

## Reconstruction

The reference command fails closed unless:

1. the query document is valid;
2. the local EventStore already exists and its full schema, canonical JSON,
   indexes, ordering and event digests verify;
3. every `plan.authorization.evaluated` event in the frozen prefix has a valid
   domain payload.

Unrelated event types are skipped. A domain-invalid authorization event is an
error, even when it would not have matched. The command never repairs a store,
appends a fact, retries, or mints caller-owned identity.

Matches are exact field equality, including the digest algorithm tag. Results
are ordered by global sequence. `authorized`, `pending` and `denied` facts are
all candidates when they match the query.

## Report document

JSON success output is `PlanAuthorizationLineageReport v0alpha1`. It echoes the
query, the frozen `highWaterSequence`, `matchCount`, and one match object per
located fact:

- `eventId` and `sequence` form a stable citation into the event log;
- `status` / `authorized` mirror the recorded evaluation;
- `binding` carries the four stored digests;
- each match repeats `approvalAuthentication=not-authenticated`,
  `authority=audit-only` and `execution=not-executed`.

The report itself fixes:

- `approvalAuthentication=not-authenticated`;
- `authority=audit-only`;
- `execution=not-executed`;
- `runtimeConsumption=not-consumed`;
- `persistence=read-only`;
- all four side-effect counters are zero.

`matchCount` MUST equal `matches.length`. Sequences and event IDs MUST be unique
and ordered by sequence. A report MUST NOT claim that a Run used a listed fact.

## CLI behavior

```bash
researchos authorizations find \
  examples/plan-authorization-lineage/valid/minimal.json \
  research.db --format json
```

| Exit | Meaning |
|---:|---|
| `0` | The store prefix was reconstructed; `matchCount` may be zero |
| `2` | Input, integrity or domain validation failed; no report was emitted |

Zero matches is a successful reconstruction of an empty candidate set, not an
authorization denial.

## Explicit non-goals

This protocol does not authenticate an actor, sign, expire or revoke a
decision, create a missing database, persist a Run projection, add fields to
`RunSnapshot`, select a latest-authorized fact, import a block entrypoint,
execute a runtime, send a signal, access a network, upload an artifact or
reach a scientific conclusion. A future executable runtime must add and review
an authenticated authorization consumption rule; a non-empty candidate set is
insufficient.
