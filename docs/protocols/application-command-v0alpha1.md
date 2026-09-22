# ApplicationCommand and ApplicationReceipt v0alpha1

> Status: Experimental external command contract for R02
> Schemas: `schemas/application-command/v0alpha1.schema.json`,
> `schemas/application-receipt/v0alpha1.schema.json`

`ApplicationCommand` is the shared request used by `researchos app execute` and
`ApplicationService.execute`. `ApplicationReceipt` is the durable result of one
successful command. A receipt cites fact event ids and artifact digests. It is
not an event, not a Worker grant, and not launch authority.

## Command

| Field | Meaning |
|---|---|
| `apiVersion` | Exactly `researchos.dev/application/v0alpha1` |
| `kind` | Exactly `ApplicationCommand` |
| `commandId` | Caller-owned command identity |
| `actorId` | Caller-owned actor identity |
| `submittedAt` | Caller-owned timezone-aware RFC3339 time. The service does not read a clock |
| `expectedHead` | EventStore head the caller observed. Required for ledger, decision, revision list, run show, and run simulate |
| `expectedRevision` | Spec or request revision the caller reviewed. Required for validate, diff, dry-run, decision, and simulate |
| `operation` | One closed operation object discriminated by `kind` |

Operation kinds are `workspace.show`, `spec.validate`, `spec.diff`,
`plan.dry-run`, `revision.list`, `research.ledger`, `research.decision`,
`run.show`, and `run.simulate`. Paths inside an operation are caller inputs.
The request digest is JCS SHA-256 of the actor, time, expected head, expected
revision, and operation content. File inputs contribute byte digests, so two
paths with the same bytes are the same content.

The same `commandId` and the same request digest return the stored receipt
with `disposition=replayed` and do not append another fact. The same
`commandId` with different content fails `receipt-conflict`. A head or
revision that does not match fails `stale-head` or `stale-revision` before a
new fact is written. Cross-project documents fail `project-mismatch`.

Mutating operations reuse `ResearchControl` and `SimulatedRuntime`. Repeated
simulation of an existing run does not create a second Run. Refused commands
do not write a receipt, so a later correction can use the same `commandId`.

`expectedHead` is required by the command model for store operations. That
cross-field rule is enforced by the loader. The generated JSON Schema rejects
unknown fields, missing `commandId`, and a negative `expectedHead`; see
`examples/application-command/invalid/`.

## Receipt

| Field | Meaning |
|---|---|
| `disposition` | `committed` on first success, `replayed` when the stored receipt is returned |
| `requestDigest` | Digest of the command content, not of `commandId` |
| `observedHead` | EventStore head after the command |
| `factEventIds` | Facts this command appended, or the existing Run facts when simulation appended nothing |
| `artifactDigests` | `sha256:` evidence refs that verified in the workspace CAS |
| `resultDigest` | JCS SHA-256 of `result` |
| `result` | Operation result. Dry-run, ledger, and run results reuse their existing documents |

## Workspace binding

`researchos app init` writes `workspace.json` with `projectId`, `controlDb`,
`casRoot`, and `workerRoot`. Relative paths are workspace-relative. The
control database directory, the control database file, and the CAS root must
not overlap the Worker root. Operation receipts live in
`operation-receipts.sqlite` in the workspace root. That file is not the
EventStore.

## Schema v2

R02 does not add an EventStore migration. `SCHEMA_VERSION` stays 2. Commands
open the existing schema, and historical `event_digest` values are not
rewritten. Receipts are workspace operation state that point at fact ids.

## Deliberate omissions

No Web API, native user-code launch, SSH, new authority store, or workflow
engine. A simulated `completed` status remains a simulation result, not a
scientific conclusion and not a launch credential. Audit signatures are not
accepted as launch input.
