# M1 synthetic metrics and static Run report

## What this slice proves

A success-path SimulatedRuntime can append seeded synthetic `training.step` and
`evaluation.metric` facts when the SimulationRequest supplies those identities.
`researchos report RUN` rebuilds a static HTML or Markdown projection with
research, training, cost, and lineage sections. Every stored-fact summary links
to an `eventId`.

It does not train a model, call a CSPRNG, open a network, or treat synthetic
values as scientific results. React Flow is not used.

## Emit metrics

```bash
uv run researchos runs simulate \
  examples/valid/minimal.yaml \
  examples/simulation-requests/valid/success-with-metrics.json \
  research.db --format json
```

Without the extra `events` keys, the six-event M0 success path is unchanged.

## Render the report

```bash
uv run researchos report run.simulated \
  --database research.db \
  --format markdown
```

`--format html` is a static document: no JavaScript, no React Flow. Exit `1`
means the Run id is absent. Exit `2` is input, integrity, or fold failure.
The report is not a fact source; replay `events` to audit.

The report lineage section also cites the consumed authorization fact by
`eventId` even though that event has a null `runId` and is therefore absent from
`report.lineage`.

Protocol: [Synthetic metrics and static Run report v0alpha1](../protocols/run-report-v0alpha1.md).
