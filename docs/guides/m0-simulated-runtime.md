# M0 SimulatedRuntime

## What this slice proves

A ready single-task `simulated.experiment@0.1.0` plan can drive a deterministic
Run/Attempt lifecycle through `RunControl` and EventStore, and a later process
can rebuild the same `RunSnapshot` by replaying those facts.

It does **not** train a model, import a block entrypoint, mint identity, retry a
compare-and-set conflict, or treat simulated completion as a scientific result.

## Minimal use

```python
from llm_research_os.blocks import build_registry
from llm_research_os.execution import (
    SimulatedRuntime,
    SimulationEventIdentity,
    SimulationRequest,
)
from llm_research_os.spec import load_spec
from llm_research_os.storage import EventStore

EVENTS = (
    "run.queued",
    "run.started",
    "attempt.queued",
    "attempt.started",
    "attempt.succeeded",
    "run.completed",
)

request = SimulationRequest(
    workflow_id="workflow.simulation",
    attempt_id="attempt.1",
    source="https://researchos.dev/projects/example-minimal",
    subject="run.simulated",
    stream_id="stream.simulated",
    actor_id="researcher.alice",
    events={
        event_type: SimulationEventIdentity(
            id=f"evt.{index}.{event_type}",
            time="2026-08-30T12:00:00Z",
        )
        for index, event_type in enumerate(EVENTS, start=1)
    },
)

with EventStore("research.db") as store:
    runtime = SimulatedRuntime(
        store,
        build_registry(),
        project_id="example-minimal",
        run_id="run.simulated",
    )
    result = runtime.run(load_spec("examples/valid/minimal.yaml"), request)
    print(result.disposition)
    print([item.event.type for item in result.stored])
```

`projectId` and `experimentRevision` come from the frozen ResearchSpec.
`workflowId`, `runId`, `attemptId`, `source`, `subject`, `streamid`, actor id,
and every event `id` / `time` are supplied by the caller. The runtime does not
generate them.

`examples/valid/minimal.yaml` must state `outcome` explicitly:

```yaml
config:
  outcome: success
  seed: 0
```

`seed` is bound into the plan digest. This slice does not use it as a random
seed.

## Event sequences

Success (`outcome: success`), exactly six facts:

1. `run.queued` — `workflowId`, three digests, `maxAttempts: 1`
2. `run.started`
3. `attempt.queued` — `ordinal: 1`, `retryOf: null`, `retryDecisionId: null`
4. `attempt.started`
5. `attempt.succeeded`
6. `run.completed`

Failure (`outcome: failure`), exactly six facts: the same first four events,
then `attempt.failed` (`reasonCode: simulation.outcome.failure`, `retryHint:
not-retryable`) and `run.failed` (`reasonCode: simulation.outcome.failure`).
The Run is `failed`. It is not retried.

Unknown (`outcome: unknown`), exactly five facts: the same first four events,
then `attempt.unknown` (`reasonCode: simulation.outcome.unknown`). The Run
stays `unknown`. SimulatedRuntime does not emit `attempt.failed`, `run.failed`,
or `run.completed`, and does not guess lost, cancelled, or success.

`run.reviewed` is never emitted. Simulated completion is not a research
conclusion.

## Security boundary

Allowed side effects are the lifecycle appends above. SimulatedRuntime does not
import or call a block entrypoint, `eval` / `exec`, subprocess, sockets, HTTP,
DNS, dynamic import, environment expansion, secret reads, GPU/MPS/CUDA probes,
model APIs, paid actions, or ArtifactStore writes. It does not change SQLite
schema, persist a Run table, unroll loops, pass data-edge values, authorize
retries, or run NativeProcessRuntime / OCI / Workers.

Unsupported plans — multiple tasks, edges, approval, loop, resources, policy
requirements, other runtime types, or a missing/malformed `outcome` — fail
closed with zero writes. Error text does not echo task config, payloads,
unknown fields, secrets, or control characters.

A simulated `completed` disposition is a controlled lifecycle finish. It does
not mean training succeeded, metrics are valid, or a hypothesis is supported.
`unknown` is never degraded to failure or success.

## Recovery and conflict

`run()` rebuilds from EventStore before appending. An empty store starts at
`run.queued`. A legal prefix continues with the next event on the frozen
outcome path. `completed` / `failed` return the existing snapshot with zero new
facts. `unknown` / `lost` / cancelled / `cancellationRequested` return
`unresolved` without inferring an outcome.

The six (or five) events are **not** one SQLite transaction. An interrupted
invocation leaves the committed prefix. Reopening the database and calling
`run()` again continues from replay, using the same caller-owned identities for
events that have not yet been written.

Each write still goes through RunControl replay, preflight, and global CAS.
`EventSequenceConflictError` is not caught, slept, or retried, and a conflict
is not success. `DuplicateEventError`, `EventIntegrityError`, and schema errors
keep their EventStore meanings.

A caller that mutates the original spec or nested config after freeze cannot
change the outcome or digests that will be written.

## Current non-goals

- NativeProcessRuntime, OCI, remote-service, composite, or Python execution
- Multi-node scheduling and data-port values
- LoopBlock expansion or `until` evaluation
- ApprovalBlock, paid resources, metrics, artifacts
- Automatic retry, cancel, heartbeat, or lost/recovered policy
- Run/start/stop CLI and a SimulatedRuntime JSON Schema
- Minting `id`, `time`, `streamid`, `correlationid`, or `causationid`
