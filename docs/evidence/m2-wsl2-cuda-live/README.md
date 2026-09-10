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
| EventStore 118 events, last `run.completed` for cuda.7 | [eventstore-redacted.json](eventstore-redacted.json) |
| CPU OCI two-host `grant.wsl.oci.1` completed seq 12–14 | same excerpt |
| Reconnect `grant.wsl.reconnect.1` completed seq 41–43 | same excerpt |
| Cancel `grant.wsl.cancel.1` `cancel-observed` seq 48–50 | same excerpt |
| CUDA 20-step `grant.wsl.cuda.7` completed seq 116–118 | [cuda7-WslCudaTrainingReport.json](cuda7-WslCudaTrainingReport.json) |
| cuda.1 revoked; cuda.2–6 consumed-failed | excerpt + [cuda-grants.md](cuda-grants.md) |
| Report file-presence ≠ restore; single checkpoint ≠ `parametersUpdated` | `tests/test_worker_gpu.py` |
| GPU resume overlay is a new `commandDigest` | `tests/test_worker_gpu.py`, [restore-overlay.preflight.json](restore-overlay.preflight.json) |
| `unknown ≠ rerun` (unit / loopback) | [unknown-not-rerun.md](unknown-not-rerun.md) |
| HTTPS serve still listening; proxy caused the TLS timeout | [https-locate.md](https-locate.md) |

## Corrected cuda.7 report semantics

The original `WslCudaTrainingReport` in CAS is unchanged
(`sha256:9da93e29…ea76`, seq 116). Read it with
[cuda7-report-correction.md](cuda7-report-correction.md). Do not treat
`resumeEvidence.optimizer: true` as a restore, or
`parametersUpdated: true` as a two-checkpoint adapter diff.

## Code identity

[code-identity.md](code-identity.md). cuda.7 did not run a clean
`git rev-parse HEAD` on both machines.

## Not proven live (this pack)

| Item | Status |
| --- | --- |
| Checkpoint-20 file list / SHA256 on the Worker host | blocked: Windows Tailscale peer absent; SSH closes before banner |
| `POST /v0alpha1/artifacts` of adapter + restore state | not run (needs the host files) |
| Control-plane retrieve of those bytes | not run |
| Authorized restore from checkpoint-10 → 20 | static overlay only; no new grant |
| `unknown ≠ rerun` two-host live | not a dedicated live shot; see tests |
| M2 charter §14.4 dashboards / paid-cloud | out of this slice |

Do not reuse `grant.wsl.cuda.1`–`.7`. Do not merge PR #73. Do not close
Issue #38.

## Reproduce (no GPU)

```bash
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_worker_gpu.py tests/test_worker_isolate.py \
  tests/test_worker_recovery.py tests/test_training_checkpoint.py --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
uv run researchos training overlay examples/training-backend/valid/wsl-cuda-sft.json \
  --resume full-checkpoint --checkpoint /work/output/checkpoint-10 --format json
```

Live restore, when the Worker is reachable, is a **new** grant
(`grant.wsl.cuda.8`) with the overlay `commandDigest` above, a copied
`checkpoint-10` in a fresh output dir, and the closed `maxSteps: 20`
plan. That is ten additional steps on the closed plan, not a schema
change to `maxSteps: 22`.
