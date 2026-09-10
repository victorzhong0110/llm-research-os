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

Next restore, if issued, is `grant.wsl.cuda.8` with a new run/attempt
and the overlay `commandDigest`.
