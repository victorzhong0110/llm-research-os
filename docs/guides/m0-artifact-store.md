# M0 Local Artifact Store

## What this slice proves

The local control plane can import ordinary file bytes into an immutable,
content-addressed object directory without loading the whole file into memory,
without trusting caller-supplied object paths, and without treating canonical
JSON digests as file addresses.

It does **not** index artifacts in SQLite, emit ResearchEvents, expose an
artifact CLI, assign media types, or garbage-collect objects.

## Minimal use

```python
from pathlib import Path

from llm_research_os.artifacts import LocalArtifactStore

root = Path("artifacts")
root.mkdir()
store = LocalArtifactStore(root)

source = Path("checkpoint.bin")
record = store.put(source)
assert store.exists(record.digest)
verified = store.verify(record.digest)
with store.open(record.digest) as handle:
    first_page = handle.read(65_536)
```

`record` is frozen and contains:

- `digest`: `sha256:` plus 64 lowercase hexadecimal characters of the **raw
  file bytes**;
- `size_bytes`: the number of bytes copied from the source;
- `storage_key`: `objects/sha256/<ab>/<remaining 62 hex characters>`.

The same bytes imported twice reuse one object. A later `put` of matching
content is idempotent. The store never calls `content_digest()` for artifact
bytes; that helper hashes canonical JSON and is the wrong preimage.

## Addressing and publication

Object paths are derived only after `parse_artifact_digest` accepts the whole
string. Uppercase hex, extra prefix/suffix, path separators and `..` segments
are rejected before any filesystem join.

Publication is:

1. open the source with `O_NOFOLLOW`, then `fstat` the descriptor so a symlink,
   directory, FIFO, socket or device cannot sneak past a pre-check;
2. stream the bytes into a private temporary file under `root/tmp` on the same
   filesystem, hashing each chunk;
3. `fsync` the temporary file;
4. `os.link` it onto the digest path (`link` fails if the destination exists,
   and unlike `rename` it does not replace a dest);
5. if the destination already exists, re-hash it and reuse it only when digest
   and size match; a truncated or substituted object fails closed and is never
   overwritten.

Concurrent importers of the same bytes therefore converge on one complete
object. Callers all receive the same digest.

## Integrity boundary

`verify` re-reads the stored object in chunks and compares the digest. `open`
only checks that the path is a regular file; use `verify` when the bytes will
be trusted. Local SHA-256 detects accidental truncation and bit-rot. It does
**not** defend a host administrator who can rewrite the object file and
recompute the digest. There is no signature, external anchor or keyed MAC in
this slice.

Created `tmp/`, `objects/sha256/<ab>/` directories use owner-only `0700`. New
objects use `0600`. Existing directories are not chmod'd, so their mode is
never widened.

## Operational boundary

- The store root must already be a real local directory, not a symlink or file.
- Keep the object tree on a local filesystem. Cross-device `link` is not a
  supported import path. A checkout-root `artifacts/` directory stays gitignored
  so local object trees are not committed; the library lives at
  `src/llm_research_os/artifacts/`.
- Do not place secrets in artifact bytes if the host is untrusted; the store
  does not encrypt.
- SQLite `artifacts` / `artifact_links` tables, media types, URIs, deletion,
  GC, tombstones and CLI commands remain later slices.

## Residual open questions

- How artifact rows will reference `storage_key` without becoming a second fact
  source.
- Whether `open()` should re-hash large objects by default.
- Project-scoped namespaces (TM-014) before multi-project sharing.
- A later ADR for authenticated or cross-language artifact identity.
