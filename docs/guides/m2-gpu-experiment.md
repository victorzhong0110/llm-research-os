# M2 GPU experiment sheet (not executed)

This sheet is the unpaid GPU run design. It is **not** a GPU result, **not**
M2 acceptance, and **not** authorization to spend.

Do not rent a cloud GPU, do not recharge, and do not start `swift sft` here.
`researchos training plan` only prints argv. Cost stays unknown until the
researcher records `budget.limit.recorded` and says 开 for this single run.

Constraint: [ADR-0048](../adr/0048-pinned-ms-swift-adapter.md),
[ADR-0053](../adr/0053-gpu-experiment-sheet.md).
Protocol: [Training backend plan v0alpha1](../protocols/training-backend-plan-v0alpha1.md).
Image method: [examples/m2-gpu-image](../../examples/m2-gpu-image/README.md).

## Interface audit (`ms-swift==4.5.2`)

Source: tagged docs
[Command-line-parameters.md @ v4.5.2](https://raw.githubusercontent.com/modelscope/ms-swift/v4.5.2/docs/source_en/Instruction/Command-line-parameters.md)
and `swift/cli/sft.py` (`sft_main`). v3 `--sft_type` / `--train_type` are
**not** this pin. v4 uses `--tuner_type`.

| Planned argv flag | v4.5.2 docs |
|---|---|
| `swift sft` | entrypoint `swift/cli/sft.py` |
| `--model` | required model id or path |
| `--tuner_type lora` | values include `lora` (default) |
| `--dataset` | dataset id; `#N` takes first N rows |
| `--torch_dtype bfloat16` | `float16` / `bfloat16` / `float32` |
| `--max_steps 1` | max trainer steps |
| `--per_device_train_batch_size 1` | default 1 |
| `--gradient_accumulation_steps 1` | documented |
| `--learning_rate 1e-4` | LoRA default `1e-4` |
| `--lora_rank 8` | default 8 |
| `--lora_alpha 16` | documented; default 32. Plan pins 16 |
| `--output_dir /work/output` | documented |
| `--save_steps 1` | default 500; plan pins 1 |
| `--logging_steps 1` | documented |
| `--max_length 512` | documented |

Resume is **not** a second backend. Keep the same argv and add
`--resume_from_checkpoint /work/output/<run>/checkpoint-1`. That loads
weights, optimizer, seed, and continues from the last step. `--adapters`
loads adapter weights only and MUST NOT be treated as a full resume.
Unknown work MUST NOT auto-rerun (ADR-0046, ADR-0051).

## Combo (named, not run)

| Item | Value | Status |
|---|---|---|
| Backend | `ms-swift==4.5.2` (`swift sft`, `--tuner_type lora`) | Parse/plan matches v4.5.2 docs |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` (ModelScope / Hub id; pin the snapshot after first download) | Not downloaded here |
| Data | `AI-ModelScope/alpaca-gpt4-data-en#8` (first 8 rows) | Not downloaded here |
| Image | Build [examples/m2-gpu-image](../../examples/m2-gpu-image/README.md); pin `sha256:` after `docker build`. Tag is not identity | Digest TBD until built |
| Runtime | `gpu-oci-container` + `execute.gpu` (ADR-0056) with `requiredAccelerators: ["cuda"]` | Profile in tree; CUDA not run |
| GPU | **AutoDL RTX 4090 24GB**, 1 card, Ubuntu, no extra disks beyond the instance disk | Not rented |
| CUDA | Image ships CUDA 12.4 toolkit; host must expose one NVIDIA GPU (`nvidia-smi`) | Not verified on a GPU host |
| Estimated wall time | **45 minutes** (pull image + 0.5B weights + 8-row dataset + 1 step). GPU-hours ≈ 0.75 | Not measured |
| Public price quotes (not invoices) | AutoDL docs list SKU prices as **console-only**. 2026-06/07 roundups for 4090 span ≈ **¥1.61–3.49 / hour**. Planning uses **¥3.49/h** as a conservative public upper bound | Not billed |
| Compute estimate | 0.75 h × ¥3.49 ≈ **¥2.62** GPU-instance time. Idle powered-on time still bills. Paid data disk bills after 关机 until 缩容/释放 | Unknown until invoice |
| Single-run cost cap | **¥20.00 CNY** MUST be recorded as `budget.limit.recorded` before boot. This number is the proposed cap, not a spend | Cap not recorded; ¥0 spent |
| Envelope / remaining | Charter M2 envelope **¥1000**. Remaining **¥1000** until a recorded consume | Untouched |
| Stop (Worker) | Cancel request, then observe process/container exit (ADR-0050). Container stop ≠ cloud instance stop | CPU proven; GPU pending |
| Stop (cloud) | After observe: AutoDL **关机** ends **instance** billing (docs: 开机开始计费、关机结束计费, per-second, min ¥0.01; billed on power, not on whether GPU compute ran). **付费数据盘** still bills daily after 关机 until **缩容** or **释放**. The Worker MUST NOT issue cloud-instance stop (`cloud-instance-stop-forbidden`) | Researcher console only |
| Disconnect | Timeout/kill/disconnect is `unknown`. CAS without `work.completed` is not success. Resume uses `--resume_from_checkpoint` on `checkpoint-1`; do not spawn a second 1-step run as if the first never happened | CPU proven; GPU pending |
| Acceptance | See below. None of these are met | GPU not-run |

## GPU options compared (obtainable, not invoices)

AutoDL [充值与计费](https://www.autodl.com/docs/price/) (fetched 2026-09-08):
on-demand instance billing starts at boot and **ends at 关机**, per-second,
minimum ¥0.01. Duration is **power on/off**, not GPU-kernel time. SKU ¥/h
is **console-only** (`各型号GPU价格：请以网站显示的现价为准`). Paid extra
disk bills the next day even after 关机 until 缩容 or 释放. File storage
is free under 20 GB then ¥0.01/GB/day; saved images free under 30 GB then
¥0.01/GB/day.

Public 2026-06/07 roundups (not the console): AutoDL 4090 ≈ ¥1.61–3.49/h;
晨涧云 4090 ≈ ¥1.50–2.20/h; AutoDL 3090 ≈ ¥1.2–1.7/h. Recheck the console
before any 开. This tree does not open an account, pass a key, or subscribe.

| Option | Why considered | Obtainable quote / billing | Fit for this 1-step 0.5B LoRA |
|---|---|---|---|
| AutoDL RTX 4090 24GB | Shanghai researcher, CNY path, 关机 stops instance billing | Roundups ¥1.61–3.49/h; plan with **¥3.49/h** upper bound | **Selected on the sheet.** Peak hours may have no stock |
| 晨涧云 RTX 4090 | Same SKU, often cheaper long-rent | Roundups ≈ ¥1.50–2.20/h | Backup if AutoDL has no 4090 |
| AutoDL RTX 3090 24GB | Lower public quote, 24 GB | Roundups ≈ ¥1.2–1.7/h | Enough VRAM; slower; only if 4090 is unavailable |
| Hugging Face Jobs | Obtainable, billed in USD on a Pro plan | Not used | Different trainer (TRL/Unsloth), paused HF first-cut lane, would still be paid |
| Local Mac | This machine | ¥0 GPU | No CUDA device; cannot accept this sheet |

A100/H100 are unnecessary for 0.5B LoRA and would burn the envelope faster.

## Data, model, checkpoint (concrete, unpaid)

Do not change the closed `TrainingBackendPlan` for resume.

1. **Model.** Plan field `Qwen/Qwen2.5-0.5B-Instruct`. Hugging Face revision
   `7ae557604adf67be50417f59c2c2f167def9a775` is recorded in
   [`examples/m2-gpu-checkpoint/data-binding.json`](../../examples/m2-gpu-checkpoint/data-binding.json).
   After the first download on a GPU host, record `contentDigest` of that
   local tree. Do not silently retarget a newer snapshot.
2. **Data.** Plan field `AI-ModelScope/alpaca-gpt4-data-en#8` (first 8 rows).
   ModelScope git SHA is `pending-live` until recorded on the GPU host.
   Lineage cites Hugging Face `vicgalle/alpaca-gpt4` @
   `f7e3ded725cb81e8e564e32feb12860f376f2b51`. Eight rows exist so one step
   finishes inside the 45 minute wall.
3. **Output.** `--output_dir /work/output` is a bind mount, not tmpfs.
   `researchos training collect` puts files into CAS (1 MiB / 32 files).
   Real LoRA weights may exceed that bound; raising it is a later review.
4. **Resume overlay.** `researchos training overlay --resume full-checkpoint`
   adds `--resume_from_checkpoint` and loads weights, optimizer, scheduler,
   RNG, and `global_step`. `--resume adapter-only` adds `--adapters` and is
   **not** a full resume. `--resume_only_model` is forbidden. Overlay is a
   new `commandDigest`, not a silent second spawn.
5. **Unknown.** Timeout, Worker kill, or disconnect without `work.completed`
   stays `unknown`/`lost`. Do not auto-rerun. A recovery client must not
   spawn a second 1-step job while the original executor is alive.
6. **CPU fixture.** `examples/training-backend/cpu-snapshot` plus
   `researchos training snapshot` / `collect` prove the protocol without a
   GPU. That is not CUDA training or resume success.

## Command that is allowed now

```bash
uv run researchos training plan \
  examples/training-backend/valid/ms-swift-sft.json \
  --format json
uv run researchos training snapshot \
  examples/m2-gpu-checkpoint/data-binding.json \
  --plan examples/training-backend/valid/ms-swift-sft.json \
  --format json
uv run researchos training overlay \
  examples/training-backend/valid/ms-swift-sft.json \
  --resume full-checkpoint \
  --checkpoint /work/output/run/checkpoint-1 \
  --format json
```

Receipt MUST show `executed: false`, `gpu: not-run`, `costKnown: false`.

Image verify (no GPU, no training):

```bash
sh examples/m2-gpu-image/verify.sh
```

Missing docker is `skipped-no-runtime`. Docker without
`RESEARCHOS_GPU_IMAGE_BUILD=1` is `skipped-no-build` (does not pull CUDA).
Linux with disk may run:

```bash
RESEARCHOS_GPU_IMAGE_BUILD=1 sh examples/m2-gpu-image/verify.sh
```

That build runs `swift sft --help` and MUST NOT pass `--gpus` or train.
If the flag is set and docker is missing or down, the script **fails**
(`failed-no-runtime`); it does not skip. Designated Linux OCI CI must not
set that flag.

## Acceptance (all required)

1. `budget.limit.recorded` cap **¥20** on this project; researcher said 开
   for this one run.
2. Digest-pinned image; `swift sft --help` shows `--tuner_type`; `nvidia-smi`
   sees one 4090.
3. One grant with `requiredAccelerators: ["cuda"]` on a Worker that advertised
   `cuda`.
4. `work.completed` with adapter files under `/work/output/**/checkpoint-1`.
5. Report cites spec, runtime, image, config, output artifact.
6. Invoice or console charge ≤ ¥20; AutoDL instance 关机 (and 释放 if disk
   would keep billing).
7. If the run becomes `unknown`, resume is `--resume_from_checkpoint` on that
   checkpoint, not a silent second spawn.

Until those exist, do not say real training ran and do not close Issue #38.
