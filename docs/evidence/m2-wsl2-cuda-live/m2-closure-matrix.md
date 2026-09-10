# M2 charter §14.4 closure matrix (not M2 complete)

Charter: [docs/charter-v0.1.md](../../charter-v0.1.md) §14.4.
Issue [#38](https://github.com/victorzhong0110/llm-research-os/issues/38)
stays **open**. PR [#73](https://github.com/victorzhong0110/llm-research-os/pull/73)
stays **open**; this document does not merge anything.

Platform claim, where live: **Windows/WSL2 + Docker Engine**. Not native
Linux. Not paid cloud GPU.

## Charter rows

| Requirement | Implementation | Evidence | Remaining |
| --- | --- | --- | --- |
| Remote Worker | Loopback HTTPS Worker plus two-host TLS Worker (`worker.wsl.1`, `worker.wsl.gpu.1`) | EventStore seq 1–142; [eventstore-redacted.json](eventstore-redacted.json); [eventstore-redacted-cuda8-9.json](eventstore-redacted-cuda8-9.json); [https-locate.md](https-locate.md) | Not a productized multi-tenant Worker. #38 open. |
| `OCIContainerRuntime` | Digest-pinned CPU OCI runtime; Linux CI `oci_live`; two-host CPU grant | `grant.wsl.oci.1` completed seq 12–14; GitHub job Linux OCI integration | GPU path uses `run_gpu_training` / `gpu-oci-container`, not a second generic GPU OCI class. |
| GPU capability report | Worker advertised `cuda`; grants require it | `work.queued` payloads for cuda.7/cuda.9; Worker register `worker.wsl.gpu.1` | No cloud GPU advertisement. |
| Generic Python training brick | CPU brick + GPU bind stay `gpu-not-run` until grant | ADR-0056; `execute_gpu_training` tests | Unchanged. |
| Real training-framework adapter (ms-swift) | Pinned `ms-swift==4.5.2` WSL plan; 20-step LoRA live | [cuda7-WslCudaTrainingReport.json](cuda7-WslCudaTrainingReport.json) seq 116–118; [cuda7-report-correction.md](cuda7-report-correction.md) | One laptop profile only. Not AutoDL. |
| Checkpoint | Host SHA256 + Worker `POST /v0alpha1/artifacts` (22 files) | [cuda7-frozen-inventory.json](cuda7-frozen-inventory.json); [upload-cuda7.json](upload-cuda7.json); [retrieve-proof.json](retrieve-proof.json) | Worker GET of blobs remains `http-artifact-denied` by design. |
| Stop | Two-host cancel observed; process identity | `grant.wsl.cancel.1` `cancel-observed` seq 48–50 | No extra GPU cancel live shot. |
| Restore | New overlay grant `grant.wsl.cuda.9`; reports split requested vs observed loads; leftovers excluded | seq 140–142; [cuda9-WslCudaTrainingReport.json](cuda9-WslCudaTrainingReport.json) (historical, over-claimed `verified`); [cuda9-report-correction.md](cuda9-report-correction.md); `tests/test_worker_gpu.py` | optimizer/scheduler/rng **unverified** (no framework load logs). No cuda.10. |
| Artifact upload | Worker HTTPS PUT 256 MiB cap; control-plane `artifacts verify` | [collect-cuda7.receipt.json](collect-cuda7.receipt.json); [retrieve-proof.json](retrieve-proof.json) | Same as checkpoint row. |
| Training / evaluation / system / cost / lineage views | Static `researchos report` HTML/Markdown. Evaluation and System are now separate headings. Cost and lineage already existed. | `src/llm_research_os/report/render.py`; `tests/test_report.py`; M1-5 synthetic metrics | No React / live dashboard. CUDA runs have no `evaluation.metric` facts — Evaluation says so. System lists worker/work/attempt events when present. |
| First paid task: per-job and total caps | Budget events and CNY caps exist in M1 | `budget.*` protocol; this live pack spent **¥0** | **N/A** — no paid cloud job. Do not invent a cap proof from WSL. |

## Explicit non-claims

| Topic | What is true | What is not claimed |
| --- | --- | --- |
| `unknown ≠ rerun` | Unit/loopback: [unknown-not-rerun.md](unknown-not-rerun.md) | Dedicated two-host unknown live. cuda.8 was **failed**, not rerun. |
| Paid cloud | Not done | Not a remaining live experiment for this pack. |
| Code identity | cuda.7 overlay `b3da4bd` / e47279d tree; cuda.8 shared venv miss; cuda.9 `PYTHONPATH` overlay; independent venv of `041365a` with its own `.venv` | Those live grants did not run final pack HEAD. Independent venv did not `workers run`. |
| Leftover checkpoint-20 | cuda.9 checkpoint-20 mtime is new vs freeze-copied checkpoint-10; adapter SHA matches cuda.7 checkpoint-20 | That match is leftover copy. |

## Stacked PRs (do not merge)

Merge into `main` from the bottom. Do not merge in this slice.

1. [#55](https://github.com/victorzhong0110/llm-research-os/pull/55) `m2/worker-protocol-cpu-loop` → `main`
2. [#56](https://github.com/victorzhong0110/llm-research-os/pull/56)
3. [#57](https://github.com/victorzhong0110/llm-research-os/pull/57)
4. [#58](https://github.com/victorzhong0110/llm-research-os/pull/58)
5. [#59](https://github.com/victorzhong0110/llm-research-os/pull/59)
6. [#60](https://github.com/victorzhong0110/llm-research-os/pull/60)
7. [#61](https://github.com/victorzhong0110/llm-research-os/pull/61)
8. [#62](https://github.com/victorzhong0110/llm-research-os/pull/62)
9. [#63](https://github.com/victorzhong0110/llm-research-os/pull/63)
10. [#64](https://github.com/victorzhong0110/llm-research-os/pull/64)
11. [#65](https://github.com/victorzhong0110/llm-research-os/pull/65)
12. [#66](https://github.com/victorzhong0110/llm-research-os/pull/66)
13. [#67](https://github.com/victorzhong0110/llm-research-os/pull/67)
14. [#68](https://github.com/victorzhong0110/llm-research-os/pull/68)
15. [#69](https://github.com/victorzhong0110/llm-research-os/pull/69)
16. [#70](https://github.com/victorzhong0110/llm-research-os/pull/70)
17. [#71](https://github.com/victorzhong0110/llm-research-os/pull/71)
18. [#72](https://github.com/victorzhong0110/llm-research-os/pull/72) `m2/macos-mps-training`
19. [#73](https://github.com/victorzhong0110/llm-research-os/pull/73) `m2/wsl2-cuda-live` (this slice)

[#43](https://github.com/victorzhong0110/llm-research-os/pull/43) Dependabot is outside this stack.

## GitHub required checks

`15a8025` protocol jobs cancelled at the 20-minute cap inside pytest, not
`cancel-in-progress`. Root cause: `_reap_process_group` `killpg`'d pytest
when a MPS test spawned `/bin/sleep` in the runner's group (Linux SIGKILL;
the job then sat). Also fixed Worker HTTPS GET `read(256MiB+1)` and 120s
sockets. Required protocol pytest uses `-m "not oci_live and not slow"`.
Local pytest is not a substitute for the required GitHub checks.
