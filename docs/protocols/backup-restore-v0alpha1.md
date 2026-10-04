# Backup and restore protocol v0alpha1

Status: **candidate on the R15 branch; not merged, not accepted.**

This document defines the on-disk contract for a project backup image and for the
reports returned by creating, verifying, and restoring one. It is additive: it
introduces no new execution authority and changes no existing event, Worker, or
research contract.

## Contract

| Contract | Schema | Purpose |
| --- | --- | --- |
| `BackupManifest` | [`backup-manifest/v0alpha1.schema.json`](../../schemas/backup-manifest/v0alpha1.schema.json) | Self-describing image header |
| `BackupReport` | [`backup-report/v0alpha1.schema.json`](../../schemas/backup-report/v0alpha1.schema.json) | Outcome of `backup create` and `backup verify` |
| `RestoreReport` | [`restore-report/v0alpha1.schema.json`](../../schemas/restore-report/v0alpha1.schema.json) | Outcome of `backup restore` |
| `WorkspaceDiagnostic` | [`workspace-diagnostic/v0alpha1.schema.json`](../../schemas/workspace-diagnostic/v0alpha1.schema.json) | Redacted `workspace doctor` output |

All four carry `apiVersion: researchos.dev/recovery/v0alpha1` and accept aliases
only. They are generated from Pydantic; the committed files are never edited by
hand and `researchos schema --check-all` is the authority.

## Image layout

```text
<image>/
  backup-manifest.json          manifest, written last
  events.sqlite3                standalone snapshot, no -wal or -shm sidecar
  cas/objects/sha256/<xx>/<rest> referenced immutable objects
```

The object subtree mirrors the live CAS layout under an image-local `cas/`
prefix, so an image can be moved, mounted, or archived without being mistaken
for a workspace root.

## Snapshot rule

The EventStore copy is taken with the SQLite online backup API. Copying the
database file is not an accepted method: a live WAL database copied as a file
can capture a torn page set and miss committed content.

Because `EventStore` opens every database in WAL mode, reading the snapshot
would leave committed pages in a `-wal` sidecar that the manifest digest does not
cover. The snapshot is therefore collapsed to one standalone file — checkpoint,
`journal_mode=DELETE`, sidecars removed — *before* `snapshotDigest` is taken, and
the image is re-verified from a copy so it is verified in the shape it will be
restored.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `projectId` | Workspace project identity carried into the restored workspace |
| `createdAt` | RFC 3339 UTC timestamp supplied by the caller |
| `highWater`, `eventCount` | Verified prefix the snapshot actually contains |
| `lastEventDigest` | Content digest of the last event in the prefix, or absent when empty |
| `schemaVersion`, `schemaDigest` | Store schema the image was written at |
| `snapshotDigest`, `snapshotBytes` | Raw-byte digest and size of `events.sqlite3` |
| `objects[]` | `digest`, `sizeBytes`, `storageKey` for each referenced object |
| `totalObjectBytes` | Sum of object sizes |
| `relaunchPolicy` | Always `not-relaunched` |

`objects[]` is derived by replaying the verified prefix with the same
digest-reference rule the artifact projection uses. Only digests in CAS form
(`sha256:` + 64 lowercase hex) name a file object; a `jcs-sha256:` document
digest has no object to copy. A `sha256:` digest referenced by the prefix but
absent from the workspace **aborts the backup** — a partial image that restores
to a broken project is worse than no image.

## Verify

`backup verify` re-derives the image from its own bytes. The manifest is an
assertion to be checked, not an input to be believed:

1. recompute `events.sqlite3` raw-byte digest **and** its size;
2. compare `schemaVersion` and `schemaDigest` against this build;
3. require each `storageKey` to equal the key derived from its `digest`, so no
   hand-edited key can redirect a read or a write;
4. recompute every object digest and size;
5. re-run `verify_integrity()` on a copy, then compare the event count, the head,
   **and** the last event digest;
6. **re-derive the object set from the events** and require it to equal the
   manifest's. This is the check that a manifest cannot quietly drop an object
   and still verify;
7. require the object sizes to sum to `totalObjectBytes`.

An earlier implementation of this document claimed verify "trusts nothing in the
manifest" while in fact reading eight fields from it verbatim and never
re-deriving the object set. Dropping one `objects[]` entry produced a
`verified: true` image that restored a project referencing an object it did not
hold. The list above is what the claim now means, and step 6 exists because of
that defect.

Any mismatch is a `BackupIntegrityError` with a closed code. Verification does
not modify the image, and `backup restore` uses the exact manifest object the
verification checked rather than re-reading the file.

## Restore

`backup restore` verifies the image completely **before** it writes anything, so
a damaged image can never become the head of a project. It then:

1. initializes a new workspace from the manifest's `projectId` (overridable);
2. copies the snapshot into the control store, staged and renamed;
3. copies each referenced object into the CAS and re-verifies its size;
4. compares the restored store against the image by recomputed event digests and
   a recomputed research-ledger content digest;
5. reports every Run left non-terminal as `unknown`.

### The no-relaunch rule

A restore copies facts. It does not:

- append any event — `appendedEvents` is always `0` and the restored high-water
  equals the image high-water;
- start a Worker, dispatch a Run, or resume an Attempt;
- convert an unobservable in-flight task into a success, failure, or stop.

A Run that was not terminal when the image was taken is returned in
`reconciledRuns` with `observation: unknown` and
`nextAction: reconcile-manually`. Listing a Run is not relaunching it
([ADR-0054](../../adr/0054-process-observation-tristate.md)). Reconciliation is
an explicit operator action against the live system.

## Operator entry points

| Command | Contract produced |
| --- | --- |
| `researchos workspace demo --root DIR` | Creates and populates one offline workspace from the packaged corpus, then reports health |
| `researchos workspace doctor [--deep]` | `WorkspaceDiagnostic` |
| `researchos workspace migrate` | Version report; no new contract |
| `researchos backup create/verify` | `BackupReport` |
| `researchos backup restore` | `RestoreReport` |

`workspace demo` refuses a non-empty root with `demo-path-occupied` and touches no
network, Worker, or paid resource.

## Errors

| Code | Raised when |
| --- | --- |
| `backup-path-occupied` | Destination exists and is not empty |
| `backup-path-invalid` | Destination exists and is not a directory |
| `backup-manifest-missing` | No readable manifest |
| `backup-manifest-invalid` | Manifest is not a valid contract |
| `backup-snapshot-mismatch` | Snapshot bytes differ from `snapshotDigest` |
| `backup-event-count-mismatch` | Snapshot does not contain the manifest prefix |
| `backup-snapshot-incomplete` | Collapsed snapshot lost the verified prefix |
| `backup-snapshot-failed` | The control store could not be snapshotted or collapsed |
| `backup-snapshot-not-standalone` | The snapshot could not be collapsed out of WAL mode |
| `backup-too-large` | The control store exceeds the supported backup size |
| `backup-object-missing` | A referenced object is absent from the workspace |
| `backup-object-mismatch` | An object differs from its manifest digest or size, or the sizes do not sum |
| `backup-object-set-mismatch` | The image objects are not the objects its events reference |
| `backup-object-path-invalid` | A manifest object key is not the key derived from its digest |
| `backup-schema-mismatch` | The image was written at a schema this build does not support |
| `backup-event-digest-mismatch` | The snapshot head does not match `lastEventDigest` |
| `backup-snapshot-missing` | The event snapshot is absent from the image |
| `backup-manifest-too-large` | The manifest exceeds the bounded read |
| `restore-path-occupied` | Restore destination is not empty |
| `restore-path-invalid` | Restore destination exists and is not a directory |
| `restore-ledger-mismatch` | The restored research ledger differs, or the project has no events in the prefix |
| `demo-path-occupied` | The demonstration root is not empty |
| `demo-path-invalid` | The demonstration root exists and is not a directory |
| `restore-event-mismatch` | Restored store differs from the image prefix |
| `restore-object-mismatch` | A restored object differs from its recorded size |
| `control-store-missing` | The workspace control store does not exist |
| `control-store-unreadable` | The control store header could not be read |
| `diagnostic-invalid` | A diagnostic detail could not be rendered (internal invariant) |

No message contains a host path, a document body, or a credential.
