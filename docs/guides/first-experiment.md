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
stopped. A resumed claim MUST NOT re-run unknown work. `cancel-observed`
requires a confirmed process or container exit; missing identity stays
`execution-unobserved` (ADR-0050). Sandbox timeout or a
killed sandbox process is `unknown`, not `failed`. Disconnect after
upload retries `work.completed` from a pending receipt and MUST NOT
re-run (ADR-0051). A second Worker client MUST NOT spawn while the
original executor is still running. Disconnect before
complete leaves the lease open (not success). Heartbeats do not grow the
event log. Completed work reconciles Run/Attempt; a CAS object without
`work.completed` is not success. CPU checkpoint JSON is inspectable
(`examples/m2-checkpoint-resume/`). Host Python is not a kernel sandbox.

CPU OCI (`researchos m2 oci`) fails closed without a live digest-pinned
image. That failure is not a mocked container success. See
[M2 CPU OCI](m2-oci.md). A remote Worker pack is pending-live and is
**not** a cross-machine proof; see [M2 remote Worker](m2-remote-worker.md).

## Usage evidence (not EventStore fill)

`researchos m2 bench` is a storage fill. Worker/RunControl append, claim,
cancel, and coordinate, plus an isolated Worker and cited report:

```bash
uv run researchos m2 usage /tmp/m2-usage --format json
```

See [M2 usage](m2-usage.md). OCI may be `skipped-no-runtime` or
`skipped-no-image` here; designated Linux OCI CI must not skip.

## Performance baseline (not SLA)

```bash
uv run researchos m2 bench research-bench-10k.db \
  --events 10000 --format json
```

`--events 100000` is the larger reproducible size. Receipts are host
measurements. See [M2 performance baseline](m2-perf.md).

After prove, the static report cites spec, runtime, image, config, and
output artifact:

```bash
uv run researchos report run.worker.cpu \
  --database research-m2.db \
  --format markdown
```

Pinned training-backend parse (no GPU):

```bash
uv run researchos training plan \
  examples/training-backend/valid/ms-swift-sft.json \
  --format json
```

See [M2 GPU experiment](m2-gpu-experiment.md). That command is not a
training run.

## What is still not a release

- Paid GPU / cloud provisioner
- NativeProcessRuntime (preflight still forbids launch)
- Charter v0.2
- Editable canvas, plugins, parameter self-evolution
