# Mac/MPS training plan v0alpha1

> Status: Experimental native-process contract (ADR-0058)  
> Domain version: `v0alpha1`  
> Pinned backend: `ms-swift==4.5.2`

This document is a closed Apple Silicon SFT plan. It is not a GPU OCI
launch, not NativeProcessRuntime, and not M2 close.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative.

## Document

`kind` is `MacMpsTrainingPlan`. Fields are a single pinned shape:

| Field | Value |
|---|---|
| `backendId` | `ms-swift` |
| `backendVersion` | `4.5.2` |
| `model` | `Qwen/Qwen2.5-0.5B-Instruct` |
| `modelRevision` | `7ae557604adf67be50417f59c2c2f167def9a775` |
| `modelType` | `qwen2` |
| `template` | `qwen2_5` |
| `dataset` | `data/sft.jsonl` |
| `tunerType` | `lora` |
| `torchDtype` | `float32` |
| `accDevice` | `mps` |
| `maxSteps` | `20` |
| `perDeviceTrainBatchSize` | `1` |
| `maxLength` | `256` |
| `outputDir` | `output` |
| `seed` | `42` |

Other backends, revisions, step counts, dtypes, or extra fields MUST fail
closed. The generated JSON Schema is
`schemas/mac-mps-training-plan/v0alpha1.schema.json`.

The GPU `TrainingBackendPlan` MUST stay unchanged (`maxSteps: 1`,
`bfloat16`, `outputDir: /work/output`, ModelScope dataset id).

## Receipts

`researchos training plan REQUEST --format json` MUST print
`TrainingBackendPlanReceipt` with argv starting `swift sft`,
`--max_length 256`, `--model_type qwen2`,
`--template qwen2_5`, `--add_version false`, and `executed: false`.
Argv MUST NOT pass `--device_map mps` (PyTorch 2.14 Metal deadlock).
The command MUST NOT start a process.

`researchos m2 mps CORPUS DATABASE` MUST authorize `execute.mps`, lease
`macos-mps-process`, run the native argv, collect output into CAS, and
record `work.completed`. A stub interpreter is allowed in ordinary
pytest. A live extras interpreter (`RESEARCHOS_MPS_PYTHON`) MUST probe
MPS and MUST fail `mps-unavailable` on CPU.

## Isolation

Declared isolation is `process-group`: POSIX process group, environment
allowlist, closed workspace cwd, `HF_HUB_OFFLINE=1` and related flags,
`TMPDIR=/tmp`, 1800 s wall. The live environment artifact MUST include
`sitecustomizeDigest`. The profile MUST NOT claim namespaces, cgroup,
seccomp, OCI mounts, or NativeProcessRuntime.

## Resume and collect

`researchos training overlay REQUEST --resume full-checkpoint --checkpoint
output/checkpoint-10` MUST add `--resume_from_checkpoint` and declare
loads `weights`, `optimizer`, `scheduler`, `rng`, `global_step`.
Live evidence MUST record before/after file digests. An unchanged RNG
digest is `file-present-digest-unchanged`, not a substitute for a missing
file. `--resume adapter-only` MUST add `--adapters` only. Overlay changes
`commandDigest`.

`researchos training collect OUTPUT --artifacts DIR --profile mps` MUST
put regular files into CAS with a 256 MiB / 64 file bound and verify
digests. `--profile gpu` keeps the 1 MiB bound.

## Conformance

```bash
uv run pytest tests/test_worker_mps.py tests/test_training_backend.py
uv run researchos m2 mps examples/m2-mps-checkpoint /tmp/m2-mps.db --format json
```

Live hardware: [extras/ms-swift-mps/README.md](../../extras/ms-swift-mps/README.md).
GitHub Actions MUST NOT set `RESEARCHOS_MPS_REQUIRED=1`.
