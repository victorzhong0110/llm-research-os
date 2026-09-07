# ADR-0058: Independent macOS/MPS training execution profile

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0008, ADR-0034, ADR-0045, ADR-0048,
ADR-0056, or ADR-0057. It does not claim NativeProcessRuntime, OCI
isolation, CUDA success, or Issue #38 close.

## Context

The GPU profile (ADR-0056 / ADR-0057) is `gpu-oci-container` /
`execute.gpu` with docker `--gpus device=0` and a 1 MiB CAS collect
bound. Apple Silicon has no docker GPU device. Reusing that shape, or
calling a host `swift sft` a Worker result, would invent isolation and
skip plan authorization. ADR-0008 / ADR-0034 still defer
NativeProcessRuntime.

## Decision

1. **Separate runtime and capability.** `runtime: macos-mps-process` with
   `imageMediaType: researchos.mps-swift-env/v0alpha1` and
   `execute.mps`. A `python-sandbox`, `oci-container`, or
   `gpu-oci-container` Worker MUST NOT lease MPS work.
2. **Closed Mac/MPS plan.** `kind: MacMpsTrainingPlan` is independent of
   `TrainingBackendPlan`. Pinned values: `ms-swift==4.5.2`,
   `Qwen/Qwen2.5-0.5B-Instruct` revision
   `7ae557604adf67be50417f59c2c2f167def9a775`, local `data/sft.jsonl`,
   LoRA, batch 1, `max_length` 256, `max_steps` 20, `float32`,
   authorized `accDevice: mps`. Argv does **not** pass `--device_map mps`:
   PyTorch 2.14 deadlocks that path. Weights load on CPU; HuggingFace
   Trainer `args.device` is `mps`. The extras `pythonpath/sitecustomize.py`
   shim is required. `--model_type qwen2`, `--template qwen2_5`,
   `--add_version false`. The GPU plan stays `maxSteps: 1` /
   `bfloat16` / `/work/output`.
3. **Isolation is process-group, not OCI.** The native process uses a
   POSIX process group, a minimal environment allowlist, a closed
   workspace cwd (`model/`, `data/`, `output/` siblings), offline Hub
   flags, `TMPDIR=/tmp` (macOS `AF_UNIX` path limit), and a 1800 s wall.
   `PYTHONPATH` includes `extras/ms-swift-mps/pythonpath` so Swift does
   not pass `--device_map mps`. The profile MUST NOT declare namespaces,
   cgroups, seccomp, OCI mounts, or NativeProcessRuntime. Launch keys
   such as `privileged`, `gpus`, `mounts`, and `docker` fail closed.
4. **CPU fallback is fail-closed.** A probe that is not `mps` is
   `mps-unavailable`. `PYTORCH_ENABLE_MPS_FALLBACK=1` may exist so
   unimplemented ops can run; those lines MUST be recorded as
   `mpsFallbackOps` and MUST NOT flip `device` to `cpu` or
   `cpuFallback: true` on a passing receipt.
5. **Worker chain is mandatory.** `researchos training plan` still prints
   argv with `executed: false`. Acceptance requires
   `researchos m2 mps`: authorize, lease, execute, collect, and
   `work.completed`. Core CPU files MUST NOT import
   `llm_research_os.training` at module load; the Worker client lazy-imports
   `llm_research_os.workers.mps`.
6. **Resume and artifacts.** `full-checkpoint` adds
   `--resume_from_checkpoint` and must load optimizer, scheduler, RNG,
   and `global_step`. `adapter-only` adds `--adapters` and is not a full
   resume. Collect `--profile mps` allows 256 MiB / 64 files. GPU collect
   stays 1 MiB. Training deps stay out of the core lockfile.

## Consequences

- Deleting `workers/mps.py` leaves GPU OCI and CPU OCI unchanged.
- CUDA/OCI and two-host rows stay `pending-live` unless separately
  proven. A Mac/MPS live receipt is not a 4090 result.
- Issue #38 stays open.

## Validation

1. CPU OCI policy rejects `accDevice`. MPS policy rejects `privileged`
   and `gpus`.
2. `oci-container` and `gpu-oci-container` Workers cannot lease
   `macos-mps-process` work.
3. Stub execute records `executed: true`, finite loss, two adapter
   digests, optimizer/scheduler/RNG, `global_step == 20`, and
   `cancel-observed`.
4. Full resume `commandDigest` differs from adapter-only; adapter-only
   does not continue optimizer state. Live evidence records optimizer,
   scheduler, and RNG file digests, not only `global_step`.
5. MPS collect accepts a file larger than 1 MiB; GPU collect refuses it.
6. `researchos m2 mps examples/m2-mps-checkpoint` records
   `work.completed`. The live environment artifact includes
   `sitecustomizeDigest`.

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0034](0034-m0-scope-clarification.md)
- [ADR-0048](0048-pinned-ms-swift-adapter.md)
- [ADR-0056](0056-gpu-training-execution-profile.md)
- [ADR-0057](0057-gpu-data-checkpoint.md)
- [Mac/MPS training plan v0alpha1](../protocols/mac-mps-training-plan-v0alpha1.md)
- [M2 Mac/MPS acceptance](../guides/m2-mps-acceptance.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
