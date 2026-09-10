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
| `grant.wsl.cuda.9` | completed seq 140–142 | full-checkpoint overlay from `/work/output/checkpoint-10`; report `sha256:b1c3527d…ab0c` |

Next grant, if issued, is `grant.wsl.cuda.10` with a new run/attempt.
Do not reuse 1–9.
