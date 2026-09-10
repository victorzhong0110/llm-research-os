# M2 WSL2 CUDA live evidence (not M2 close)

Issue [#38](https://github.com/victorzhong0110/llm-research-os/issues/38)
stays open. PR [#73](https://github.com/victorzhong0110/llm-research-os/pull/73)
is the code slice. This directory is the reviewable evidence pack. The
local Cursor canvas is display only.

Platform claim, when a row is live, is **Windows/WSL2 + Docker Engine**.
Not native Linux, not cloud GPU.

## Proven (EventStore + tests)

| Item | Evidence |
| --- | --- |
| EventStore 142 events; cuda.7 `run.completed` unchanged | [eventstore-redacted.json](eventstore-redacted.json) (seq 1–118 freeze) + [eventstore-redacted-cuda8-9.json](eventstore-redacted-cuda8-9.json) |
| CPU OCI two-host `grant.wsl.oci.1` completed seq 12–14 | seq 1–118 excerpt |
| Reconnect `grant.wsl.reconnect.1` completed seq 41–43 | same |
| Cancel `grant.wsl.cancel.1` `cancel-observed` seq 48–50 | same |
| CUDA 20-step `grant.wsl.cuda.7` completed seq 116–118 | [cuda7-WslCudaTrainingReport.json](cuda7-WslCudaTrainingReport.json) |
| cuda.1 revoked; cuda.2–6 consumed-failed; cuda.8 failed | [cuda-grants.md](cuda-grants.md) |
| Checkpoint-20 SHA256 on the Worker host | [cuda7-frozen-inventory.json](cuda7-frozen-inventory.json) |
| `POST /v0alpha1/artifacts` of adapter + restore state (22 files, 106 422 278 bytes) | [upload-cuda7.json](upload-cuda7.json), [collect-cuda7.receipt.json](collect-cuda7.receipt.json) |
| Control-plane retrieve of those bytes | [retrieve-proof.json](retrieve-proof.json) |
| Authorized restore checkpoint-10 → 20 | `grant.wsl.cuda.9` seq 140–142; historical [cuda9-WslCudaTrainingReport.json](cuda9-WslCudaTrainingReport.json); honest reading [cuda9-report-correction.md](cuda9-report-correction.md) |
| cuda.9 leftover vs this-run checkpoint-20 | [cuda9-host-observation-supplement.json](cuda9-host-observation-supplement.json): checkpoint-20 mtime is new; adapter SHA matches cuda.7 frozen checkpoint-20 (deterministic) |
| `requestedLoads` ≠ `observedLoads`; leftovers do not count | `tests/test_worker_gpu.py`; [cuda9-report-correction.md](cuda9-report-correction.md) |
| Report file-presence ≠ restore; single checkpoint ≠ `parametersUpdated` | `tests/test_worker_gpu.py` |
| GPU resume overlay is a new `commandDigest` | `tests/test_worker_gpu.py`, [restore-overlay.preflight.json](restore-overlay.preflight.json) |
| Invalid GPU config fails the sandbox (lease can `work.failed`) | `tests/test_worker_gpu.py::test_run_gpu_training_forbidden_config_fails_the_sandbox` |
| `unknown ≠ rerun` (unit / loopback) | [unknown-not-rerun.md](unknown-not-rerun.md) |
| HTTPS serve still listening; proxy caused the TLS timeout | [https-locate.md](https-locate.md) |

## Corrected cuda.7 report semantics

The original `WslCudaTrainingReport` in CAS is unchanged
(`sha256:9da93e29…ea76`, seq 116). Read it with
[cuda7-report-correction.md](cuda7-report-correction.md). Do not treat
`resumeEvidence.optimizer: true` as a restore, or
`parametersUpdated: true` as a two-checkpoint adapter diff.

Host SHA256 now exists: checkpoint-10 adapter
`sha256:3a0260a51c22347a09e69cfaa046f3727fde3a5da800ac2cebea65d3bf78a4d5`
≠ checkpoint-20 adapter
`sha256:9d5ec47068c05809c4fb23f8d9e3d624e3c1279b10308edc6cd355b099c8ff58`.

## Code identity

[code-identity.md](code-identity.md). cuda.7 did not run a clean
`git rev-parse HEAD` on both machines. cuda.8 loaded the e47279d
`gpu.py` through a shared `.venv` (resume keys rejected). cuda.9 used
`PYTHONPATH` onto the 374f5c6 overlay.

A later independent venv of a full commit is not cuda.7/cuda.9 runtime
and is not a new grant. Receipt:
[independent-venv.json](independent-venv.json) (archive of `041365a`;
own `.venv`; `gpu.py` SHA-256 `8a69aed235…29ba`; `workers run` not
started).

## cuda.9 restore semantics

Keep the CAS JSON. Read [cuda9-report-correction.md](cuda9-report-correction.md).
`restore.status: verified` in the live report meant “argv requested full
checkpoint loads and steps grew”. Observed: `global_step` (`11/20`) and
weights (source vs this-run adapter). optimizer / scheduler / rng:
**unverified** (no framework load logs). checkpoint-20 is this-run, not a
pre-copied leftover. No `grant.wsl.cuda.10`.

## Charter matrix

[m2-closure-matrix.md](m2-closure-matrix.md). Paid cloud is N/A at ¥0.
`unknown ≠ rerun` cites tests, not a two-host unknown live.

## Not proven / out of slice

| Item | Status |
| --- | --- |
| `unknown ≠ rerun` two-host live | not a dedicated live shot; see tests. cuda.8 was **failed**, not rerun |
| M2 charter §14.4 paid cloud | N/A (¥0); not a missing live shot |
| optimizer/scheduler/rng actually loaded on cuda.9 | unverified; no framework load log |
| Independent venv as cuda.7/9 runtime | never; those grants used overlay / shared venv. [independent-venv.json](independent-venv.json) is a later archive install only |
| Worker GET of checkpoint blobs | denied by design (`http-artifact-denied`); retrieve is `artifacts verify` |

Do not reuse `grant.wsl.cuda.1`–`.9`. Do not merge PR #73 as M2 close.
Do not close Issue #38.

## Reproduce (no GPU)

```bash
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_worker_gpu.py tests/test_worker_isolate.py \
  tests/test_worker_recovery.py tests/test_training_checkpoint.py
# CI / PR: uv run pytest --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
uv run researchos training overlay examples/training-backend/valid/wsl-cuda-sft.json \
  --resume full-checkpoint --checkpoint /work/output/checkpoint-10 --format json
```
