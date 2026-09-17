# M3 native process runtime (slices 1–2)

Local restricted execution over a sealed preflight. Protocols:
[NativeProcessRuntime v0alpha1](../protocols/native-process-runtime-v0alpha1.md)
(slice 1) and
[NativeProcessRuntime v0alpha2](../protocols/native-process-runtime-v0alpha2.md)
(slice 2 profiles and pinning). Constraint records:
[ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md) and
[ADR-0064](../adr/0064-m3-native-runtime-slice-2.md).

This path does **not** close Issue #53, does not execute the manifest
entrypoint, does not dial SSH, does not spend paid cloud, and does not start
a public service.

## One-command local run

The database must already exist and already hold the cited authorization fact.
The record command refuses to create a database, so initialize an empty
EventStore first, then record, then run:

```bash
python -c 'from llm_research_os.storage import EventStore
with EventStore("native.db"):
    pass'
```

Record the authorized evaluation for the native example plan. The event
request below repeats the recomputed spec/registry/plan/decision digests from
`researchos authorize` on the same inputs; its `projectId` is
`example-native-process-preflight`, `experimentRevision` is `1`, and its
`workflowId` is `workflow.native`. The command fails closed on any stale
digest:

```bash
uv run researchos authorizations record \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  /tmp/native-auth-event.json \
  native.db \
  --registry examples/native-process-preflight/manifest.yaml \
  --format json
```

Consume that fact and run the fixed helper:

```bash
uv run researchos native run \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  native.db \
  --registry examples/native-process-preflight/manifest.yaml \
  --authorization-event-id evt.auth.native.1 \
  --authorization-sequence 1 \
  --format json
```

Exit `0` is a `succeeded` helper run (`native.process.ok`). Exit `1` is a
`failed`/`unknown` helper outcome with its stable `reasonCode`. Exit `2` is
an input, binding, authorization, transport, or store error and prints no
receipt. The receipt always says `entrypointExecuted: false`,
`isolation: process-group`, and `networkEnforcement: not-enforced`.

SSH transport is validated past authorization and then refused:

```bash
uv run researchos native run ... --transport ssh --format json
# exit 2, code ssh-transport-not-implemented, no process spawned
```

## What is enforced

- Sealed preflight plus in-process `authorized` plus this-store human
  `{eventId, sequence}` consume before spawn; stale or swapped citations
  spawn nothing.
- Fixed helper argv, `shell=false`, empty environment allowlist, isolated
  temporary cwd, preflight wall/output caps while pipes are read, and
  process-group reap with a caller-group guard.
- Tristate outcome mapping: timeout/lost stay `unknown`; cancel is
  `cancel-observed` only after the group is reaped.

## Slice 2: pinned identity and a second profile

`--profile restricted-v0alpha2` keeps every slice-1 bound and additionally
digests the resolved interpreter binary and the exact spawn environment
before `Popen`, then re-resolves the interpreter immediately before spawn
and refuses with `native-interpreter-changed` on any drift. The receipt
carries `interpreterDigest`, `environmentDigest`, and
`interpreterPinned: true` (v0alpha1 reports the same digests with
`interpreterPinned: false`: recorded, not pinned).

```bash
uv run researchos native run \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  native.db \
  --registry examples/native-process-preflight/manifest.yaml \
  --authorization-event-id evt.auth.native.1 \
  --authorization-sequence 1 \
  --profile restricted-v0alpha2 \
  --format json
```

Pinning detects substitution; it is not a sandbox. Entrypoint execution,
network enforcement, and namespaces/cgroups/seccomp stay non-goals for both
profiles (see the v0alpha2 protocol).

## What is not claimed

The manifest entrypoint is never imported. Network denial is requested, not
enforced. The interpreter is the host `sys.executable` recorded by version,
not pinned. No lifecycle fact is appended, no artifact is collected, and no
cloud, Web, or plugin boundary is provided.
