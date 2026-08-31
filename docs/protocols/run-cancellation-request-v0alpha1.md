# RunCancellationRequest v0alpha1

> Status: Experimental external authoring contract
> Schema: `schemas/run-cancellation-request/v0alpha1.schema.json`

`RunCancellationRequest` supplies every caller-owned field needed to append
exactly one `run.cancel.requested` or `attempt.cancel.requested` ResearchEvent.
It requests cancellation; it is not evidence that a process received a signal,
an Attempt stopped, or a Run reached the `cancelled` outcome.

## Document shape

The document is a closed, alias-only, strict JSON/YAML object:

| Field | Meaning |
|---|---|
| `apiVersion` | Exactly `researchos.dev/v0alpha1` |
| `kind` | Exactly `RunCancellationRequest` |
| `projectId`, `experimentRevision`, `runId` | Existing Run aggregate binding |
| `target` | Closed `{"kind":"run"}` or `{"kind":"attempt","attemptId":"..."}` |
| `reasonCode` | Stable machine-readable reason identifier |
| `source`, `subject`, `streamid`, `actor.id` | Caller-owned ResearchEvent identity |
| `event.id`, `event.time` | Caller-owned identity and timezone-aware RFC3339 time for the single fact |
| `evidenceRefs` | Explicit, duplicate-free evidence identifiers; may be empty |

Python field names, trimming, scalar coercion, explicit nulls, unknown fields,
invalid URI references, invalid timestamps, duplicate evidence references,
JSON duplicate keys, YAML aliases, and symbolic-link request paths are rejected.

The command chooses the lifecycle `type` from `target`; callers cannot inject an
arbitrary lifecycle event. It supplies the fixed ResearchEvent Schema URI,
content type and `schemaVersion`. SQLite alone assigns `sequence`,
`sequencetype` and `streamversion`.

## Normative example

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "RunCancellationRequest",
  "projectId": "example-minimal",
  "experimentRevision": 1,
  "runId": "run.simulated",
  "target": {
    "kind": "attempt",
    "attemptId": "attempt.1"
  },
  "reasonCode": "researcher.requested",
  "source": "https://researchos.dev/projects/example-minimal",
  "subject": "run.simulated",
  "streamid": "stream.simulated",
  "actor": {
    "id": "researcher.alice"
  },
  "event": {
    "id": "evt.7.attempt.cancel.requested",
    "time": "2026-08-30T12:00:01Z"
  },
  "evidenceRefs": []
}
```

## State and append semantics

- The database and Run must already exist. A missing database is not created.
- One invocation appends at most one fact through RunControl replay, reducer
  preflight and the global-head CAS.
- `target.kind=run` emits `run.cancel.requested` and sets the Run snapshot's
  monotonic `cancellationRequested` flag.
- `target.kind=attempt` emits `attempt.cancel.requested` for the named active
  Attempt and sets only that Attempt flag unless the Run was already requested.
- Terminal Runs, missing Runs, revision drift, a non-active Attempt, duplicate
  event identity, corrupt storage and CAS conflicts fail before a new fact is
  committed. Conflicts are not retried.
- JSON output is exactly the existing `RunSnapshot v0alpha1`. Status remains
  `queued`, `running`, `retry_pending`, `lost` or `unknown`; this command never
  emits `attempt.cancelled` or `run.cancelled`.

## Deliberate omissions

This contract does not send POSIX signals, stop a Worker, execute a plugin,
retry a conflict, mint identity, or infer a cancellation outcome. It does not
freeze the open stream granularity or correlation/causation reference rules;
those envelope fields are not exposed by this request version. A future runtime
or Worker adapter must report its observed Attempt outcome as a separate fact.
`actor.id` is claimed audit metadata, not authenticated authority; M0 relies on
local operating-system access to the database and request file.
