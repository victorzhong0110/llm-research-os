# M2-0 Worker CLI

Loopback Worker registration, HMAC grants, and the CPU prove path.
Protocol: [Worker v0alpha1](../protocols/worker-v0alpha1.md),
[Authorization grant v0alpha1](../protocols/authorization-grant-v0alpha1.md).
Constraint record: [ADR-0043](../adr/0043-m2-loopback-worker-and-hmac-grants.md).

This path does **not** close Issue #38, does not spend GPU, and does not
start NativeProcessRuntime.

## Register and grant

The database must already exist. Worker registration is a human fact.
Grant recording does not print the HMAC token.

```bash
uv run researchos workers register \
  examples/m2-checkpoint/worker.json \
  research.db --format json
uv run researchos grants record \
  examples/m2-checkpoint/grant.json \
  research.db --format json
```

## One-command CPU loop

```bash
uv run researchos m2 prove \
  examples/m2-checkpoint \
  research.db \
  --format json
```

The command creates an empty EventStore, consumes local plan authorization,
registers the corpus Worker, records a grant, queues a Run, serves loopback
long poll, executes the CAS-pinned `brick.py`, stores the report object,
appends `work.completed`, then `attempt.succeeded` / `run.completed`. It
reopens the store and requires the same events and Markdown report.

`--artifacts` selects the CAS root (created if missing). Default is
`<database-stem>-artifacts` beside the database.

Exit `0` is a recorded CPU loop, not scientific success and not GPU
completion. JSON stdout is `M2CheckpointReceipt` (ids and digests only).
