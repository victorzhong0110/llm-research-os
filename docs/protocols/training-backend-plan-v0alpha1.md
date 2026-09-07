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
a launch token. Resume overlay is `--resume_from_checkpoint` on the same
argv.

## Isolation

CPU Worker paths (`m2 prove`, host-python brick, OCI adapter) MUST NOT
import this package. Training dependencies MUST NOT enter the core
lockfile.
