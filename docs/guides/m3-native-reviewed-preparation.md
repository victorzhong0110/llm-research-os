# M3 reviewed native preparation (R04)

Prepare and diagnose a digest-bound workspace for one reviewed Python task.
Normative record:
[Native reviewed preparation v0alpha1](../protocols/native-reviewed-preparation-v0alpha1.md).
Request contract:
[Native reviewed execution v0alpha1](../protocols/native-reviewed-execution-v0alpha1.md).
Constraint record:
[ADR-0065](../adr/0065-reviewed-native-execution-authority.md).

This package does **not** start user code. `researchos native run` remains the
fixed `restricted-v0alpha1` noop. `launchAllowed` stays false on every receipt
and diagnosis. No entrypoint is imported, no child is spawned, no package is
installed, no grant nonce is consumed, and no Run or Attempt fact is appended.

## What preparation checks

`llm_research_os.execution.native_reviewed_preparation` does not trust the
prefix citations, prepared citations, or grant booleans used as R03 fixtures.
Before it writes or accepts a workspace it rebuilds:

1. The cited human `plan.authorization.evaluated` fact for `execute.native`.
2. The existing `rg1` HMAC grant and the Worker grant fold.
3. The CAS bytes for the bundle, code, inputs, interpreter document,
   dependency lock, inventory, and canonical review.

The interpreter identity is that JSON document's byte digest. A mutable
executable path is rejected. The host platform, machine, CPython version, and
implementation must match the document or preparation refuses
`environment-identity-mismatch`. The lock and inventory pin lists must match
and are not installed.

## Workspace behavior

An empty workspace is fresh and can be prepared. A second prepare of the same
bytes is a no-op. A workspace that already holds a different receipt, a
partial tree, a damaged receipt, or an extra file is diagnosed and left in
place. Preparation does not repair it.

`check_before_user_code` repeats that check. Replacing code, configuration,
inputs, or a required environment identity invalidates the old binding before
any later package could start user code. This package returns at that check.

## Commands

```bash
uv run researchos native prepare REQUEST DATABASE ARTIFACTS WORKSPACE \
  --grant-token-file TOKEN --hmac-key-file KEY --format json
uv run researchos native doctor REQUEST DATABASE ARTIFACTS WORKSPACE \
  --grant-token-file TOKEN --hmac-key-file KEY --format json
```

Exit 0 means the receipt outcome is `prepared` or the diagnosis outcome is
`ready`. Both still report `launchAllowed: false`. Any other outcome exits 1.
The HMAC key file is exactly 32 bytes and is not copied into the receipt.

## Examples

The first fixture is a CPU Python brick. It is materialized as bytes. Tests
do not import it.

- `examples/native-reviewed-preparation/brick/task.py`
- `examples/native-reviewed-preparation/valid/`
- `examples/native-reviewed-preparation/invalid/`

The Linux receipt and diagnosis under `valid/` are internally consistent
document fixtures. Their interpreter digest is not a live host measurement.
Live preparation builds the interpreter document from the process that runs
the check, then hashes those bytes.

Schemas are generated from the Pydantic models and registered as
`native-reviewed-preparation-receipt`,
`native-reviewed-preparation-diagnosis`,
`native-reviewed-python-bundle`,
`native-reviewed-code-review`,
`native-reviewed-interpreter-identity`,
`native-reviewed-dependency-lock`, and
`native-reviewed-dependency-inventory`.
Do not edit the JSON Schema files by hand.

## Limits

No GPU, training extra, implicit install, or cloud resource is required.
Network, filesystem, and memory isolation remain unenforced, as in R03.
Issue #53 stays open. Real entrypoint execution remains R05.
