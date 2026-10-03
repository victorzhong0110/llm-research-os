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
planned native input, code bundle/member, dependency lock, inventory, bound
interpreter identity/review document, or canonical execution configuration. It requires
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
observation. The controller reconstructs the full closed request from recorded facts and
requires `requestDigest` to match. Run integration must still verify the actual
process result and original specification/registry execution binding. Durable remote staging, remote
launch/recovery integration and new real two-host fault acceptance remain open.
See [the output protocol](../protocols/native-output-transfer-v0alpha1.md) and TM-070.

## Bound request context

`WorkerClient.fetch_native_request()` returns the closed reviewed request derived
from the existing human authorization fact, recorded grant and immutable queued
execution. It requires the same live scoped HTTPS authority as inputs and is
available before claim. Repeating it changes no facts, consumes no grant and
starts no process. The result's Worker identity, canonical bytes and JCS digest
are checked. A completed, expired, revoked or cancelled claim refuses this live
context fetch. It is context for material preparation, not a launch receipt.

Output verification rebuilds that same request independently; a digest for a
different full request refuses. No controller database/HMAC key is distributed.
See [the request context protocol](../protocols/native-request-transfer-v0alpha1.md).
Remote execution/recovery integration and new authorized two-host proof remain open.

## Worker-local remote preparation API

Create a private Worker parent (mode `0700`), a CAS directory under it, and keep
the staging root, workspace and CAS separate. Supply the existing pinned
`WorkerClient` session/grant and call:

```python
from llm_research_os.workers.native_preparation import prepare_remote_native

receipt = prepare_remote_native(
    client,
    artifacts=worker_cas,
    workspace=worker_root / "workspace",
    staging_root=worker_root / "staging",
)
```

The helper fetches authenticated material metadata and stages at most 64 objects
of at most 1 MiB each in persistent batches. After an interrupted transfer,
repeat this call with the same private directories/client scope; it resumes
verified remaining bytes without polling or starting anything. Three persisted
attempts per batch is the bound. A completed workspace is inspected and reused;
a corrupted cache, stage or workspace is refused without repair. Partial
private publication candidates remain owner-managed scratch after a crash.

Actual Worker interpreter and installed dependencies must match the reviewed
bytes. Dependencies are not installed automatically. Remote checkpoint inputs
and required unsupported isolation refuse. `receipt.launch_allowed` stays
false. Keep database, HMAC key and controller TLS private key on the controller.
The helper checks live authority again after material and host checks; eventual
execution must independently recheck/consume authority and preserve process
identity. See [the preparation protocol](../protocols/native-material-preparation-v0alpha1.md)
and TM-072. This slice does not close Checkpoint B.

## Controller-side remote claim binding

After remote preparation, the native poll boundary requires trusted controller
spec/registry inputs. Configure the Python server explicitly:

```python
from llm_research_os.workers.native_claim import NativeControllerContext

server = LoopbackWorkerServer(
    database,
    controller_artifacts,
    hmac_key=controller_hmac_key,
    project_id=spec.metadata.id,
    source=project_source,
    experiment_revision=spec.metadata.revision,
    tls=controller_tls,
    native_context=NativeControllerContext(spec, registry),
)
```

These objects come from the controller's reviewed project and registry, never
from a Worker poll body. The omitted context refuses native dispatch. The
existing `WorkerClient.poll()` body uses integer `waitSeconds: 0`; a successful
claim queues one Run/Attempt and consumes the recorded grant without starting a
process. A retry/restart that finds an existing lease returns `resumed: true`;
it is observation/recovery context, never permission to launch again. See
[the claim protocol](../protocols/native-remote-claim-v0alpha1.md) and TM-073.
The remote executor and process-recovery integration remain unfinished.

Track live evidence separately: (1) two-host CPU native transport/execution and
faults, (2) availability and actual execution of an already supported GPU profile,
and (3) that GPU profile over the remote chain. Kaggle is a candidate GPU resource
until its environment has been probed; a GPU notebook alone cannot certify
remote fault recovery or current Worker runtime compatibility. These dimensions
do not reduce the existing Checkpoint B requirements.
