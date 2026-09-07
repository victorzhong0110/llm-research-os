# Research Decision Objects v0alpha1

> Status: Experimental external contract for `proposal.submitted`,
> `dissent.recorded`, `decision.recorded`, and `ResearchLedger`.
> `question.asked` / `question.answered` remain Issue #42 and are not implemented.
> JSON Schema: `schemas/proposal-submit-request/v0alpha1.schema.json`,
> `schemas/dissent-record-request/v0alpha1.schema.json`,
> `schemas/decision-record-request/v0alpha1.schema.json`,
> `schemas/research-ledger/v0alpha1.schema.json`.
> Authority: [ADR-0039](../adr/0039-human-help-period-purpose.md) D2–D3,
> [ADR-0038](../adr/0038-charter-errata-after-m0.md) E1–E4,
> [ADR-0005](../adr/0005-researcher-final-decision.md).
> Tracking: Issues #41 (this slice) and #42 (question channel).

This document fixes the payloads of five ResearchEvent types through which a
human teaches the system what observation cannot supply, and through which an AI
component may ask for that help. They are event-sourced aggregates (charter §23
E1), never ResearchSpec fields. They do not execute anything and do not change
the Run/Attempt reducer (ADR-0024).

## 1. Event types

| Type | Emitted by actor kind | Purpose |
|---|---|---|
| `proposal.submitted` | `ai`, `human` | A structured proposal to move a project to a new revision |
| `dissent.recorded` | `ai`, `human` | A structured objection to a proposal, decision or conclusion |
| `decision.recorded` | `human`, `policy` | The researcher's (or a declared policy's) resolution, with rationale |
| `question.asked` | `ai`, `system` | The only sanctioned request for information from the researcher |
| `question.answered` | `human` | The researcher's answer, recorded as a fact with rights |

Actor kind is required on these event types. An `ai` actor MUST NOT emit
`decision.recorded` or `question.answered`; a `human` actor MUST NOT emit
`question.asked`. M1-1 enforces the three implemented types; the question pair
waits for Issue #42.

All five reuse the ResearchEvent v0alpha1 envelope unchanged: caller-owned `id`,
`time`, `source`, `subject`, `streamid`; store-owned `sequence`, `sequencetype`,
`streamversion`. `data.projectId` and `data.experimentRevision` bind the fact to
a project revision. `runId`, `attemptId` and `blockId` are absent unless the
target is a Run.

## 2. Common payload rules

Same discipline as `run-state` payloads: closed alias-only strict models, unknown
fields rejected, no trimming, no scalar coercion, JSON `null` rejected where a
field is optional (omit instead). Identifiers use the `EventIdentifier` grammar.
Semantic digests are `jcs-sha256:` per [digest-v0alpha1](digest-v0alpha1.md).

Text fields are Unicode scalar strings with these ceilings (draft values; the
implementer may tighten, not loosen):

| Field class | Max length |
|---|---|
| `statement`, `question`, `answer.text`, `rationale`, `uncertainty`, `whyNotObservable` | 4 000 |
| list item text (`objections[].statement`, `falsificationConditions[]`, `options[]`) | 1 000 |
| any list | 32 items |

Text is data. No field is interpreted as an instruction, expression or command.
Text MUST NOT be echoed in error messages (TM-022).

## 3. `proposal.submitted`

| Field | Type | Rule |
|---|---|---|
| `proposalId` | identifier | Unique per project |
| `baseRevision` | integer ≥ 1 | Revision the proposal starts from; equals `data.experimentRevision` |
| `specDiffDigest` | digest | Semantic digest of the `spec/diff` result between base and proposed revision |
| `proposedSpecDigest` | digest | Canonical digest of the proposed ResearchSpec document |
| `rationale` | text | Required, non-empty |
| `predictions` | list of `{id, statement, metric?, expectedDirection}` | ≥ 1 item; same shape as `ResearchSpec.hypotheses[].predictions[]` |
| `falsificationConditions` | list of text | ≥ 1 item |
| `riskAssessment` | `{data, method, safety, cost}` each text | All four keys present; empty string allowed |
| `evidenceRefs` | list of identifier | Duplicate-free; may be empty |

The proposed ResearchSpec document itself is not embedded (charter §8.3: bodies
live in artifacts). A proposal does not change any revision state by itself.

## 4. `dissent.recorded`

| Field | Type | Rule |
|---|---|---|
| `dissentId` | identifier | Unique per project |
| `targetKind` | `proposal` \| `decision` | Closed enum for M1-1. `conclusion` is reserved until that aggregate exists |
| `targetId` | identifier | Must resolve in the same project (projection-level check) |
| `targetId` | identifier | Must resolve in the same project (projection-level check) |
| `objections` | list of `{kind, statement}` | ≥ 1 item |
| `objections[].kind` | closed enum | `falsifiability`, `alternative-explanation`, `data-leakage`, `baseline-or-ablation`, `metric-validity`, `cost-benefit`, `negative-result-value`, `other` — the charter §9.3 checklist |
| `evidenceRefs` | list of identifier | Duplicate-free; may be empty |

A dissent is never mutated or deleted. A later decision references it (§5).

## 5. `decision.recorded`

| Field | Type | Rule |
|---|---|---|
| `decisionId` | identifier | Unique per project; the value later cited by `run.reviewed.decisionId` and `attempt.queued.retryDecisionId` |
| `targetKind` | `proposal` \| `run` \| `dissent` | Closed enum for M1-1. `question` is reserved for Issue #42 |
| `targetId` | identifier | Must resolve in the same project (projection-level check) |
| `outcome` | `accept` \| `reject` \| `modify` \| `continue` \| `defer` | Closed enum |
| `rationale` | text | **Required, non-empty.** A decision without rationale is invalid (ADR-0039 D2) |
| `overriddenDissentIds` | list of identifier | May be empty; every id must be a `dissent.recorded` earlier in the same project; the dissents remain in the log |
| `evidenceRefs` | list of identifier | Duplicate-free; may be empty |

`outcome=accept` on a `proposal` target marks that proposal's revision as
accepted in the ledger (§8). It is not a launch credential and does not authorize
a plan; plan authorization stays the ADR-0030 gate.

## 6. `question.asked` and `question.answered`

`question.asked`:

| Field | Type | Rule |
|---|---|---|
| `questionId` | identifier | Unique per project |
| `question` | text | Required |
| `uncertainty` | text | Required: what is unknown |
| `whyNotObservable` | text | Required: why available evidence, spec and history could not settle it |
| `options` | list of text | Optional closed choices; omit when free-form |
| `blocking` | boolean | Whether the asking component waits for the answer |
| `relatedProposalId` | identifier | Optional |
| `evidenceRefs` | list of identifier | What was consulted before asking; may be empty |

`question.answered`:

| Field | Type | Rule |
|---|---|---|
| `questionId` | identifier | Must match an earlier `question.asked` in the same project (projection-level check) |
| `answer` | `{text}` or `{option}` | Exactly one key; `option` must be one of the question's `options` |
| `rights` | `{status, allowedUses}` | `status` ∈ `allowed` \| `restricted` \| `unknown`; `allowedUses` ⊆ `research-read`, `retrieval`, `training`, `redistribution`; default `["research-read"]`; `unknown` cannot list `training` or `redistribution` (same rule as `DatasetSource`) |
| `evidenceRefs` | list of identifier | May be empty |

An answer is data for other components, never an instruction (charter §10.4).
A question that a component could have answered from the spec, evidence or
history is a defect; the ledger counts questions so this is visible (§8).

## 7. Cross-event invariants

Payload validation is per event and pure. The following are checked by the
read-only ledger fold (§8), not by the Run/Attempt reducer:

1. `targetId` / `overriddenDissentIds` / `questionId` resolve to earlier facts in
   the same `projectId`.
2. At most one `question.answered` per `questionId`.
3. `decision.recorded` on a `question` target requires that question to be
   answered or `outcome=defer`.
4. A `proposal` accepted by a decision is `accepted`; a later accepted proposal
   with a higher `baseRevision` marks the earlier one `superseded` (charter §23 E2
   revision lifecycle: Draft → Proposed → Validated → Accepted / Rejected →
   Superseded; `Validated` is derived from a dry-run `ready` report bound by
   `proposedSpecDigest`, recorded as a separate M1-1 event or left `Proposed`).
5. Overridden dissents are still present and unchanged in the fold output.

Violations fail closed with typed problem codes; the fold does not skip or repair.

## 8. Research ledger projection

`ResearchLedger` is a rebuildable, read-only fold over one `projectId`, in the
same style as `RunStateProjection`: pure `apply`, frozen snapshot, JSON Schema
`schemas/research-ledger/v0alpha1.schema.json`. It lists proposals with their
revision state, dissents with the decisions that overrode them, questions with
answer status, and the D4 counters:

| Counter | Definition |
|---|---|
| `decisionCount` | Number of `decision.recorded` |
| `answeredQuestionCount`, `openQuestionCount` | Per `questionId` |
| `rationaleCharacters` | Sum of `rationale` lengths in Unicode scalars |
| `overriddenDissentCount` | Distinct dissents referenced by decisions |

The outcome side of the metric (pre-registered prediction accuracy) is produced
by M1-5 from evaluation events; this ledger only supplies the attention side.

## 9. CLI (M1-1)

Each command takes a strict request document (same conventions as
`RunCancellationRequest`: caller-owned identity and time, explicit `evidenceRefs`,
existing database required, one RunControl-style CAS append, no retry):

`researchos questions ask` / `questions answer` are Issue #42. M1-1 ships:

```text
researchos proposals submit  REQUEST research.db
researchos dissents record   REQUEST research.db
researchos decisions record  REQUEST research.db
researchos research ledger   research.db --project ID [--format json]
```

Exit codes follow the repository convention: `0` fact appended or ledger built;
`1` valid input but a domain refusal (for example, an answer to an unknown
question); `2` input, integrity or concurrency error. Successful output is the
versioned ledger snapshot or a closed receipt, never the payload text echoed.

## 10. Non-goals for M1-1

- No model API call; the mock provider is M1-2.
- No change to Run/Attempt lifecycle types or reducer semantics.
- No automatic decision, auto-accept, or policy engine beyond the `policy` actor
  kind being allowed on `decision.recorded`.
- No training-eligibility flag; eligibility is derived later under ADR-0039 D5.
- No persistence of the ledger; it is rebuilt from the event store.
- No signature or authentication of the human actor; `actor.id` remains claimed
  metadata, as in M0.

## 11. Acceptance tests

Corpus under `examples/research-decisions/{valid,invalid}/` plus tests that:

1. Reject `decision.recorded` without `rationale` or with an empty one.
2. Reject `question.answered` whose `questionId` has no prior `question.asked`
   in the same project; reject a second answer.
3. Reject `question.asked` from a `human` actor and `decision.recorded` or
   `question.answered` from an `ai` actor.
4. Reject an `option` answer not present in the question's `options`.
5. Reject `rights.status=unknown` with `training` or `redistribution` in
   `allowedUses`.
6. Show a stored dissent unchanged in the ledger after a later decision lists it
   in `overriddenDissentIds` (ADR-0005 validation).
7. Ledger counters equal hand-computed values on a fixed valid corpus.
8. Replay equality: ledger built from the store equals ledger built from the
   same events in a second process.
9. Non-echo: error output for invalid text fields does not contain the text.
10. Schema check: `researchos schema --check-all` includes the new contracts
    registered in `cli/contracts.py`.

## 12. Implementation notes (non-normative)

- Suggested placement: `src/llm_research_os/research/` for payload models,
  ledger fold and request documents; `src/llm_research_os/cli/research_commands.py`
  for the commands; schemas under `schemas/research-ledger/` and one request
  schema per command, registered in `cli/contracts.py`.
- Reuse `EventDocumentModel`, `EventIdentifier`, `RunStateDocumentModel`
  conventions, `DataUse` / `RightsStatus` enums and the `DatasetSource` rights
  validator rather than redefining them.
- Reuse `RunControl`'s isolate → validate → CAS append pattern; a
  project-scoped append boundary may be extracted if RunControl's Run binding
  does not fit.
- Deliver #41 and #42 as two pull requests in that order; #42 depends on the
  ledger from #41.
- Update this document's status header and add it to README's protocol list only
  when the schema and tests land.
