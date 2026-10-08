# Receipt-aware backup and restore v0alpha2

Status: R13 engineering continuation. The original
[EventStore-prefix v0alpha1 contract](backup-restore-v0alpha1.md) remains readable
and its published schema stays unchanged. Images without an operation log use
v0alpha1; images with an operation log use the explicit v0alpha2 manifest.

## Captured state

The unit is a verified EventStore prefix plus an inert snapshot of the
workspace's append-only command receipts and dispatch reservations. Read both
operation tables in one SQLite read transaction **before** taking the EventStore
online backup. Every captured receipt must have an observed head no greater than
the resulting prefix; cited facts must exist and belong to that project (or be
project-neutral Worker facts). Concurrent later commands need not be captured.

The manifest adds `operationsSnapshotDigest`, `operationsSnapshotBytes`,
`operationsReceiptCount`, and `operationsIntentCount`. The fixed image file
`operations.json` follows the registered `operations-backup` contract. It is
bounded to 64 MiB, 100,000 receipts and 100,000 reservations; individual source
receipts are bounded to 4 MiB. No launch profile, private key, process handle,
provider credential, or Worker directory is copied.

The object set is re-derived from **both** the verified events and validated
receipts. Receipt-backed roots include collected baseline/candidate details,
their request/output/source provenance, comparison artifacts, and immutable human
reports with their embedded comparison lineage. A semantic JCS identity is not
mistaken for a byte-addressed CAS object. Every copied object retains its actual
byte digest, size and derived path. Dropping a receipt-backed manifest entry
fails verification just as dropping an event-backed entry does.

## Verification and restore

Validate the operation snapshot's byte hash, length, schema, counts, unique
identities, result digests, project scope and fact links. A report's project,
comparison identity, recorded human actor and byte object identity must agree.
An altered snapshot cannot be repaired merely by rehashing its manifest.

Restore rechecks the operation snapshot after the EventStore and CAS have been
copied, then rebuilds the receipt log through its append-only APIs. It executes
no command and appends no event. A prior dispatch reservation remains reserved,
including one whose outcome has no receipt. Restoration grants no execution
authority and does not retry unknown work. Existing non-terminal Runs retain
the observation-only reconciliation policy.

A restored workspace can list and inspect its recorded human reports and
recompute its trained details from preserved request/output CAS and EventStore
lineage. Profiles and credentials must be installed separately by an authorized
operator; restoring historical records is not a launch credential.

The two databases do not form a distributed transaction: this is a bounded
receipt snapshot followed by a verified later event prefix, not a claim of an
atomic backup of arbitrary external provider/process state. Backups are integrity
checks over supplied bytes, not signatures or proof of a human's identity.
