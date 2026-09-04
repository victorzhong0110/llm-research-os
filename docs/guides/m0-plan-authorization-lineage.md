# M0 Plan Authorization Lineage Query

This slice reconstructs recorded `plan.authorization.evaluated` facts for one
exact plan identity. It does not change the authority of those facts.

## What is reconstructed

`researchos authorizations find` loads a closed `PlanAuthorizationLineageQuery`,
opens an existing SQLite store read-only, freezes a verified high-water prefix
and folds matching authorization evaluation events.

The required join key is project, revision, workflow and the spec/registry/plan
digest triple. Optional `decisionDigest` narrows the candidate set to one exact
decision. Omitting it returns every recorded evaluation of that plan, including
`pending` and `denied`.

## Reconstruct from an existing store

The find command refuses to create a database. Record an evaluation first, or
use any existing verified store:

```bash
uv run researchos authorizations record \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  examples/plan-authorization-events/valid/minimal.json \
  research.db --format json

uv run researchos authorizations find \
  examples/plan-authorization-lineage/valid/minimal.json \
  research.db --format json
```

Successful JSON is a `PlanAuthorizationLineageReport`. Exit `0` means the prefix
was reconstructed; `matchCount` may be zero. Exit `2` means input or integrity
failed and no report was emitted.

Each match cites `{eventId, sequence}`. Retrieve the full event independently
with `events get` or `events replay`.

## Authority boundary

The report and every match fix:

- `approvalAuthentication: not-authenticated`;
- `authority: audit-only`;
- `execution: not-executed`;
- `runtimeConsumption: not-consumed`;
- `persistence: read-only`.

The projection never selects a latest-authorized fact. SimulatedRuntime records the
in-process `decisionDigest` on `RunSnapshot` and, from M1-6, a local `{eventId, sequence}`
citation. This query still does not write those fields, stays `not-consumed`, and does
not treat a match as the fact the Run used. No NativeProcessRuntime, Worker or paid adapter
may treat a non-empty candidate set as a launch token.

Signatures, expiry and revocation remain future work.
