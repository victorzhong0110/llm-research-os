# M0 Plan Authorization Evaluation Events

This slice adds one append-only audit path without changing the authority of the existing pure
authorization evaluator.

## What is recorded

`researchos authorizations record` rebuilds the exact plan, recomputes the separate
`PlanAuthorizationRequest`, checks a four-digest event binding and appends one
`plan.authorization.evaluated` ResearchEvent to an existing SQLite store.

The payload preserves:

- project revision and workflow identity;
- spec, registry, plan and decision digests;
- `authorized`, `pending` or `denied` status;
- required and missing capabilities and permissions;
- approved, pending and denied requirements;
- caller-asserted actor, event identity, time and evidence references.

## Create an empty store for the example

The record command deliberately refuses to create a database. An application or an existing Run
flow must initialize the EventStore first. For a local example, the deterministic simulated CLI can
create one, or Python can explicitly construct `EventStore`.

After a store exists:

```bash
uv run researchos authorizations record \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  examples/plan-authorization-events/valid/minimal.json \
  research.db --format json

uv run researchos events replay research.db
```

Successful JSON is the stored ResearchEvent, not a new projection or receipt format. Exit `0`
means an `authorized` evaluation was recorded. Exit `1` means a valid negative or unresolved
evaluation was recorded. Exit `2` means nothing requested was committed.

## Integrity and concurrency

Before append, the recorder verifies the complete store and treats the resulting contiguous event
count as the frozen global head. SQLite append then compare-and-sets that head. A concurrent event
causes a conflict; the command does not retry because a retry would need to rebuild and re-evaluate
the plan and policy against the caller's current intent.

Authorization events are project/revision facts, not Run/Attempt lifecycle facts, so they bypass
RunControl but retain EventStore validation, append-only triggers, global ordering and CAS.

## Authority boundary

The event is durable and independently replayable, but its actor is not authenticated. Its payload
therefore fixes:

- `approvalAuthentication: not-authenticated`;
- `authority: audit-only`;
- `execution: not-executed`.

Linking a Run to an authenticated, expiring and revocable authorization fact remains future
work. A read-only candidate-set reconstruction now exists as
[M0 plan authorization lineage](m0-plan-authorization-lineage.md); it does not add a
RunSnapshot citation or grant runtime consumption.
