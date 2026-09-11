# CUDA grants (do not reuse)

| Grant | Lease | Terminal |
| --- | --- | --- |
| `grant.wsl.cuda.1` | none | revoked seq 37 (alpine image Id) |
| `grant.wsl.cuda.2` | failed | `worker.brick.failed` — missing `model.safetensors` |
| `grant.wsl.cuda.3` | failed | output mode / UID 65534 EACCES |
| `grant.wsl.cuda.4` | failed | `HOME=/nonexistent` EROFS under `--read-only` |
| `grant.wsl.cuda.5` | failed | Triton missing `Python.h` |
| `grant.wsl.cuda.6` | failed | tmpfs default `noexec`, JIT `.so` mmap |
| `grant.wsl.cuda.7` | completed seq 116–118 | 20-step LoRA; report `sha256:9da93e29…ea76` |
| `grant.wsl.cuda.8` | failed seq 129 | `gpu-mount-forbidden` — shared `.venv` imported e47279d `gpu.py`; `resume`/`checkpoint` treated as unknown keys. Grant consumed; **not rerun** |
| `grant.wsl.cuda.9` | completed seq 140–142 | full-checkpoint overlay from `/work/output/checkpoint-10`; report `sha256:b1c3527d…ab0c` (historical `restore.status=verified`; honest reading is **partial**, see [cuda9-report-correction.md](cuda9-report-correction.md)) |
| `grant.wsl.cuda.10` | failed seq 153 | new task `task.gpu.restore12`; 10→12 overlay; independent venv of `6e60115`; container exit 1 writing `/work/output/args.json` (root `775`). No observe JSONL. **Not retried.** See [cuda10-failure.md](cuda10-failure.md) |
| `grant.wsl.cuda.11` | completed seq 164–166 | new task `task.gpu.restore12b`; output `output-resume-12b`; independent venv of `b7d960c`; Trainer load hooks `phase=loaded` for optimizer/scheduler/rng; checkpoint-12. See [cuda11-success.md](cuda11-success.md) |

Do not reuse 1–11.
