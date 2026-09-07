# M1 checkpoint command v0alpha1

> Status: Experimental integration path for the ADR-0038 E4 checkpoint sentence.
> This command does **not** close [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38).
> Numbered M1 slices are not the checkpoint.

`researchos m1 prove` records one offline research chain from a closed corpus:

ResearchSpec → Mock proposal (predictions and falsification conditions) →
dissent → question and answer → researcher decision with rationale →
(accept only) local authorization consume → simulated run → static report
linked to `eventId` values.

The path is ¥0 and opens no network. Every step is an EventStore fact.
`--decision reject` records the same research facts and MUST NOT append
`run.queued`.

## 1. Corpus files

The corpus directory MUST contain these names:

| File | Kind |
|---|---|
| `spec.yaml` | `ResearchProject` |
| `fixture.json` | `ModelFixture` whose `output` is a `ProposalSubmitRequest` |
| `generate.json` | `ModelGenerateRequest` (mock only) |
| `dissent.json` | `DissentRecordRequest` |
| `question-ask.json` | `QuestionAskRequest` |
| `question-answer.json` | `QuestionAnswerRequest` |
| `decision-accept.json` / `decision-reject.json` | `DecisionRecordRequest` |
| `authorization-request.json` | `PlanAuthorizationRequest` |
| `authorization-event.json` | `PlanAuthorizationEventRequest` |
| `simulation.json` | `SimulationRequest` |

The fixture output is the claimed model result. `prove` validates it as a
`ProposalSubmitRequest` **before** recording `ai.call.*`. `generate()` still
returns only digests. The recorded `outputDigest` MUST equal the digest of that
output object.

`proposedSpecDigest` MUST equal the live dry-run spec digest. `specDiffDigest`
MUST equal the JCS digest of:

```json
{
  "kind": "initial-spec",
  "specDigest": "<live spec digest>",
  "baseRevision": <spec metadata.revision>
}
```

That envelope is the checkpoint stand-in for a two-revision semantic diff when
the authorized spec is the same revision the proposal names.

The authorization request MUST already bind the live spec/registry/plan digests.
`prove` overwrites the authorization event binding and the simulation
`authorization: {eventId, sequence}` citation from the fact it just recorded.

## 2. Replay

After the chain is recorded, `prove` closes the store, reopens it, and requires
the same event ids, types, research ledger, and (on accept) Markdown report.

A second `prove` on a non-empty database fails closed. The command does not
retry CAS conflicts. It does not close Issue #38 and does not mint `v0.1.0-m1`.

## 3. Conformance

```bash
uv run researchos m1 prove \
  examples/m1-checkpoint \
  /tmp/m1-checkpoint.db \
  --format json
uv run pytest tests/test_m1_checkpoint.py
```
