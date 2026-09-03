# ADR-0028: Explicit Run Cancellation Request

- Status: Accepted
- Date: 2026-08-31

## Context

The M0 charter requires CLI run and stop behavior. ADR-0027 exposed the
deterministic simulated Run path, while the state protocol already distinguished
a cancellation request from an observed cancelled outcome. A convenience stop
command could otherwise create a missing database, mint event identity, send an
unreviewed host signal, retry a CAS conflict, or report `cancelled` before any
runtime or Worker observed that result.

## Decision

Add `RunCancellationRequest v0alpha1` and one command:

```text
researchos runs cancel REQUEST DATABASE
```

- The request is a closed, strict, alias-only Pydantic authoring model with a
  committed Draft 2020-12 JSON Schema. The caller provides the aggregate,
  target, reason, event identity/time, source, subject, stream, actor and
  evidence references.
- The target is a closed discriminated union. `run` selects only
  `run.cancel.requested`; `attempt` requires an `attemptId` and selects only
  `attempt.cancel.requested`. No arbitrary event type or payload is accepted.
- The database is opened writable only if it already exists and has the exact
  supported EventStore schema. Input errors and missing paths create nothing.
- One invocation builds one isolated ResearchEvent draft and passes it through
  RunControl replay, lifecycle preflight and global-head CAS. It does not retry
  conflict or append a second event.
- JSON output is exactly `RunSnapshot v0alpha1`. Text output says that no
  process signal was sent and no cancellation outcome was observed.
- Exit `0` means the request fact was committed. Invalid input, integrity,
  transition, duplicate and conflict errors return `2` as a ProblemReport.

The command does not implement a runtime stop adapter, POSIX signal, Worker
protocol, `attempt.cancelled`, `run.cancelled`, network, GPU, plugin execution,
model API or paid operation.

## Consequences

- M0 now has a user-facing, auditable stop-request path without weakening the
  state machine's distinction between requested and observed cancellation.
- Run and Attempt cancellation are separate single-fact invocations. This
  avoids a partially committed two-event operation but requires a runtime or
  Worker to translate policy into later outcome facts.
- Repeated requests remain explicit facts. Duplicate IDs and stale global heads
  are errors rather than hidden idempotence or automatic retry.
- `EventStore(require_existing=True)` is the writable-existing counterpart to
  the existing read-only `create=False` mode. It verifies an existing schema
  before enabling writable connection settings.
- Stream granularity and correlation/causation rules remain open; this request
  version does not decide them.
- `actor.id` is audit metadata rather than authenticated authority. M0 relies on
  local OS access controls; a future network control plane needs explicit
  identity and policy enforcement before exposing this mutation.

## Validation

Tests cover model/Schema agreement, target union rules, alias-only strictness,
coercion/null/URI/time rejection, duplicate evidence, request isolation,
unknown-key non-echo, missing and corrupt database preservation, Run and active
Attempt requests, exact RunSnapshot JSON, explicit text caveats, terminal and
binding rejection, duplicate identity, and concurrent same-head conflict.

## References

- [RunCancellationRequest v0alpha1](../protocols/run-cancellation-request-v0alpha1.md)
- [M0 Run Cancellation CLI](../guides/m0-run-cancellation-cli.md)
- [ADR-0024 Run/Attempt State Machine](0024-run-attempt-state-machine.md)
- [ADR-0025 Atomic RunControl Append Boundary](0025-atomic-run-control-append-boundary.md)
- [ADR-0027 Explicit Simulated Run CLI](0027-explicit-simulated-run-cli.md)
