# Synthetic metrics and static Run report v0alpha1

## Status and authority

M1-5 adds two optional SimulatedRuntime facts and one read-only projection:

- `training.step` / `evaluation.metric` ResearchEvent types with `kind: synthetic`
- `researchos report RUN` static HTML or Markdown

There is no JSON Schema for the rendered report. EventStore remains the fact
source. The report is a rebuildable projection (TM-011, TM-023). React Flow is
not used.

Caller-owned identities for the two metric types live on
[SimulationRequest v0alpha1](simulation-request-v0alpha1.md). The runtime does
not mint `id`, `time`, or `streamid`, and does not call a clock or CSPRNG.

## Synthetic payloads

Both types are emitted only on the success path, after `attempt.started` and
before `attempt.succeeded`, and only when the request includes those keys.
They are not Run/Attempt lifecycle types; RunControl rejects them. SimulatedRuntime
appends them through EventStore. The Run reducer stamps them as unrelated facts
on the same `(projectId, runId)` aggregate.

Numeric values are I-JSON decimal strings `0.NN` derived from
`jcs-sha256:` of `{"attemptId", "runId", "type"}`. Spec `config.seed` is not a
CSPRNG seed.

`training.step` payload:

| Field | Rule |
|---|---|
| `kind` | exactly `synthetic` |
| `step` | exactly `1` |
| `loss` | `^0\.[0-9]{2}$` |
| `seedDigest` | JCS digest of `{attemptId, runId, type}` |

`evaluation.metric` payload:

| Field | Rule |
|---|---|
| `kind` | exactly `synthetic` |
| `name` | exactly `accuracy` |
| `value` | `^0\.[0-9]{2}$` |
| `split` | exactly `synthetic` |
| `seedDigest` | JCS digest of `{attemptId, runId, type}` |

Actor `kind` is `system`. `data.runId` and `data.attemptId` are required.
These facts are not training success and not a scientific metric.

## Report command

```bash
uv run researchos report run.simulated \
  --database research.db \
  --format markdown
```

`--format html` writes a static document (no JavaScript). `--project` selects
the `(projectId, runId)` aggregate when supplied. Without `--project`, a `runId`
that appears in more than one project is `run-project-mismatch`. The database
must already exist.

Sections, in order: Research, Training, Cost, Lineage, Event index. Every
claim that reports a stored fact cites that fact's `eventId` as a fragment
link into the event index. Fragment destinations are percent-encoded so
punctuation in an id cannot break Markdown or HTML anchors; visible event ids
are HTML `<code>` text (not Markdown code spans) so backticks and markup in an
id stay literal. The index uses the same encoding. Cost always includes
human-attention counters from the project ledger (`decisionCount`,
`answeredQuestionCount`, `openQuestionCount`, `rationaleCharacters`) and does
not echo question or answer text. When outstanding reservations remain, Cost
states the reserved amount and that actual cost is unknown.

The report freezes EventStore high-water `H` once and folds every section from
that prefix, including consumed `plan.authorization.evaluated`. Facts appended
after `H` are omitted. Authorization citations are resolved from the frozen
prefix by event id; the report MUST NOT re-query the live store.

A resumed synthetic metric with the same event id MUST match the canonical
caller document (type, Run, payload). Id+type agreement is not enough.
Lineage also cites the consumed authorization row when
`RunSnapshot.consumedAuthorization` is present; that event has a null
`runId` so it is not in the Run-scoped lineage list.

| Exit code | Meaning |
|---|---|
| `0` | report written to stdout |
| `1` | no events for `RUN` (`run-not-found`) |
| `2` | missing/corrupt store, invalid identifier, project mismatch, or fold failure |

## Non-goals

- React Flow / editable canvas (`9-UIA` unchanged)
- Real trainer metrics, GPU telemetry, or treating `kind: synthetic` as evaluation
- JSON report schema
