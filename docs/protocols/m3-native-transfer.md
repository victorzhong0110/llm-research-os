# Local manifest-scoped transfer records

Status: R08 local implementation slice; remote integration is not implemented.
These are local CLI records, not a Worker wire protocol or launch credentials.
The canonical package scope remains the R08 definition in the M3 plan.

The manifest binds correlation identifiers `grantId`, `taskId`, `runId`,
`attemptId`, direction (`input` or `output`), and 1–32 explicitly named files.
Each file names a relative path, tagged SHA-256 digest, and exact byte size.
Total and per-file byte limits are 256 MiB. The manifest document is bounded
to 64 KiB; FIFOs, symlinks, traversal and special files are refused.

The receipt names the implementation, host runtime, canonical manifest digest,
correlation identifiers, optional lease reference, completed files and retry
count. `status=complete` describes the transfer only. Its observation starts
as `unknown`; a supplied process identity is identity metadata, not a fresh
operating-system observation. Fault classification and `starts` are local
bookkeeping, not proof of real disconnect/restart recovery or exactly-once
remote execution. No command here consumes or validates a Worker launch grant.

For a single journal, competing claims cannot replace a recorded lease;
three file-transfer attempts are allowed. Every retry re-verifies completed
bytes. File publication uses exclusive private staging and a no-overwrite
atomic link after full write and fsync. The journal is locked across its
read/modify/publish transaction and uses private exclusive temporary files,
atomic replacement and directory fsync. Reads and writes traverse no-follow
directory descriptors, including the journal parent held by the lock.

The caller owns the local CAS, staging tree, and journal parent. Other actors
must not be allowed to delete the journal or its lock file. The local caller
is trusted to choose these paths and the correlation references. A new
authenticated remote transfer protocol must independently enforce grant/task
bindings before using these helpers. Checkpoint B and GPU acceptance remain
unaccepted; code integration does not substitute for their evidence.

Examples: see the [guide](../guides/m3-native-transfer.md) and the positive and
negative fixtures in `tests/test_native_transfer.py` and
`tests/test_native_transfer_security.py`. A file path `../secret` is invalid;
`inputs/corpus` with its exact tagged digest and byte size is valid.
