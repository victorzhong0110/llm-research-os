# M2 charter §14.4 closure matrix (not M2 complete)

Charter: [docs/charter-v0.1.md](../../charter-v0.1.md) §14.4.
Integration correction: PR [#73](https://github.com/victorzhong0110/llm-research-os/pull/73)
was merged into `main` as `229d1b0` from accepted evidence `57ffdae`.
PRs #55–#72 were closed as superseded. The live records below retain their
original runtime identity and limitations. Integration is not a public release.
Issue #38 tracks the independent M1 checkpoint, not the CUDA experiment.

Platform claim, where live: **Windows/WSL2 + Docker Engine**. Not native
Linux. Not paid cloud GPU.

## Charter rows

| Requirement | Implementation | Evidence | Remaining |
| --- | --- | --- | --- |
| Remote Worker | Loopback HTTPS Worker plus two-host TLS Worker (`worker.wsl.1`, `worker.wsl.gpu.1`) | EventStore seq 1–166; [eventstore-redacted.json](eventstore-redacted.json); [eventstore-redacted-cuda8-9.json](eventstore-redacted-cuda8-9.json); [eventstore-redacted-cuda10.json](eventstore-redacted-cuda10.json); [eventstore-redacted-cuda11.json](eventstore-redacted-cuda11.json); [https-locate.md](https-locate.md) | Not a productized multi-tenant Worker. #38 open. |
| `OCIContainerRuntime` | Digest-pinned CPU OCI runtime; Linux CI `oci_live`; two-host CPU grant | `grant.wsl.oci.1` completed seq 12–14; GitHub job Linux OCI integration | GPU path uses `run_gpu_training` / `gpu-oci-container`, not a second generic GPU OCI class. |
| GPU capability report | Worker advertised `cuda`; grants require it | `work.queued` payloads for cuda.7/cuda.9; Worker register `worker.wsl.gpu.1` | No cloud GPU advertisement. |
| Generic Python training brick | CPU brick + GPU bind stay `gpu-not-run` until grant | ADR-0056; `execute_gpu_training` tests | Unchanged. |
| Real training-framework adapter (ms-swift) | Pinned `ms-swift==4.5.2` WSL plan; 20-step LoRA live | [cuda7-WslCudaTrainingReport.json](cuda7-WslCudaTrainingReport.json) seq 116–118; [cuda7-report-correction.md](cuda7-report-correction.md) | One laptop profile only. Not AutoDL. |
| Checkpoint | Host SHA256 + Worker `POST /v0alpha1/artifacts` (22 files) | [cuda7-frozen-inventory.json](cuda7-frozen-inventory.json); [upload-cuda7.json](upload-cuda7.json); [retrieve-proof.json](retrieve-proof.json) | Worker GET of blobs remains `http-artifact-denied` by design. |
| Stop | Two-host cancel observed; process identity | `grant.wsl.cancel.1` `cancel-observed` seq 48–50 | No extra GPU cancel live shot. |
| Restore | Overlay `grant.wsl.cuda.11` 10→12 with Trainer load-hook JSONL (`phase=loaded`) for optimizer/scheduler/rng. cuda.9 remains partial; cuda.10 remains the failed permission shot | seq 164–166; [cuda11-success.md](cuda11-success.md); [cuda11-WslCudaTrainingReport.json](cuda11-WslCudaTrainingReport.json); seq 153 [cuda10-failure.md](cuda10-failure.md); [cuda9-report-correction.md](cuda9-report-correction.md) | One laptop restore pair only. Not paid cloud. |
| Artifact upload | Worker HTTPS PUT 256 MiB cap; control-plane `artifacts verify` | [collect-cuda7.receipt.json](collect-cuda7.receipt.json); [retrieve-proof.json](retrieve-proof.json) | Same as checkpoint row. |
| Training / evaluation / system / cost / lineage views | Static `researchos report` HTML/Markdown. Evaluation and System are now separate headings. Cost and lineage already existed. | `src/llm_research_os/report/render.py`; `tests/test_report.py`; M1-5 synthetic metrics | No React / live dashboard. CUDA runs have no `evaluation.metric` facts — Evaluation says so. System lists worker/work/attempt events when present. |
| First paid task: per-job and total caps | Budget events and CNY caps exist in M1 | `budget.*` protocol; this live pack spent **¥0** | **N/A** — no paid cloud job. Do not invent a cap proof from WSL. |

## Explicit non-claims

| Topic | What is true | What is not claimed |
| --- | --- | --- |
| `unknown ≠ rerun` | Unit/loopback: [unknown-not-rerun.md](unknown-not-rerun.md) | Dedicated two-host unknown live. cuda.8 was **failed**, not rerun. |
| Paid cloud | Not done | Not a remaining live experiment for this pack. |
| Code identity | cuda.7 overlay `b3da4bd` / e47279d tree; cuda.8 shared venv miss; cuda.9 `PYTHONPATH` overlay; independent venv of `041365a` (no `workers run`); cuda.10 independent venv of `6e60115`; cuda.11 independent venv of `b7d960c` | cuda.11 is the restore runtime; see [code-identity.md](code-identity.md) |
| Leftover checkpoint-20 | cuda.9 checkpoint-20 mtime is new vs freeze-copied checkpoint-10; adapter SHA matches cuda.7 checkpoint-20 | That match is leftover copy. |

## Integration history

The nineteen-PR stack was integrated through #73 alone after changing its base
to main. Do not replay the historical bottom-up merge instructions. Dependabot
updates are independent of this experiment pack.

## GitHub required checks

`15a8025` protocol jobs cancelled at the 20-minute cap inside pytest, not
`cancel-in-progress`. Root cause: `_reap_process_group` `killpg`'d pytest
when a MPS test spawned `/bin/sleep` in the runner's group (Linux SIGKILL;
the job then sat). Also fixed Worker HTTPS GET `read(256MiB+1)` and 120s
sockets. Required protocol pytest uses `-m "not oci_live and not slow"`.
Local pytest is not a substitute for the required GitHub checks.

Observe-hook commit `6e60115` required checks:
https://github.com/victorzhong0110/llm-research-os/actions/runs/34594958194
(success). Restore live on that SHA failed; see [cuda10-failure.md](cuda10-failure.md).

Permission-prepare + `python3` probe commit `b7d960c` required checks:
https://github.com/victorzhong0110/llm-research-os/actions/runs/34619555030
(success). Live restore on that SHA completed seq 164–166; see
[cuda11-success.md](cuda11-success.md). Evidence for that run lands in a
follow-up commit on this branch; required checks must also pass on that
HEAD.
