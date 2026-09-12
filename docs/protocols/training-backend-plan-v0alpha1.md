# Training backend plan v0alpha1

> Status: Experimental parse/plan contract (ADR-0048)  
> Domain version: `v0alpha1`  
> Pinned backend: `ms-swift==4.5.2`

This document is a closed SFT plan. It is not a launch token, not a GPU
run, and not M2 acceptance.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative.

## Document

`kind` is `TrainingBackendPlan`. Fields are a single pinned shape:

| Field | Value |
|---|---|
| `backendId` | `ms-swift` |
| `backendVersion` | `4.5.2` |
| `model` | `Qwen/Qwen2.5-0.5B-Instruct` |
| `dataset` | `AI-ModelScope/alpaca-gpt4-data-en#8` |
| `tunerType` | `lora` |
| `torchDtype` | `bfloat16` |
| `maxSteps` | `1` |
| `outputDir` | `/work/output` |

Other backends, versions, models, step counts, or extra fields MUST fail
closed. The generated JSON Schema is
`schemas/training-backend-plan/v0alpha1.schema.json`.

## Receipt

`researchos training plan REQUEST --format json` MUST print
`TrainingBackendPlanReceipt` with:

- `argv` starting `swift sft` and `--tuner_type lora` (ms-swift v4)
- `executed: false`
- `gpu: not-run`
- `costKnown: false`
- `backendInstalled` from `find_spec("swift")` without importing torch

The command MUST NOT start a process.

`researchos training bind REQUEST --image sha256:… --data-dir DIR
--model-dir DIR --output-dir DIR` MUST print `GpuLaunchPreparation`
with docker argv, the same command argv, `executed: false`, and
`gpu: not-run`. It MUST NOT start docker.

The GPU experiment sheet ([ADR-0053](../adr/0053-gpu-experiment-sheet.md))
names AutoDL RTX 4090, a 45 minute wall, and a proposed ¥20 cap. It is not
a launch token.

## Data snapshot and checkpoint (ADR-0057)

`kind` is `GpuDataCheckpointBinding`. The closed plan MUST NOT grow extra
fields. The binding pins:

| Identity | Value | Status |
|---|---|---|
| Model | `Qwen/Qwen2.5-0.5B-Instruct` @ Hugging Face `7ae557604adf67be50417f59c2c2f167def9a775` | Recorded |
| Dataset | `AI-ModelScope/alpaca-gpt4-data-en` first 8 rows | ModelScope git SHA `pending-live` |
| Dataset lineage | Hugging Face `vicgalle/alpaca-gpt4` @ `f7e3ded725cb81e8e564e32feb12860f376f2b51` | Cross-reference only |
| Output | `/work/output` bind (not tmpfs), max 1 MiB / 32 files into CAS | Protocol |

`researchos training snapshot BINDING` MUST compare local trees, print
prefetch argv, and set `fetched: false`. It MUST NOT download.

`researchos training overlay REQUEST --resume full-checkpoint --checkpoint
/work/output/<run>/checkpoint-1` MUST add `--resume_from_checkpoint` and
declare loads `weights`, `optimizer`, `scheduler`, `rng`, `global_step`.
`--resume adapter-only` MUST add `--adapters` and load adapter weights
only. `--resume_only_model` MUST fail closed. Overlay changes
`commandDigest` and is a new execution object.

`researchos training collect OUTPUT --artifacts DIR` MUST put regular
files from the persistent output directory into CAS, verify digests, and
resume from a prior receipt after interrupt. Symlinks fail closed.
Receipts stay `executed: false` / `gpu: not-run`. This is not a CUDA
checkpoint success.

The generated schema is `schemas/gpu-data-checkpoint/v0alpha1.schema.json`.

## Isolation

CPU Worker paths (`m2 prove`, host-python brick, OCI adapter) MUST NOT
import this package. Training dependencies MUST NOT enter the core
lockfile.
