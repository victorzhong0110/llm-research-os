# ADR-0035: Read-only Plan Authorization Lineage Query

- Status: Accepted
- Implemented for review: 2026-09-02

## Context

ADR-0032 made a recomputed plan-authorization decision durable as a
`plan.authorization.evaluated` fact. That fact is independently replayable, but
callers still have no language-neutral way to ask which recorded evaluations
match a given plan identity.

Issue #19 still needs an answer to “which authorization facts exist for this
plan?” A RunSnapshot field, an authenticated credential, or a runtime that
consumes the audit event would be irreversible protocol and security choices.
Those remain blocked. The missing piece that can be added now is a read-only
projection over the existing audit facts.

A current `RunSnapshot` already carries `projectId`, `experimentRevision`,
`workflowId` and `digests.{spec,registry,plan}`. It does not carry
`decisionDigest` or an authorization event citation. The projection must
therefore support that three-digest join without pretending that a listed fact
is “the” authorization a Run used.

## Decision

Add `PlanAuthorizationLineageQuery` / `PlanAuthorizationLineageReport` v0alpha1
and `researchos authorizations find QUERY DATABASE`.

Matching rules:

1. Open an existing EventStore read-only. Do not create a database, append,
   retry, or mint identity.
2. Freeze a verified high-water prefix (`verify_integrity` via paged replay).
3. Fold only `plan.authorization.evaluated` events. Unrelated types are skipped.
4. Domain-invalid authorization events fail closed. Reconstruction does not
   return a partial candidate set.
5. Required join key: `projectId`, `experimentRevision`, `workflowId`,
   `specDigest`, `registryDigest`, `planDigest`. Comparison is exact tagged
   digest identity; `sha256:` and `jcs-sha256:` of the same hex are different.
6. Optional `decisionDigest` further restricts the candidate set to one exact
   decision. Omitting it returns every recorded evaluation of that plan
   identity, including `pending` and `denied`.
7. Matches are listed in global sequence order. The projection never selects a
   single winning fact.

The report is explicitly:

- `approvalAuthentication=not-authenticated`
- `authority=audit-only`
- `execution=not-executed`
- `runtimeConsumption=not-consumed`
- `persistence=read-only`

A match cites `{eventId, sequence}` into the log. That citation shape is
available for a later RunSnapshot field; this slice does not add that field,
does not change the Run/Attempt reducer, and does not let SimulatedRuntime or
any other runtime consume the reconstruction.

## Consequences

- Researchers can reconstruct the candidate authorization facts for a plan
  identity that a current RunSnapshot already names.
- Multiple recordings of the same identity remain visible. Latest-authorized is
  not a credential.
- Authenticated actors, signatures, expiry, revocation, RunSnapshot citation
  and runtime consumption remain separate security work and require their own
  ADR plus threat-model review.

## References

- [Issue #19](https://github.com/victorzhong0110/llm-research-os/issues/19)
- [PlanAuthorizationLineage protocol](../protocols/plan-authorization-lineage-v0alpha1.md)
- [M0 Authorization Lineage guide](../guides/m0-plan-authorization-lineage.md)
- [ADR-0032 Audit-only Plan Authorization Events](0032-audit-only-plan-authorization-events.md)
- [ADR-0024 Pure Run and Attempt state machine](0024-run-attempt-state-machine.md)
