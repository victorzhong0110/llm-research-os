# ADR-0032: Audit-only Plan Authorization Events

- Status: Accepted
- Implemented for review: 2026-09-02
- Record status: M1-6 (ADR-0042) lets SimulatedRuntime cite `{eventId, sequence}` on this local store. The event remains audit-only and is not a launch JWT. Signatures, expiry and revocation stay not-delivered.

## Context

The deterministic plan-authorization gate can say whether one exact plan is `authorized`,
`pending` or `denied`, but its result previously existed only in process memory or CLI output.
That preserves a clean pure-function boundary, yet it leaves no append-only fact that can answer
which exact decision was evaluated, by which caller-asserted actor, and against which project
revision.

Simply writing an `authorized` boolean would be unsafe. The current local CLI cannot authenticate
an approver, sign or expire a decision, and a stored event must not become a launch credential by
accident. Recording also needs the same integrity and concurrency discipline as other facts without
forcing authorization events through the Run/Attempt lifecycle reducer.

## Decision

Add a strict `PlanAuthorizationEventRequest v0alpha1` and a separate
`researchos authorizations record` command.

The command:

1. loads all documents and builds a sealed registry before opening the database;
2. rebuilds the exact dry-run plan and recomputes `authorize_plan`;
3. requires exact project, experiment revision, workflow, spec, registry, plan and decision-digest
   binding in the event request;
4. requires an existing EventStore, verifies its complete integrity, and CAS-appends exactly one
   `plan.authorization.evaluated` fact at the verified global head;
5. records `authorized`, `pending` and `denied` evaluations with their normalized dispositions;
6. gives the event project/revision scope only: `runId`, `attemptId` and `blockId` remain null;
7. fixes the payload claims to `approvalAuthentication=not-authenticated`,
   `authority=audit-only` and `execution=not-executed`.

The existing `researchos authorize` command remains pure and zero-write. A recorded evaluation is
durable audit evidence that the local evaluator produced a decision; it is not proof of approver
identity, a signature, a revocable approval receipt, or permission for a future runtime to launch.
No runtime consumes this event in the current slice.

## Consequences

- `events get`, `events list` and `events replay` can independently expose the exact normalized
  authorization evaluation.
- Every identity and time remains caller-owned; the command mints only store sequence and stream
  version.
- Integrity corruption and a concurrent append fail before the requested fact is committed; CAS
  conflicts are not retried.
- The event type now has a reference domain-payload validator in addition to the generic
  ResearchEvent envelope validator.
- Authenticated actors, signatures, expiry, revocation, runtime consumption and a projection that
  links a Run to one authorization fact remain separate security work.

## References

- [Issue #19](https://github.com/victorzhong0110/llm-research-os/issues/19)
- [PlanAuthorizationEvent protocol](../protocols/plan-authorization-event-v0alpha1.md)
- [M0 Authorization Event guide](../guides/m0-plan-authorization-events.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
- [ADR-0031 Explicit Plan Authorization CLI](0031-explicit-plan-authorization-cli.md)
