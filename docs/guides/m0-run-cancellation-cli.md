# M0 Run Cancellation CLI

## What the command does

`researchos runs cancel` records one explicit cancellation-request fact for an
existing Run or its active Attempt:

```bash
uv run researchos runs cancel \
  examples/run-cancellation-requests/valid/run.json \
  research.db --format json
```

The request is validated against
`schemas/run-cancellation-request/v0alpha1.schema.json` before SQLite is opened.
The database must already be an initialized event store; a missing path is not
created. The command rebuilds the target Run, validates the transition and uses
RunControl's frozen global-head CAS to append exactly one ResearchEvent.

## What success means

Exit `0` means the request fact was committed. JSON stdout is exactly the
versioned `RunSnapshot`. Inspect `cancellationRequested` on the Run or target
Attempt. The status does not become `cancelled` merely because the request was
recorded.

Text output explicitly reports:

```text
cancellation request: recorded
process signal sent: false
cancellation outcome: not observed
```

The command sends no signal and has no Worker connection. SimulatedRuntime
consumes a recorded request on the next `runs simulate` / `run()` and emits
`attempt.cancelled` and, when the Run-level request is present, `run.cancelled`.
Completion or failure may still win a race already in progress, as defined by
the Run/Attempt state protocol. `unknown` is not collapsed to cancelled.

## Errors and concurrency

Exit `2` covers invalid or symlinked input, a missing/corrupt database, missing
Run, revision drift, wrong or terminal Attempt, terminal Run, duplicate event
ID and CAS conflict. Errors are emitted as `ProblemReport` in JSON mode and do
not echo unknown request field names or values. The command never retries a CAS
conflict; the caller must inspect the new facts and submit a fresh request with
new explicit identity if cancellation is still appropriate.

Use the existing read-only commands to verify the result:

```bash
uv run researchos events verify research.db --format json
uv run researchos events replay research.db --page-size 100
```

This M0 slice does not implement NativeProcessRuntime, Worker stop protocols,
automatic cancellation completion, multi-event cancellation transactions,
network calls, GPU use, model APIs or paid actions.
`actor.id` is not authenticated: local filesystem and process access remain the
authorization boundary until a later policy/identity slice.
