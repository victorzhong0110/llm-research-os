# Code identity for the live Worker path

Do not cite a single `HEAD` SHA as the cuda.7 environment.

## cuda.7 (completed seq 116–118)

| Layer | Identity |
| --- | --- |
| WSL source tree | `/root/researchos/src-e47279da27289094683259b1a9639b7ccea70dee` |
| Overlay | `src/llm_research_os/workers/gpu.py` from `b3da4bd` (tmpfs `exec`) |
| Image Id | `sha256:78a31edde58ca329c3b4d769bc020917b45afa41c8ff4eb9de594ca24b75b151` |
| Mac serve | repo working tree + uncommitted `http.py` `RESEARCHOS_LEASE_SECONDS` (live value **1800**) |
| Origin after the later push | `b3da4bd5b9753e184aa86731b1ebe699a52788f6` |

`start_serve.sh` exports `RESEARCHOS_LEASE_SECONDS=1800` and runs `uv run`
from the Mac repo. Heartbeats do not extend leases.

## This evidence pack

Report semantics, GPU resume overlay, and the lease env reader belong to
the commit that lands this directory. That SHA is **not** the cuda.7
runtime. A later restore grant must deploy that commit (or an explicit
overlay of it) before `workers run`.
