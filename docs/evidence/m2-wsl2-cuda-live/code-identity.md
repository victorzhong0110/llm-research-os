# Code identity for the live Worker path

Do not cite a single `HEAD` SHA as the cuda.7 or cuda.9 environment.

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

## cuda.8 (failed seq 129)

A copy of the e47279d tree at
`/root/researchos/src-374f5c6f75d5c51fbca8b993e0eca434ddd63e53` received
the 374f5c6 `gpu.py` overlay, but `workers run` used the **shared
`.venv`**, which still imported e47279d `gpu.py` (`resume` not in
`_GPU_LAUNCH_KEYS`). That grant was failed. It was not retried.

## cuda.9 (completed seq 140–142)

| Layer | Identity |
| --- | --- |
| Overlay `gpu.py` | SHA-256 `ea5739351a1bc6c7c6498015109e64e646a7f68104427177573e1326d0788932` (374f5c6) |
| Import | `PYTHONPATH=/root/researchos/src-374f5c6f75d5c51fbca8b993e0eca434ddd63e53/src` |
| Image Id | same as cuda.7 |
| Mac serve | PID 55566 still on `100.69.150.10:8443`; EventStore 142 after reconcile |
| Overlay `commandDigest` | `jcs-sha256:411120ecc09852a717d43ad1dd53210af86ca9901c496bfa13d5398c3b67901d` |
| `configDigest` | `jcs-sha256:28e9ac5f46f2a3c7a0f017f90af0776dad1d89d93a129c0de3f6e425a333abc8` |

## Independent venv (no grant)

| Layer | Identity |
| --- | --- |
| Source commit (archive) | `041365a4e74d02a5827162c2ebc8e792c850a8fa` |
| WSL tree | `/root/researchos/src-041365a4e74d02a5827162c2ebc8e792c850a8fa` |
| Venv | that tree’s `.venv` (not a symlink; not the e47279d env) |
| `gpu.py` | `/root/researchos/src-041365a4e74d02a5827162c2ebc8e792c850a8fa/src/llm_research_os/workers/gpu.py` SHA-256 `8a69aed235…29ba` |
| PYTHONPATH | unset |
| `workers run` | not started |

Receipt: [independent-venv.json](independent-venv.json). This is not cuda.7, cuda.8, or cuda.9.

## cuda.10 (failed seq 153)

| Layer | Identity |
| --- | --- |
| Source commit | `6e601150dd7fff8d654fbed9954b55353915a794` |
| WSL tree | `/root/researchos/src-6e601150dd7fff8d654fbed9954b55353915a794` |
| Venv | that tree’s `.venv` (not a symlink; not the e47279d env) |
| `gpu.py` | SHA-256 `3bd87a7c7719dc8831c8f3d6294ade651baaf8fffcdc40fd54835fa856136d21` |
| observe module | SHA-256 `9b921d4f0d4325ef04f884c439119a92e87028df6ede85c7d45d4be1bede2c9f` |
| PYTHONPATH | unset |
| `workers run` | yes; grant consumed-failed |

[cuda10-preflight.json](cuda10-preflight.json),
[cuda10-code-identity.json](cuda10-code-identity.json),
[cuda10-failure.md](cuda10-failure.md).

## cuda.11 (completed seq 164–166)

| Layer | Identity |
| --- | --- |
| Source commit | `b7d960c7c78a8c6fbdbdbdc006d50285165e50a6` |
| WSL tree | `/root/researchos/src-b7d960c7c78a8c6fbdbdbdc006d50285165e50a6` |
| Venv | that tree’s `.venv` (not a symlink; not the e47279d or 6e60115 env) |
| `gpu.py` | SHA-256 `5749a8f7cabe41357415c186dcdc2b927692d72e0df3e9004aad7762b8ea3f40` |
| observe module | SHA-256 `9b921d4f0d4325ef04f884c439119a92e87028df6ede85c7d45d4be1bede2c9f` |
| PYTHONPATH | unset |
| `workers run` | yes; grant consumed-completed |

[cuda11-preflight.json](cuda11-preflight.json),
[cuda11-code-identity.json](cuda11-code-identity.json),
[cuda11-success.md](cuda11-success.md).

## This evidence pack

Report semantics, GPU resume overlay, lease env reader, leftover
checkpoint exclusion, and sandbox fail-closed on forbidden GPU config
belong to the commit that lands this update. That SHA is **not** the
cuda.7 or cuda.9 runtime.
