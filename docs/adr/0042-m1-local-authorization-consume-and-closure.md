# ADR-0042: M1 local authorization consume and numbered-slice closure

- Status: Accepted
- Date: 2026-09-04

This record does not reopen ADR-0032, ADR-0035, or ADR-0036. It closes the
ADR-0038 E4 numbered M1 slices (M1-0 through M1-6) and the Issue #19 remainder
that M0 left as in-process `decisionDigest` only. Umbrella Issue #38 stays open
while the question channel (Issue #42) and charter v0.2 consolidation remain
not-delivered. The first tag `v0.1.0-m1` is not cut by this record.

## Context

Issue #19 asked for a durable authorization fact, a Run citation of that fact,
and a runtime that consumes the citation before writing lifecycle events. M0
delivered the audit-only recorder (ADR-0032), a read-only lineage query that
does not choose a fact (ADR-0035), and an in-process `decisionDigest` on
`RunSnapshot` (ADR-0036). ADR-0037 recorded those as non-credentials and left
`{eventId, sequence}` consume for M1.

ADR-0038 E4 named M1-6 as that remainder plus an M1 closure ADR with an
explicit not-delivered list. Treating the stored event as a signed launch JWT,
or treating lineage `not-consumed` as the citation, would erase those
boundaries.

## Decision

SimulatedRuntime consumes one local `plan.authorization.evaluated` fact by
`{eventId, sequence}` before any Run/Attempt append.

Local authentication for this slice is not a cryptographic signature. It is:

1. This EventStore assigned the sequence.
2. The cited `{eventId, sequence}` matches the stored row (swap fails closed).
3. The stored actor `kind` is `human`.
4. The four-digest binding matches the in-process `authorize_plan` result for
   this frozen spec, sealed registry, project revision, and workflow.
5. Payload literals stay `not-authenticated` / `audit-only` / `not-executed`.
   The event is still not a launch JWT.

`SimulationRequest` requires a sibling `authorization: {eventId, sequence}`.
`events` `maxProperties` stays 13. SimulatedRuntime writes
`authorizationEventId` / `authorizationSequence` on `run.queued` (both present
or both omitted on ungated traces; JSON `null` is invalid). The reducer copies
them onto `RunSnapshot.consumedAuthorization` with integer `sequence`, like
`lastSequence`. Resume requires an exact match. A legacy snapshot without a
citation is `authorization-citation-missing`. `decisionDigest` remains the
in-process gate identity and is no longer sufficient by itself for
SimulatedRuntime.

The recorder still takes `{id}` only on the request actor and now emits
`kind: human` on the stored event. Lineage stays `not-consumed`; it is not the
citation. Consume lives in `execution/consume.py` so SimulatedRuntime does not
import the recorder or lineage query.

Documented CLI order:

1. Create an empty EventStore (`with EventStore("research.db"): pass`).
   `authorizations record` refuses to create a database.
2. `researchos authorizations record …`
3. `researchos runs simulate …` citing that fact as sequence `"1"`.

A missing simulation database is still created, then consume fails closed if
the cited event is absent.

### Delivered in the E4 numbered slices

- M1-0: schema v2 verified high-water cache and query tables (ADR-0041);
  `SecretRef`; optional actor `kind` / `modelId`; SimulatedRuntime cancelled
  outcomes.
- M1-1: proposal / dissent / decision and `ResearchLedger`.
- M1-2: `ModelProvider` mock and digest-only `ai.call.*` facts.
- M1-3: local Markdown/PDF `evidence.imported`.
- M1-4: OpenAI-compatible HTTP adapter, `SecretRef`, CNY budget facts.
- M1-5: seeded synthetic metrics and static `researchos report`.
- M1-6: this consume rule and closure list.

### Explicitly not delivered

These MUST NOT be described as M1 complete:

- Issue #42 question channel; umbrella #38 still lists 提问/回答 and
  human-attention cost on the report.
- Signatures, expiry, or revocation of authorization; a remote or launch JWT.
- `NativeProcessRuntime`, remote Workers, GPU training.
- React Flow / editable canvas (`9-UIA`).
- T2 community adapter isolation (E5).
- File/keyring `SecretRef` backends.
- OpenAI Python SDK / LiteLLM / streaming / tool execution.
- GitHub / arXiv / web evidence connectors.
- Tag `v0.1.0-m1` (cut only when asked).
- Making the mock an HTTP server; `ai.call.failed` remains unused.
- Charter v0.2 consolidation (E8).

### Status changes this record authorizes

| Record | Change |
|---|---|
| ADR-0026 | Record status notes M1-6 consume of a local citation. |
| ADR-0032 | Record status notes SimulatedRuntime may cite `{eventId, sequence}` on this store; the event remains audit-only. |
| ADR-0035 | Lineage remains `not-consumed`. The Run citation is consume, not this query. |
| ADR-0036 | `decisionDigest` remains in-process identity and is no longer sufficient alone for SimulatedRuntime. |
| Issue #19 | Closed by this slice. |
| Issue #38 | Remains open. |
| Issue #42 | Remains open and independent. |

## Consequences

- A SimulatedRuntime Run can answer which local authorization row it consumed,
  and EventStore replay rebuilds the same citation.
- Swap, deny, non-human actor, digest drift, and project mismatch write zero
  lifecycle facts.
- NativeProcessPreflight and NativeProcessRuntime still do not consume the
  event.
- Charter §14.2 keeps the M0 history that `{eventId, sequence}` consume was
  not an M0 deliverable. E17 records that M1-6 delivered the local form.

## Validation

Independently checkable:

1. `SimulationRequest` requires `authorization`; committed examples cite
   `evt.authorization.example-minimal.1` sequence `"1"`.
2. SimulatedRuntime fail-closed codes cover missing, swap, type, invalid,
   non-human, not-authorized, binding, project, and resume citation drift.
3. Lineage reports still say `not-consumed`.
4. `researchos schema --check-all`, ruff, mypy, pytest, and coverage ≥ 85%.
5. Issue #38 and #42 remain open. No `v0.1.0-m1` tag is created by this PR.

## References

- [Issue #19](https://github.com/victorzhong0110/llm-research-os/issues/19)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
- [ADR-0032 Audit-only Plan Authorization Events](0032-audit-only-plan-authorization-events.md)
- [ADR-0035 Read-only Plan Authorization Lineage Query](0035-read-only-plan-authorization-lineage.md)
- [ADR-0036 In-process Run decisionDigest](0036-in-process-run-decision-digest.md)
- [ADR-0037 M0 Kernel-Proof Closure](0037-m0-kernel-proof-closure.md)
- [ADR-0038 Charter Errata after M0](0038-charter-errata-after-m0.md) E4 M1-6
- [Living threat model](../security/threat-model.md) TM-012 / TM-034 / TM-035 / TM-036
