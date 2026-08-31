# ArtifactObjectReport v0alpha1

> Status: Experimental machine-readable output
>
> JSON Schema: `schemas/artifact-object-report/v0alpha1.schema.json`

`researchos artifacts put` and `researchos artifacts verify` emit one versioned report after a
successful local object operation.

| Field | Meaning |
|---|---|
| `apiVersion` | Exactly `researchos.dev/v0alpha1` |
| `kind` | Exactly `ArtifactObjectReport` |
| `operation` | Exactly `put` or `verify` |
| `digest` | Raw-byte address, `sha256:` plus 64 lowercase hexadecimal characters |
| `sizeBytes` | Non-negative number of bytes read from the object |
| `storageKey` | Digest-derived relative key `objects/sha256/<2>/<62>` |

The report is closed: unknown fields are invalid. The Python reference implementation also checks
that `storageKey` is the exact deterministic key for `digest`; JSON Schema consumers must perform
that semantic comparison themselves.

Neither the source path nor the artifact-root path appears in the report. `storageKey` is relative
object-store addressing, not a public URI, SQLite identity, project namespace or authorization
claim. `operation: put` means the supplied bytes were fully hashed and atomically published or an
identical existing object was fully verified and reused. `operation: verify` means the stored
object was fully re-hashed during that invocation.

Errors use `ProblemReport` on stderr and do not emit a partial ArtifactObjectReport.

```bash
uv run researchos schema --contract artifact-object-report \
  --check schemas/artifact-object-report/v0alpha1.schema.json
```
