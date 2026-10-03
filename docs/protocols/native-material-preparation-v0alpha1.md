# Remote native material preparation v0alpha1

This R08 slice prepares a Worker-local environment from authenticated remote
material. Preparation does not claim work, consume a grant, import an entrypoint,
install dependencies, spawn a process or append lifecycle facts. The returned
existing R04 preparation receipt keeps `launchAllowed: false` and five zero
side-effect counters. It is not a launch credential or two-host acceptance.

## Material index and download scope

`POST /v0alpha1/native/materials` has the same pinned HTTPS/session/grant,
exactly-one-header, empty JSON body, 4096-byte request and ten-second timeout
requirements as [native request context](native-request-transfer-v0alpha1.md).
The controller reconstructs the full request from recorded authorization, grant
and immutable queue, including the current source revision. Revocation, expiry,
cancellation and terminal claimed leases refuse. The endpoint is available
before claim and creates no facts or lease.

The response is canonical UTF-8 JSON matching
[NativeMaterialIndex](../../schemas/native-material-index/v0alpha1.schema.json),
capped at 65536 bytes, with exact `Content-Length` and the full index JCS digest
in `X-ResearchOS-Material-Index`. It contains the full request and its digest,
recorded grant ID, at most 64 unique role-relative material paths, semantic
digests, raw `byteDigest`, byte sizes and `launchAllowed: false`. Each object is
bounded to the existing R04/CAS 1 MiB preparation limit; aggregate material is
at most 64 MiB. This does not extend native preparation into large-object storage.

Non-code rows must exactly match the request's bundle, named inputs, canonical
execution configuration, interpreter identity document, dependency lock,
inventory and canonical code-review citation. Code rows come only from the
digest-bound bundle's declared members. Configuration and review use semantic
JCS digests and the matching raw SHA-256 of canonical bytes. The Worker checks
closed schema, canonical response bytes, its own identity and both JCS bindings.
Only disconnects or truncated responses retry, at most three times, with bounded
size-plus-one reads and connection closure.

The existing [input endpoint](native-input-transfer-v0alpha1.md) additionally
serves those declared bundle members, interpreter document, review document and
synthetic canonical configuration by exact raw digest and size. It verifies
the bundle and bound documents with size checks before allocation. No arbitrary
CAS listing, unplanned object or inner interpreter executable is exported.
The identity document is data describing the reviewed executable, not executable
bytes or permission to download a controller host program.

## Durable Worker preparation

`workers.native_preparation.prepare_remote_native(client, artifacts=...,
workspace=..., staging_root=...)` uses the Worker's own CAS and private roots.
No controller SQLite database, HMAC key or TLS private key is copied. Workspace,
staging and CAS roots must not overlap. CAS root, CAS/staging parents, workspace parent and staging root must
be owned by the current user and inaccessible to group/other users; directory
walks reject symlink ancestors. Per-workspace private locks serialize publication
and refuse another process holding the same lock.

Verified missing objects download to the Worker CAS. Existing corrupted,
oversized or symlink objects refuse rather than being repaired. The bounded
metadata determines every download's size and digest. Staged files use opaque
SHA-256 path names; native module names such as `__init__.py` and input names
containing `:` do not weaken the legacy transfer path grammar. At most two
batches of 32 objects reuse the existing serialized, durable transfer journals.
Their namespace binds the entire index including grant, request and byte sizes.
Journals are outside CAS and staging object trees, and `starts` remains zero.

An interrupted download records incomplete/unknown transfer state. A later call
with the same index reuses verified files and resumes remaining bytes, with at
most three persisted attempts per batch. This limit is separate from each
HTTPS call's three disconnect retries. A completed batch rechecks the staged
bytes without downloading or consuming new artifact disk. Changed staged bytes
refuse. Disk availability is checked before staging, CAS insertion and workspace
publication. Cached files cannot bypass a fresh live metadata check.

The Worker independently matches all code rows to the downloaded immutable
bundle and checks canonical configuration, review/lock/inventory, actual
installed dependency bytes, CPython version/ABI/platform and actual interpreter
executable bytes using the existing R04 checks. It does not install or import
the reviewed code. Required unsupported isolation refuses. Any checkpoint input
explicitly refuses `transfer-restore-unsupported` until remote verified restore
integration exists; a download is not a verified restore claim.

After host checks, a second live index fetch must still equal the original.
Fresh preparation is written through held directory descriptors into a random
private candidate, synchronized, inspected and atomically renamed into the
workspace. A crash before publication may leave an unreferenced private
candidate, never a ready workspace. Cleanup belongs to the local owner. Matching
completed workspaces are inspected and reused; damaged/incomplete/mismatched
existing workspaces are refused without repair or replacement.

Trusted private parent ownership is required throughout. This is preparation,
not a filesystem sandbox against a malicious process with the same UID. A live
grant checked here can be revoked immediately afterward; an eventual launcher
must separately recheck/consume live authority and retain durable process
identity, source-specification/registry verification and Run/Attempt semantics.
Remote launch/recovery, new authorized two-host/GPU evidence and Checkpoint B
acceptance remain separate work.
