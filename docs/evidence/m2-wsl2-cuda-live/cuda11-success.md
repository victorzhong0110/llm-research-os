# cuda.11 restore (10→12, load hooks verified)

Issue [#38](https://github.com/victorzhong0110/llm-research-os/issues/38)
stays open. PR [#73](https://github.com/victorzhong0110/llm-research-os/pull/73)
is not merged. cuda.1–10 are not reused. Seq 1–153 are unchanged.

## Identity

Independent venv of `b7d960c7c78a8c6fbdbdbdc006d50285165e50a6` (not a
symlink onto e47279d). `PYTHONPATH` unset. Probe entrypoint `python3`.

| Layer | Identity |
| --- | --- |
| Source commit | `b7d960c7c78a8c6fbdbdbdc006d50285165e50a6` |
| WSL tree | `/root/researchos/src-b7d960c7c78a8c6fbdbdbdc006d50285165e50a6` |
| `gpu.py` | `sha256:5749a8f7cabe41357415c186dcdc2b927692d72e0df3e9004aad7762b8ea3f40` |
| observe module | `sha256:9b921d4f0d4325ef04f884c439119a92e87028df6ede85c7d45d4be1bede2c9f` |
| Image | `sha256:78a31edde58ca329c3b4d769bc020917b45afa41c8ff4eb9de594ca24b75b151` |
| Output | `/root/researchos/gpu/output-resume-12b` |
| Frozen source | `/root/researchos/gpu/output-cuda7-frozen/checkpoint-10` (untouched, still nobody) |

[cuda11-preflight.json](cuda11-preflight.json),
[cuda11-code-identity.json](cuda11-code-identity.json).

A first `workers run` of `2d55bd7` failed **before claim**
(`gpu-output-unwritable`): the CUDA image has no `python` binary. The
grant stayed queued. `b7d960c` switched the probe to `python3` and
reused `grant.wsl.cuda.11`.

## Control plane

| Seq | Event |
| --- | --- |
| 155 | `authorization.grant.recorded` `grant.wsl.cuda.11` |
| 160 | `work.queued` `task.gpu.restore12b` |
| 162 | `work.claimed` |
| 163 | `authorization.grant.consumed` |
| 164 | `work.completed` report `sha256:ab90b952…a0b3` |
| 165 | `attempt.succeeded` |
| 166 | `run.completed` |

[eventstore-redacted-cuda11.json](eventstore-redacted-cuda11.json).

## Restore evidence

Trainer load-hook JSONL (`phase=loaded`) for optimizer, scheduler, and
RNG, sourced from checkpoint-10, with source digests matching the
frozen cuda.7 files. this-run product is checkpoint-12
(`globalStep=12`). Report:
[cuda11-WslCudaTrainingReport.json](cuda11-WslCudaTrainingReport.json).
Observe log: [cuda11-observe.jsonl](cuda11-observe.jsonl).

Mac `artifacts verify` of the report, observe JSONL, checkpoint-12
adapter, trainer_state, and the frozen checkpoint-10 adapter:
[cuda11-mac-verify.json](cuda11-mac-verify.json). Worker PUT of the new
files: [cuda11-upload.json](cuda11-upload.json).

No merge. No close of #38.
