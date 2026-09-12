# M2 Mac/MPS acceptance (not M2 close)

Issue #38 stays open. This document records the Apple Silicon native
training loop. It does **not** merge PRs, cut a tag, close a milestone,
rent a GPU, or claim CUDA success.

Working language is English. Chinese shop-window: `README.zh-CN.md`.

Constraint: [ADR-0058](../adr/0058-macos-mps-training-profile.md).
Protocol: [mac-mps-training-plan-v0alpha1](../protocols/mac-mps-training-plan-v0alpha1.md).
Install: [extras/ms-swift-mps/README.md](../../extras/ms-swift-mps/README.md).

## 1. Three-column matrix

| Path | What is proven | Evidence | Status |
|---|---|---|---|
| Mac / MPS live | Pinned `ms-swift==4.5.2` LoRA on `Qwen2.5-0.5B-Instruct` @ `7ae557604adf67be50417f59c2c2f167def9a775`; Worker authorize → lease → train → checkpoint → cancel → full resume → CAS collect; parameters changed; loss finite; stop observed; resume `global_step` 10→20 with optimizer/scheduler byte change; RNG file present (live digest may be unchanged) | [`examples/m2-mps-checkpoint/live-evidence.json`](../../examples/m2-mps-checkpoint/live-evidence.json). `cpuFallback: false` because the Worker probe `device` is `mps`. Worker `peakRssBytes` is `ps` RSS and excludes MPS allocations (`mpsAllocatedStatus: unmeasured`). Direct `swift sft` gate (separate receipt): 21.35 s wall, 2.31 GiB `/usr/bin/time -l` RSS. Environment artifact includes `sitecustomizeDigest`. Stub chain: `tests/test_worker_mps.py`. Do not copy this row onto CUDA/OCI | **live** on this developer Mac (Darwin 25.6.0, Apple M4, 24 GiB, torch 2.14.0) |
| CUDA / OCI | `gpu-oci-container` / `execute.gpu`; `execute_gpu_training` returns `gpu-not-run`; designated Linux OCI CPU faults | [m2-gpu-chain-acceptance.md](m2-gpu-chain-acceptance.md) §3 and §5 | **pending-live** (no paid 4090; image digest TBD) |
| Two-host Worker | Independent EventStore/CAS; `secondHost` named | [m2-cross-machine.md](m2-cross-machine.md) | **pending-live** (`secondHost: not-provisioned`) |

Short LoRA runs are **not** accepted on effect (loss drop or eval gain).
Acceptance is the control-plane loop above.

## 2. Isolation (do not inherit OCI)

| Claim | Mac/MPS | GPU OCI |
|---|---|---|
| Runtime | `macos-mps-process` | `gpu-oci-container` |
| Capability | `execute.mps` | `execute.gpu` |
| Image media | `researchos.mps-swift-env/v0alpha1` | `researchos.oci-image/v0alpha1` |
| Isolation | process-group + env allowlist + cwd + offline flags + `TMPDIR=/tmp` + 1800 s wall | docker network-denied, closed mounts, device `nvidia.com/gpu=0` |
| Not claimed | namespaces, cgroup, seccomp, OCI mounts, NativeProcessRuntime | CUDA training success until a paid sheet run |

CPU OCI allow-list still rejects `accDevice`. MPS policy rejects
`privileged` / `gpus` / `mounts`.

## 3. Commands

Stub (CI and ordinary pytest):

```bash
uv run researchos m2 mps \
  examples/m2-mps-checkpoint \
  /tmp/m2-mps.db \
  --format json
```

Live (this Mac, no cloud spend):

```bash
export RESEARCHOS_MPS_PYTHON="$PWD/extras/ms-swift-mps/.venv/bin/python"
export RESEARCHOS_MPS_WORK="$PWD/extras/ms-swift-mps/.cache/run"
uv run researchos m2 mps \
  examples/m2-mps-checkpoint \
  /tmp/m2-mps-live.db \
  --format json
```

Prefetch and direct `swift sft` are in the extras README. Direct argv is
a gate, not the acceptance row.

`pytest -m mps_live` with `RESEARCHOS_MPS_REQUIRED=1` is optional.
GitHub Actions MUST NOT set that flag. A skip of `mps_live` on CI is
not a Mac pass and not a fail.

## 4. Resume and artifacts

| Mode | Argv | Declared loads | Observed full resume |
|---|---|---|---|
| `full-checkpoint` | `--resume_from_checkpoint output/checkpoint-N` | weights, optimizer, scheduler, RNG, `global_step` | yes only if `trainer_state.json` continues `global_step` **and** optimizer/scheduler files are present. Byte-change of those files is recorded; an unchanged `rng_state.pth` digest is `file-present-digest-unchanged`, not a missing file |
| `adapter-only` | `--adapters output/checkpoint-N` | adapter weights | no |

MPS collect: 256 MiB / 64 files, digest verify, interrupt resume.
GPU collect remains 1 MiB / 32 files.

Live evidence cites EventStore event ids, the training-report artifact digest,
the environment artifact (including `sitecustomizeDigest`), and CAS file
digests. A handwritten boolean is not the only proof.

## 5. Not proven

- Paid AutoDL 4090 / CUDA image `sha256:`
- Two-host Worker
- NativeProcessRuntime
- Effect of a 20-step LoRA as research result
- Issue #38 close
