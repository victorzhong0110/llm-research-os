# SimulationRequest v0alpha1

## Status and authority

`SimulationRequest` is the external input contract for the M0 deterministic
SimulatedRuntime CLI. The committed Draft 2020-12 JSON Schema is the structural
cross-language contract:

```text
schemas/simulation-request/v0alpha1.schema.json
```

The Pydantic reference validator additionally enforces semantic uniqueness of
event IDs. SimulatedRuntime checks that the identities needed by the selected
ResearchSpec outcome and any resumed prefix are present before the first event
of that invocation is appended.

This contract packages caller-owned identity. It does not authorize execution,
choose an outcome, assign an event sequence, or settle the open ResearchEvent
questions about stream granularity and correlation/causation.

## Document shape

| Field | Rule |
|---|---|
| `apiVersion` | exactly `researchos.dev/v0alpha1` |
| `kind` | exactly `SimulationRequest` |
| `runId` | closed ResearchEvent identifier; supplied by caller |
| `workflowId` | exact workflow selected from the ResearchSpec |
| `attemptId` | identity of the sole simulated Attempt |
| `source` | RFC 3986 URI-reference used on emitted ResearchEvents |
| `subject` | non-empty CloudEvents string used on emitted events |
| `streamid` | explicit ResearchEvent stream identity |
| `actor.id` | explicit actor identity |
| `events` | closed map from supported lifecycle type to `{id, time}` |

Every event identity contains a non-empty CloudEvents string `id` and a
timezone-bearing RFC3339 string `time`. IDs across the map must be unique.
Neither strings nor identifiers are trimmed, and JSON numbers, booleans, or
other types are not coerced to strings.

The only recognized `events` keys are:

- `run.queued`, `run.started`, `run.completed`, `run.failed`, `run.cancelled`;
- `attempt.queued`, `attempt.started`, `attempt.succeeded`,
  `attempt.failed`, `attempt.unknown`, `attempt.cancelled`.

The map may contain only the path needed by a specific outcome. Cancel
continuations also need `attempt.cancelled` and/or `run.cancelled`. The map may
also be empty for a terminal idempotent replay, but an empty or incomplete map
cannot start or continue a nonterminal Run. Missing identities are an error; the
CLI does not generate them. Explicit `null` identities and unknown lifecycle keys
are invalid.

## Normative success request

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "SimulationRequest",
  "runId": "run.simulated",
  "workflowId": "workflow.simulation",
  "attemptId": "attempt.1",
  "source": "https://researchos.dev/projects/example-minimal",
  "subject": "run.simulated",
  "streamid": "stream.simulated",
  "actor": {
    "id": "researcher.alice"
  },
  "events": {
    "run.queued": {
      "id": "evt.1.run.queued",
      "time": "2026-08-30T12:00:00Z"
    },
    "run.started": {
      "id": "evt.2.run.started",
      "time": "2026-08-30T12:00:00Z"
    },
    "attempt.queued": {
      "id": "evt.3.attempt.queued",
      "time": "2026-08-30T12:00:00Z"
    },
    "attempt.started": {
      "id": "evt.4.attempt.started",
      "time": "2026-08-30T12:00:00Z"
    },
    "attempt.succeeded": {
      "id": "evt.5.attempt.succeeded",
      "time": "2026-08-30T12:00:00Z"
    },
    "run.completed": {
      "id": "evt.6.run.completed",
      "time": "2026-08-30T12:00:00Z"
    }
  }
}
```

## CLI binding

```bash
uv run researchos runs simulate \
  examples/valid/minimal.yaml \
  examples/simulation-requests/valid/success.json \
  research.db --format json
```

The command loads the ResearchSpec and request before opening the database,
builds a sealed inert registry, and delegates lifecycle decisions and every
append to SimulatedRuntime and RunControl. A missing database is initialized;
an existing supported database is resumed. No identity, time, sequence, stream
version, retry, cancellation, or scientific conclusion is inferred by the CLI.

JSON success or domain-negative output is exactly a `RunSnapshot v0alpha1`, so
the existing run-state Schema remains authoritative. Text output also reports
the simulation disposition and number of events appended by this invocation.

| Exit code | Meaning |
|---|---|
| `0` | Run snapshot is `completed` |
| `1` | controlled `failed`, `unknown`, or `unresolved` disposition |
| `2` | invalid input, unsupported plan, integrity failure, or CAS conflict |

Exit `0` means only that the controlled simulated lifecycle completed. It is
not evidence that training succeeded or a hypothesis is supported.

## Schema and semantic boundary

JSON Schema checks field names, JSON types, identifier shapes, URI-reference
structure, RFC3339 syntax, and the closed lifecycle key set. The reference
validator performs component-level timestamp/URI validation and rejects
duplicate event IDs. SimulatedRuntime, not Schema, chooses the outcome path from
the frozen ResearchSpec and checks path completeness, registry/plan digests,
resume identity, lifecycle legality, and duplicate IDs already in EventStore.

YAML aliases, duplicate JSON/YAML keys, symbolic links for execution inputs,
oversized documents, and invalid Unicode are rejected by the local loader.

## Non-goals and open questions

This contract does not add NativeProcessRuntime, arbitrary Python or shell
execution, network access, GPU probing, ArtifactStore writes, automatic retry,
stop/cancel policy, metric emission, or paid actions. Existing open questions
remain open: `streamid` granularity, the complete ResearchEvent type catalog,
correlation/causation rules, retry authority, Worker timeout policy, and event
payload size/depth limits.
