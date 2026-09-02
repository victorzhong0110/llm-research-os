# PlanAuthorizationRequest and PlanAuthorizationReport v0alpha1

## 1. Scope

These two documents expose the deterministic plan-authorization evaluator without turning its
output into an authority credential or executing a plan.

- `PlanAuthorizationRequest` is caller-owned policy input for one exact static plan.
- `PlanAuthorizationReport` is a normalized evaluation result.

Their JSON Schema identifiers are:

- `https://researchos.dev/schemas/plan-authorization-request/v0alpha1.schema.json`
- `https://researchos.dev/schemas/plan-authorization-report/v0alpha1.schema.json`

Both use `apiVersion: researchos.dev/v0alpha1`. Unknown fields, Python field-name spellings,
coercion and whitespace repair are rejected.

## 2. Request contract

A request MUST contain all of the following fields:

| Field | Meaning |
|---|---|
| `specDigest` | Exact canonical ResearchSpec digest |
| `registryDigest` | Exact sealed BlockRegistry digest |
| `planDigest` | Exact semantic execution-plan digest |
| `grantedCapabilities` | Exact capabilities granted for this plan |
| `grantedPermissions` | Exact permissions granted for this plan |
| `requirementDecisions` | Explicit `approved` or `denied` decisions keyed by planner requirement ID |

Every collection is an explicit JSON array. Capability and permission values must be unique.
Requirement IDs must also be unique even when their decision values differ. Semantic digest
fields are produced as `jcs-sha256:<64 lowercase hex>` per
[Semantic Content Digests v0alpha1](digest-v0alpha1.md). Models also accept historical
`sha256:<64 lowercase hex>` on input; a legacy tag MUST fail closed against a recomputed JCS
digest. The request cannot
contain an actor, timestamp, signature or reusable organization-wide grant. It is not a receipt.

The normative minimal request is:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "PlanAuthorizationRequest",
  "specDigest": "jcs-sha256:3aef52d942c807c1661ea3e10e856b74b7b209e7f7a8a92c47cd183fcb045af0",
  "registryDigest": "jcs-sha256:d97eed822c9897500e581f5014bb04e7adb985f7d03aa184d0f0a3ecacec741a",
  "planDigest": "jcs-sha256:a50b5b56f595258c9cd30090f0acc96bdd0987c7c32412008a1dac6eb68ccd1b",
  "grantedCapabilities": [
    "simulate"
  ],
  "grantedPermissions": [],
  "requirementDecisions": []
}
```

An implementation loading a request from a local path MUST apply the same bounded, duplicate-key
and YAML-alias checks as ResearchSpec loading. The M0 reference CLI additionally rejects symbolic
links for both the request and ResearchSpec inputs.

## 3. Evaluation

The implementation reconstructs a sealed registry from the explicitly supplied manifest paths,
validates and freezes the ResearchSpec, compiles a new `DryRunReport`, and then calls
`authorize_plan`. The request digest triple must match that newly compiled report. A request is not
allowed to supply its own plan body or replace planner output.

Evaluation follows ADR-0030:

- missing capability or permission grants produce `denied`;
- an explicit denied requirement produces `denied` and takes precedence over pending decisions;
- an undecided requirement produces `pending` when no denial exists;
- only exact complete grants and requirement approvals produce `authorized`;
- unknown, unused, duplicate or malformed entries fail as invalid input rather than becoming an
  authorization disposition.

## 4. Report contract

The report includes the status, exact three-digest binding, deterministic `decisionDigest`, sorted
required/missing access lists, and sorted approved/pending/denied requirement lists. It also carries
literal boundary declarations:

```json
{
  "approvalAuthentication": "not-authenticated",
  "persistence": "not-persisted",
  "execution": "not-executed",
  "sideEffects": {
    "blocksExecuted": 0,
    "networkRequests": 0,
    "persistentWrites": 0,
    "paidActions": 0
  }
}
```

`authorized` is true if and only if `status` is `authorized`. Report model validation recomputes
`decisionDigest` from the binding and normalized dispositions. It also rejects unsorted, duplicate,
overlapping or status-inconsistent collections. JSON Schema provides the language-neutral
structural contract; these cross-field digest and disposition rules remain normative semantic
validation requirements.

## 5. CLI status

`researchos authorize SPEC REQUEST` returns:

| Exit code | Meaning |
|---:|---|
| `0` | A valid report has status `authorized` |
| `1` | A valid report has status `pending` or `denied` |
| `2` | Input, planning, registry, binding or report validation failed |

Only a valid report is written to stdout. Errors use `ProblemReport` JSON or escaped text on stderr.
The command never executes a block, imports a manifest entrypoint, opens an EventStore, writes an
artifact, contacts a network, performs a paid action or persists the evaluation.

## 6. Deliberate M0 limitations

The request represents caller-asserted input. The report is not authenticated, signed, timestamped,
expiring, revocable, persisted or anchored in the event log. Its `decisionDigest` detects semantic
changes under the JCS `jcs-sha256:` algorithm but does not prove who approved anything. A real process,
remote Worker or paid runtime must not treat this report alone as a durable approval receipt.
