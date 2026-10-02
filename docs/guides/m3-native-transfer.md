# M3 scoped native transfer (R08 candidate)

`researchos native transfer` copies files named by a local manifest.
The manifest is the allow-list: path, digest, and size. The command never
lists a CAS and never follows a symlink. A completed journal for the same
lease is a replay of that transfer, not a second task start.

This does not accept a two-host run. No second machine is contacted.
`gpu-oci` and `macos-mps` remain `pending-live`. A local copy is not remote
evidence. The local helper does not enforce Worker grants. A separate pinned
HTTPS input API checks real grants against the immutable planned execution;
a separate output API returns a scoped Worker completion receipt. Distributed
execution/recovery remain R08 work, distinct from
missing real-host acceptance. `grantId` is a correlation reference supplied
by the trusted local caller, not a checked launch credential. Do not expose
this command or its CAS path to a remote Worker or browser.

See [the local transfer protocol](../protocols/m3-native-transfer.md) and
TM-068 in the [threat model](../security/threat-model.md).

## Manifest

```json
{
  "grantId": "grant.1",
  "taskId": "task.1",
  "runId": "run.1",
  "attemptId": "attempt.1",
  "direction": "input",
  "files": [
    {"path": "inputs/corpus", "digest": "sha256:HEX", "sizeBytes": 4}
  ]
}
```

`direction` is `input` for `stage` and `output` for `export`. At most 32
files and 256 MiB are accepted. Paths stay inside the destination; `..`,
absolute paths, and symlinks are refused.

## Stage and export

```bash
researchos native transfer stage manifest.json cas/ stage/ \
  --journal journal.json --lease-id lease.1 --format json
researchos native transfer export manifest.json output/ cas/ \
  --journal journal.json --lease-id lease.1 --format json
```

Exit `0` means the named files were copied. The receipt `observation` stays
`unknown` until a separate process observation is recorded. Exit `1` means
the journal is still incomplete. Exit `2` is a local refusal: bad path,
digest mismatch, exhausted retries, or an unsupported checkpoint restore.

An interrupted copy resumes the remaining files under the same lease. Three
attempts is the bound. A changed file after a recorded digest is rejected.
Keep the journal outside both artifact trees; it must never overwrite an input
or CAS object. A verified completed replay requires no additional artifact disk.
Files publish atomically after all bytes and their digest are verified. Journal
updates are serialized, private, bounded, and synchronized to disk. A path
replacement cannot redirect the held directory descriptors. An input crash
before publication can leave a private `.transfer-*` file in the local
staging tree; it is not a completed artifact. Cleanup belongs to the owner of
that private staging tree, never to a remote caller.

## Pinned HTTPS input API

`WorkerClient.fetch_native_input(digest=..., size_bytes=...)` downloads one
planned native input, code bundle, dependency lock, or inventory. It requires
an HTTPS origin, CA and certificate fingerprint. Each request supplies a
Worker session and grant; the controller checks the recorded, unexpired,
unrevoked grant and its task/Run/Attempt/execution binding. If work was already
claimed, its lease must still be live. Cancellation refuses further fetches.
The call never polls, consumes a grant, starts a process, or appends facts.

The client retries disconnects at most three times, checks the declared byte
count and SHA-256 before returning bytes, and does not retry refusals or
integrity failures. Returned bytes may be inserted into the worker's private
CAS and passed through local staging. This API does not treat a local manifest's
`grantId` as authorization and does not create a launch receipt.

See [the HTTPS input protocol](../protocols/native-input-transfer-v0alpha1.md).
`researchos native transfer classify disconnected-cancel` prints
`cancel-requested` and does not start work. The other classified faults
print `unknown`. None of them is success, failure, or stopped.

Checkpoint bytes are delivered only after the existing restore claim matches
the completed source Attempt and the new Attempt. Anything else is
`transfer-restore-unsupported`.

## Pinned HTTPS output API

`WorkerClient.upload_native_output(lease_id=..., payload=...)` uploads one
canonical `NativeReviewedTaskOutput` envelope for an already consumed native
claim. Its task/Run/Attempt must match the lease. The same pinned HTTPS origin,
session and grant are required. The bound is the smaller of reviewed
`artifactBytes` and 256 MiB. Use the exact canonical bytes produced by the task
result path, not a pretty-printed JSON document.

The controller verifies the complete object, rechecks authorization after disk
I/O, and appends a single Worker completion. Repeating the same upload after
response loss or controller restart returns the same fact and sequence, even
when authority has since expired or been revoked. Such replay requires the
already completed lease and the original intact CAS bytes; it cannot repair a
missing object, change a result or start work. Refusals never retry; disconnects
and truncated receipts retry at most three times. Native Workers must use this
endpoint rather than legacy artifact upload/generic HTTP completion.

This is a durable Worker result receipt, not Run success or a fresh process
observation. The transport verifies the syntax of the reported `requestDigest`;
it does not reconstruct the full closed request. Run integration must verify
that citation and the process result separately. Durable remote staging, remote
launch/recovery integration and new real two-host fault acceptance remain open.
See [the output protocol](../protocols/native-output-transfer-v0alpha1.md) and TM-070.
