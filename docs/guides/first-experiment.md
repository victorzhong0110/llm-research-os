# First experiment (release candidate path)

Issue #38 stays open. There is no `v0.1.0-m1` tag. This is a clean local
install plus two prove commands: offline M1 research chain (no GPU mock) and
M2-0 loopback Worker CPU loop.

SQLite schema remains **v2**. Opening an existing v2 store does not migrate.

## Install

```bash
uv sync
uv run researchos --help
```

## M1 corpus (no network, no GPU)

```bash
uv run researchos m1 prove \
  examples/m1-checkpoint \
  research-m1.db \
  --format json
```

Reject without a Run: add `--decision reject`. This command does not close
Issue #38.

## M2-0 CPU Worker

```bash
uv run researchos m2 prove \
  examples/m2-checkpoint \
  research-m2.db \
  --format json
```

The Markdown report cites `eventId` values. Lineage includes
`work.completed` (artifact digest) and the Run/Attempt facts. Stop/resume
for this slice: replay the same database; do not treat a cancel request as
stopped. A resumed claim MUST NOT re-run unknown work. Sandbox timeout or a
killed sandbox process is `unknown`, not `failed`. Disconnect before
complete leaves the lease open (not success). Heartbeats do not grow the
event log. Completed work reconciles Run/Attempt; a CAS object without
`work.completed` is not success. CPU checkpoint JSON is inspectable
(`examples/m2-checkpoint-resume/`). Host Python is not a kernel sandbox.

CPU OCI (`researchos m2 oci`) fails closed without a live digest-pinned
image. That failure is not a mocked container success. See
[M2 CPU OCI](m2-oci.md).

## What is still not a release

- Paid GPU / cloud provisioner
- NativeProcessRuntime (preflight still forbids launch)
- Charter v0.2
- Editable canvas, plugins, parameter self-evolution
