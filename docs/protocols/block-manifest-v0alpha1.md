# BlockManifest v0alpha1

> Status: Experimental external contract
> API version: `researchos.dev/v0alpha1`
> JSON Schema: `schemas/block-manifest/v0alpha1.schema.json`

BlockManifest declares what a workflow block claims to accept, produce and require. It is
inert data. Loading, registering, listing or resolving a manifest does **not** import its
entrypoint or grant any capability.

## 1. Exact identity

Every manifest has a globally meaningful `metadata.id` and semantic `metadata.version`.
The M0 registry resolves only the exact pair. Duplicate pairs fail closed; registration
order never selects a winner and callers cannot replace an entry in a sealed registry.

The registry and each manifest receive reference content digests. A dry-run plan records the
exact version and digest it resolved. Paths, timestamps and host information do not
participate. The current digest convention is Python-reference-only and is specified in
[Reference Content Digests v0alpha1](digest-v0alpha1.md).

## 2. Runtime declaration

The declared runtime type is one of:

- `simulated`;
- `python`;
- `container`;
- `remote-service`;
- `composite`.

Python, container and remote-service declarations require an `entrypoint`. Simulated and
composite declarations prohibit one in v0alpha1. This is only structural information:
the M0 dry-run never imports, opens, connects to or executes the entrypoint.

## 3. Ports and configuration

Inputs and outputs have unique IDs and declared value types. A required input must be
connected before a plan can be ready. The M0 planner permits exact type equality or an
explicit `researchos.any` endpoint; it never guesses conversions.

`configSchema` uses a bounded, offline subset of Draft 2020-12 whose root describes an
object. M0 allows ordinary object/array/type, enum/const, length/count and numeric-bound
keywords. It rejects references, regex, combinators, conditionals, `uniqueItems` and other
keywords whose evaluation may retrieve data or grow unpredictably. Schema nesting is capped
at 32 levels and 4096 nodes; each task config is capped at 256 KiB, 32 levels and 16,384
nodes. Task configuration diagnostics identify the failed rule without echoing rejected
values or dynamic object keys.

## 4. Capabilities and permissions

`capabilities` and `permissions` are declarations, not grants. Dry-run records them with
`authorization: not-evaluated`. A later policy engine must decide what is allowed before
any runtime handler can run. A manifest cannot override ResearchSpec invariants, approval
rules, budgets or audit requirements.

## 5. Registry loading boundary

M0 includes one T0 declaration, `simulated.experiment@0.1.0`. Additional manifests may be
loaded only from explicitly supplied regular YAML or JSON files or one non-recursive
directory. Symbolic links are rejected. There is no Python entry-point discovery, package
installation, callback registration or plugin execution in this slice.

Manifest bytes are read from the same non-following file descriptor that is checked for
regular-file type and size, preventing a path swap between inspection and reading.

Each manifest file is capped at 1 MiB. An explicit registry is capped at 1,024 manifests,
64 MiB aggregate input and 4,096 scanned entries per supplied directory. The shared strict
document loader rejects duplicate mapping keys, YAML aliases and invalid Unicode scalars.

## 6. Conformance commands

```bash
uv run researchos blocks list --format json
uv run researchos blocks validate examples/manifests/example-train.yaml --format json
uv run researchos schema --contract block-manifest \
  --check schemas/block-manifest/v0alpha1.schema.json
```

The versioned output envelope is defined by
[Block Command Reports v0alpha1](block-command-report-v0alpha1.md).
