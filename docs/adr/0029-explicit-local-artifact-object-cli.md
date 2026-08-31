# ADR-0029: Explicit Local Artifact Object CLI

- Status: Proposed
- Date: 2026-08-31

## Context

`LocalArtifactStore` already provides a hardened Python boundary for immutable raw-byte objects,
but M0 users cannot exercise it without writing Python. A convenience CLI must not weaken the
existing root identity, dirfd, no-follow, atomic-link or fsync guarantees. It must also avoid
turning an object path into a public URI, inventing mutable metadata, streaming arbitrary bytes to
the terminal, or implying that an object has been indexed or linked to a Run.

## Decision

Add two local commands:

```text
researchos artifacts put ROOT SOURCE
researchos artifacts verify ROOT DIGEST
```

- `ROOT` must already be a real local directory. The command does not create it, follow a root
  symlink, or widen existing permissions.
- `put` delegates exactly one ordinary-file import to `LocalArtifactStore.put`. It streams and
  hashes raw bytes, atomically publishes by digest, and preserves the store's idempotent concurrent
  behavior.
- `verify` accepts only `sha256:<64 lowercase hex>`, derives the object path internally and
  re-hashes the complete stored object. It never repairs or replaces corruption.
- Successful JSON output is exactly `ArtifactObjectReport v0alpha1`: operation, digest, byte size
  and relative storage key. Caller source and root paths are omitted.
- Text output contains the same object identity and states `integrity verified: true`. Terminal
  control characters in errors are escaped by the shared ProblemReport renderer.
- Exit `0` means the requested import or verification succeeded. A well-formed digest with no
  object returns `1`; invalid input, unsafe paths, I/O failure or integrity failure returns `2`.

The commands do not read object bytes to stdout, create SQLite rows, emit ResearchEvents, assign
media types or URIs, link an object to a project/Run, delete data, garbage-collect, upload, execute
or contact a network service.

## Consequences

- The existing local object layer becomes usable and scriptable without duplicating its security
  implementation in the CLI.
- The versioned report is a statement about one object operation, not an artifact metadata record
  or evidence of Run provenance.
- SQLite `artifacts` / `artifact_links`, media type, project namespace, lifecycle, deletion and
  event semantics remain open and require later contracts.

## Validation

Tests cover Schema/report agreement, strict operation/digest/storage-key/size fields, successful
put and verify, idempotent import, missing roots and objects, source symlink rejection, traversal
digest rejection, corruption detection without repair, caller-path omission and terminal-safe
errors. The existing artifact-store suite continues to cover bounded streaming, concurrency,
dirfd anchoring and durability recovery.

## References

- [M0 Local Artifact Store](../guides/m0-artifact-store.md)
- [ArtifactObjectReport v0alpha1](../protocols/artifact-object-report-v0alpha1.md)
- [ADR-0015 SQLite Event Source, Projections, and Artifacts](0015-sqlite-event-source-projections-and-artifacts.md)
