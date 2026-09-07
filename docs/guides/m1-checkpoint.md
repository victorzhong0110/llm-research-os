# M1 checkpoint CLI

## What the command does

`researchos m1 prove CORPUS DATABASE` records one offline research chain from
the committed corpus. It is the integration path for the ADR-0038 E4 checkpoint
sentence. It does **not** close Issue #38.

```bash
uv run researchos m1 prove \
  examples/m1-checkpoint \
  research.db \
  --format json
```

`--decision reject` records Mock proposal, dissent, question/answer, and a
reject decision. It must not queue a Run.

The database is created if missing and must be empty. Exit `0` means the chain
was recorded and replayed. JSON stdout is `M1CheckpointReceipt` (ids, digests,
attention counters). It does not echo rationale, objections, or fixture text.
Exit `2` is a corpus, digest, or empty-store contract failure. Exit `1` is a
domain refusal from an underlying control.

On `--format text` with `accept`, the static Markdown report is printed after
the receipt header. Every research summary still cites an `eventId`.

The command uses only `DeterministicMockProvider`. It does not open a network
connection, resolve a `SecretRef`, or treat simulation `completed` as scientific
success.

Protocol: [M1 checkpoint command v0alpha1](../protocols/m1-checkpoint-v0alpha1.md).
