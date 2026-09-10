# WSL CUDA training plan v0alpha1

Closed `WslCudaTrainingPlan` for Windows/WSL2 + Docker Engine on an
8 GB laptop GPU. Independent of `TrainingBackendPlan` (1-step / 24 GiB
sheet) and `MacMpsTrainingPlan`.

Schema: `schemas/wsl-cuda-training-plan/v0alpha1.schema.json`.

Pinned values:

- `ms-swift==4.5.2`
- model directory `/work/model` at Hub revision
  `7ae557604adf67be50417f59c2c2f167def9a775`
- dataset `/work/data/sft.jsonl` (offline; container network is denied)
- LoRA rank 8, batch 1, `max_length` 256, `max_steps` 20, `save_steps` 10
- `torchDtype: bfloat16`, `accDevice: cuda`
- output `/work/output`

`researchos training plan` / `bind` stay `executed: false`. Live start is
`run_gpu_training` after an `execute.gpu` grant on a Worker that
advertised `cuda`. A full-checkpoint restore is a new execution object:
grant config MAY include `resume: full-checkpoint` and
`checkpoint: /work/output/checkpoint-N` when `commandDigest` is the
overlay argv. File presence in a checkpoint is not a restore.
