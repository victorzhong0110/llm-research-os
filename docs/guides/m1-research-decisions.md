# M1 Research Decision CLI

## What the commands do

`researchos proposals submit`, `dissents record`, `decisions record`,
`questions ask`, and `questions answer` each append one research-decision fact
through a project-scoped CAS boundary. The database must already exist.
Caller-owned `id`, `time`, `source`, `subject`, and `streamid` come from the
request document. The store assigns `sequence`, `sequencetype`, and
`streamversion`.

```bash
uv run researchos proposals submit \
  examples/research-decisions/valid/proposal-submit.json \
  research.db --format json
uv run researchos dissents record \
  examples/research-decisions/valid/dissent-record.json \
  research.db --format json
uv run researchos decisions record \
  examples/research-decisions/valid/decision-record.json \
  research.db --format json
uv run researchos questions ask \
  examples/research-decisions/valid/question-ask.json \
  research.db --format json
uv run researchos questions answer \
  examples/research-decisions/valid/question-answer.json \
  research.db --format json
uv run researchos research ledger research.db \
  --project example-minimal --format json
```

`research ledger` rebuilds a read-only `ResearchLedger` for one `projectId`.
It is not persisted. `questions[]` carries open and answered entries with
`answeredQuestionCount` / `openQuestionCount`.

## What success means

Exit `0` on append means one fact was committed. JSON stdout is a closed
`ResearchFactReceipt` (`eventId`, `type`, `sequence`, `projectId`, `objectId`).
It does not echo rationale, objections, or predictions.

Exit `0` on `research ledger` means the fold completed. JSON stdout is the
versioned ledger. A stored dissent remains in `dissents[]` after a later
decision lists it in `overriddenDissentIds`.

`outcome=accept` on a proposal is not a launch credential. Plan authorization
stays the ADR-0030 gate.

## Errors and concurrency

Exit `1` is a domain refusal (unknown target, duplicate object id, proposal
not open). Exit `2` is invalid input, a missing or corrupt database, or a CAS
conflict. Conflicts are not retried. `ai` actors cannot record decisions.
A missing `rationale` is invalid. A second answer to the same `questionId`, an
option outside the closed list, `human` asking, or `ai` answering is refused.
Error output does not echo question or answer text (TM-022).

This slice does not call a model API, change the Run/Attempt reducer, persist
the ledger, or treat an answer as an instruction to another component.
