# ADR-0027: Explicit Simulated Run CLI

- Status: Accepted
- Date: 2026-08-30

## Context

ADR-0026 proved a deterministic Python SimulatedRuntime, but M0 still had no
user-facing Run command. A CLI wrapper could easily weaken that boundary by
minting IDs/timestamps, hiding failed or unknown outcomes behind exit zero,
printing an unversioned result object, retrying a CAS conflict, or treating a
request file as executable configuration.

The external-schema decision in ADR-0013 also means a new structured request
cannot be an undocumented Python-only dictionary. Existing ResearchEvent open
questions, especially stream granularity, must not be decided implicitly by a
convenience command.

## Decision

Add `SimulationRequest v0alpha1` and one command:

```text
researchos runs simulate SPEC REQUEST DATABASE
```

- The request is a closed, alias-only, strict Pydantic authoring model with a
  committed Draft 2020-12 JSON Schema. It contains explicit `runId`, workflow,
  Attempt, source, subject, stream, actor, and a closed map of lifecycle event
  `id` / RFC3339 `time` pairs.
- Unknown fields and event types, Python field names, coercion, trimming,
  explicit null identities, invalid URI/timestamps, and duplicate event IDs
  fail closed. The runtime still decides which identities are required for the
  frozen outcome and resumed prefix.
- The command rejects symbolic links for the ResearchSpec and request, loads
  both before opening SQLite, builds a sealed inert registry, and passes an
  isolated runtime request to SimulatedRuntime. It does not bypass RunControl.
- The named database is created if absent or resumed if supported. Structural
  input/registry failure happens before creation. Semantic runtime rejection
  may leave an initialized but event-empty database; it never leaves a partial
  prefix from an invalid identity set because SimulatedRuntime preflights all
  remaining identities before its first append.
- JSON output is exactly the existing versioned `RunSnapshot`; there is no new
  unmodeled command-result envelope. Text output is terminal escaped and labels
  simulated completion as not a scientific conclusion.
- Exit `0` is reserved for `completed`. `failed`, `unknown`, and `unresolved`
  return `1`. Invalid input, unsupported plans, EventStore integrity errors,
  illegal transitions, duplicates, and CAS conflict return `2` as a
  `ProblemReport` and are never automatically retried.

The command does not add cancellation, retry, NativeProcessRuntime, arbitrary
code, network, GPU, artifacts, metrics, or paid capability.

## Consequences

- A researcher can run and resume the no-GPU M0 vertical loop entirely through
  versioned CLI inputs and outputs, then verify or replay the resulting facts
  with the existing event commands.
- Reproducibility requires preserving the request alongside the ResearchSpec;
  the runtime intentionally has no convenient clock/UUID fallback.
- Outcome-specific path completeness remains a semantic runtime rule because
  the request Schema is independent of the separate ResearchSpec document.
- The command makes local SQLite writes. Validation-only automation should use
  `validate`, `dry-run`, and `schema --check` instead.
- Stop/cancel UX and NativeProcessRuntime require separate slices and threat
  model review.

Implementation follow-up: ADR-0028 adds a strict, single-fact cancellation
request CLI. It does not implement a process/Worker stop adapter or infer a
cancelled outcome. NativeProcessRuntime remains separately gated.

## Validation

Tests cover Schema/model agreement, alias-only strictness, unknown lifecycle
keys, duplicate IDs, URI and RFC3339 rejection, request isolation, symlink and
invalid-input failure before database creation, all three outcomes and exit
codes, exact RunSnapshot JSON, terminal idempotence, absent-identity refusal,
corrupt database handling, secret-value non-echo, and EventStore replay and
integrity after a CLI run.

## References

- [SimulationRequest v0alpha1](../protocols/simulation-request-v0alpha1.md)
- [M0 Simulated Run CLI](../guides/m0-simulated-run-cli.md)
- [ADR-0013 Schema Authority](0013-schema-authority.md)
- [ADR-0025 Atomic RunControl Append Boundary](0025-atomic-run-control-append-boundary.md)
- [ADR-0026 Deterministic SimulatedRuntime](0026-deterministic-simulated-runtime.md)
