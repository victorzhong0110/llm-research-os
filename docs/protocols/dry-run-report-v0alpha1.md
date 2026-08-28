# DryRunReport v0alpha1

> Status: Experimental machine-readable output
> JSON Schema: `schemas/dry-run-report/v0alpha1.schema.json`

`researchos dry-run` is a pure static compiler. It verifies exact block resolution,
configuration schemas, ports, graph ordering, resource declarations and planning limits.
It produces either `ready` or `blocked`; neither value means that an experiment succeeded,
was scientifically sound, was approved or was executed.

## Deterministic plan

- Independent nodes are grouped into topological stages and ordered lexically by node ID.
- Every control edge and data binding is retained with canonical source/target paths; data
  bindings also retain both ports and both declared value types.
- Loops remain symbolic and are never expanded by `maxIterations`.
- `until` remains inert; the report records only its digest and `evaluated: false`.
- Task configuration and approval prompts are represented by digests, not echoed values.
- The plan binds the ResearchSpec identity, exact BlockManifest versions and manifest
  digests, resource provider/model and declared bounds, while omitting clocks, UUIDs, file
  paths and host information.
- `specDigest` identifies the exact normalized specification. `planDigest` identifies the
  normalized semantic plan, so meaningless node-list reordering does not change it.

The current content-digest encoding is a Python reference convention, not yet a
cross-language canonicalization standard. `planDigest` also deliberately omits `specDigest`.
Consumers MUST bind `specDigest`, `registryDigest` and `planDigest` together for cache,
approval or future execution identity. See
[Reference Content Digests v0alpha1](digest-v0alpha1.md).

## Validation layers

The committed JSON Schema validates report structure, digest shape and ready/blocked field
presence. A conforming semantic validator must additionally verify that:

- outer project, workflow, spec and registry identities match the embedded plan;
- a ready summary equals the recursively counted tasks, approvals, loops and stages;
- `planDigest` matches the embedded semantic plan projection;
- a blocked report contains no plan and has at least one error diagnostic.
- a blocked report has `summary.basis: source` and zero planned stages.

JSON Schema cannot express those cross-field equality and hashing rules. Passing structural
Schema validation alone is therefore not proof that a report is authentic or internally
consistent. The Python model enforces them and tests include tampered-report negatives.

For blocked reports, counts describe source nodes rather than a partial plan. Counting is
bounded by the planner node limit and `summary.truncated` is set when that limit is reached.

## Side-effect guarantee

Every report contains four zero counters:

```json
{
  "blocksExecuted": 0,
  "networkRequests": 0,
  "persistentWrites": 0,
  "paidActions": 0
}
```

Dry-run does not import block entrypoints, evaluate expressions, inspect accelerators,
expand environment variables, access runtime paths, connect to services, reserve hardware,
write events or create artifacts.

## Exit status

| Code | Meaning |
|---:|---|
| `0` | A complete static plan is `ready` |
| `1` | A valid request is `blocked`, for example by an unknown block or invalid config |
| `2` | The CLI, ResearchSpec or registry input is invalid or unreadable |

## Conformance command

```bash
uv run researchos dry-run examples/valid/minimal.yaml --format json
uv run researchos schema --contract dry-run-report \
  --check schemas/dry-run-report/v0alpha1.schema.json
```

Invalid inputs are emitted separately as a versioned
[ProblemReport](problem-report-v0alpha1.md); no partial plan is returned.
