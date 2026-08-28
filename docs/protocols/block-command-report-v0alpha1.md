# Block Command Reports v0alpha1

> Status: Experimental machine-readable output
> JSON Schema: `schemas/block-command-report/v0alpha1.schema.json`

`researchos blocks list`, `show` and `validate` emit versioned JSON when `--format json` is
selected.

- `BlockRegistryReport` with `operation: list` contains exact ID/version summaries and the
  complete sealed-registry digest. Entries are sorted and do not embed manifests.
- `BlockRegistryReport` with `operation: show` contains exactly one entry and its complete
  normalized manifest. Source filesystem paths are never included.
- `BlockManifestValidationReport` records a successful manifest identity and digest.

The Python report model stores a show manifest as an immutable canonical snapshot and returns
a fresh object to callers. Mutating a returned copy cannot change later serialization or
invalidate the recorded summary. Structural Schema validation cannot prove that a digest is
truthful; a semantic consumer must recompute it under the reference digest convention.

Invalid inputs use the separate `ProblemReport` contract on stderr.

```bash
uv run researchos blocks list --format json
uv run researchos blocks show simulated.experiment --version 0.1.0 --format json
uv run researchos schema --contract block-command-report \
  --check schemas/block-command-report/v0alpha1.schema.json
```
