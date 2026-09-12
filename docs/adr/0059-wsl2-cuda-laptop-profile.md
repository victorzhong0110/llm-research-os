# ADR-0059: WSL2 CUDA laptop profile and authorized container start

- Status: Accepted
- Date: 2026-09-10

This record does not reopen ADR-0056 bind semantics. It does not close
Issue #38, claim every Linux GPU host, or auto-merge the GPU PR stack.

## Context

ADR-0056 `execute_gpu_training` validates the GPU object and returns
`gpu-not-run`. The 24 GiB memory ceiling matches an unpaid AutoDL 4090
sheet. A Windows 11 + WSL2 + Docker Engine host with 6 GiB WSL RAM and
an 8 GB RTX 4060 cannot use that envelope. Two-host Worker transport
(ADR-0021) was still `pending-live`.

## Decision

1. **Bind stays not-run.** `researchos training plan` / `bind` and
   `execute_gpu_training` keep `executed: false` / `gpu-not-run`.
2. **`run_gpu_training` is the Worker execution entry.** After grant +
   poll it may start docker with `--gpus device=0` (never `all`),
   observe cancel, and fail closed without docker or a digest-pinned
   image. The closed argv keeps `--read-only` and `--user 65534:65534`.
   Before poll, the Worker MUST grant that user write on the dedicated
   output root (ownership or ACL, not mode `775` alone, never `0777`)
   and prove it with a file-ops probe in the same image, user, mounts,
   and read-only root. The probe does not load a model or use a GPU.
   UID 65534 has passwd `HOME=/nonexistent`; HuggingFace datasets mkdir
   on that path is EROFS. The launch MUST set `HOME=/tmp`, `HF_HOME=/tmp/hf`,
   and `HF_DATASETS_CACHE=/tmp/hf/datasets` on the existing `/tmp` tmpfs.
   GPU `/tmp` tmpfs MUST NOT use `noexec`: Triton compiles and loads a `.so`
   there. The image MUST include `python3-dev` (`Python.h`) for that compile.
   It MUST NOT add bind mounts or drop `--read-only` to paper over cache.
3. **Closed laptop profile** `wsl2-cuda-laptop-8g`: default 3 GiB
   container memory, max 4 GiB, 6 CPU, 1800 s wall. It MUST NOT reuse
   the 16–24 GiB AutoDL defaults.
4. **Closed plan** `WslCudaTrainingPlan`: Qwen2.5-0.5B-Instruct revision
   `7ae557604adf67be50417f59c2c2f167def9a775`, local `/work/data/sft.jsonl`,
   LoRA, batch 1, `max_length` 256, `bfloat16`, mounts
   `/work/model` `/work/data` `/work/output`. Authorized step pairs are
   `(max_steps=20, save_steps=10)` and `(12, 2)`. Network remains denied.
5. **Artifact PUT** on Worker HTTPS may use 256 MiB (`MAX_WORKER_PUT_BYTES`)
   so real LoRA checkpoints can upload. JSON control bodies stay 1 MiB.
   Collect `--profile wsl2-cuda` uses the same 256 MiB bound. AutoDL `gpu`
   collect stays 1 MiB.
6. **Platform claim.** Live evidence, when recorded, is Windows/WSL2 +
   Docker Engine. It is not native Linux or cloud GPU acceptance.
7. **Checkpoint file presence is not a restore.** `resumeEvidence.kind` is
   `checkpoint-state-files`. A restore is a new overlay execution
   (`resume` + `checkpoint` in the grant, `commandDigest` of the overlay
   argv). `parametersUpdated` is true only when two checkpoints differ;
   a single checkpoint is unverified. Restore reports MUST split
   `requestedLoads` (argv / overlay) from `observedLoads`. optimizer /
   scheduler / rng are verified only from the container Trainer load
   hook JSONL (`phase=loaded`, source digest, post-load summary), not
   from prepare-to-load strings, argv, or file presence. Checkpoints
   already present in the output snapshot before docker starts MUST NOT
   count as this-run products. The GPU launch copies that hook onto
   `/work/output/.researchos` and sets closed `PYTHONPATH` plus
   `RESEARCHOS_GPU_RESTORE_OBSERVE=1`.
8. **Paid cloud is optional.** A zero-spend WSL laptop proof does not
   satisfy a paid-cloud cap; record that row as not applicable.

## Consequences

- Ordinary pytest without docker still cannot claim CUDA success.
- Two-host TLS/Worker registration remains a live step on a named
  Tailscale (or equivalent) unicast address with SAN coverage.

## Validation

1. WSL profile rejects 16 GiB `memoryBytes`.
2. `execute_gpu_training` with host dirs remains `gpu-not-run`.
3. `run_gpu_training` without host dirs is `gpu-host-dirs-missing`.
4. Bind of `WslCudaTrainingPlan` prints `--gpus device=0` and 3 GiB
   `--memory`.
5. Prepared GPU argv keeps `--read-only` and sets `HOME=/tmp` on the
   existing `/tmp` tmpfs (not passwd `/nonexistent`).
6. Root-owned dedicated output + UID 65534 either becomes writable
   after prepare (real container probe) or is refused before claim.

## References

- [ADR-0056](0056-gpu-training-execution-profile.md)
- [ADR-0021](0021-remote-worker-transport.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
