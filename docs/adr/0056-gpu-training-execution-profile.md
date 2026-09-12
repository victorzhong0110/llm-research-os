# ADR-0056: Independent GPU training execution profile

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0045, ADR-0048, or ADR-0053. It does not
spend GPU, start `swift sft`, or claim M2 acceptance.

## Context

CPU OCI (ADR-0045) forbids `devices`, `gpus`, `mounts`, and `privileged`,
and caps memory at 256 MiB and wall time at 30 seconds. A GPU training
launch cannot be that shape with the ceilings lifted. The pinned
ms-swift plan (ADR-0048) printed argv only. The experiment sheet
(ADR-0053) named AutoDL 4090 and a 45 minute wall without an execution
adapter.

## Decision

1. **Separate runtime and capability.** `runtime: gpu-oci-container` with
   `execute.gpu` is not `oci-container` / `execute.oci`. A CPU OCI Worker
   MUST NOT lease GPU work. CPU `parse_oci_launch_policy` keeps an
   allow-list and MUST reject `device` and other GPU keys.
2. **Closed GPU launch shape.** Network is `denied`. The only device is
   `nvidia.com/gpu=0`, expressed as docker `--gpus device=0` (never
   `all`). Allowed container mounts are `/work/data` (ro), `/work/model`
   (ro), and `/work/output` (rw bind, not tmpfs). Resource ceilings:
   24 GiB memory, 8 CPU, 512 PIDs, 32 GiB disk declaration, 2700 s wall.
   `privileged`, extra devices, and extra mounts fail closed.
3. **Bind the pinned plan.** Image digest, ms-swift argv, plan JCS
   digest, CAS plan bytes, and the three mount locations are the
   execution object. The container command MUST be `plan_ms_swift`
   argv. `researchos training bind` prints docker argv with
   `executed: false` and `gpu: not-run`.
4. **Worker checks.** Poll requires `gpu-oci-container` plus advertised
   `cuda`. `execute_gpu_training` validates the object and MUST NOT
   start docker. Core CPU paths MUST NOT import `llm_research_os.training`
   (lazy import only on the GPU client branch).
5. **No paid run.** This is not CUDA success. Issue #38 stays open.

## Consequences

- Deleting `workers/gpu.py` leaves the CPU OCI profile unchanged.
- Data snapshot, checkpoint resume overlay, and persistent artifact
  upload remain the next slice.
- Training dependencies stay out of the core lockfile.

## Validation

1. CPU OCI policy rejects `device`. GPU policy rejects `privileged`,
   extra mounts, and `nvidia.com/gpu=1`.
2. Prepared argv uses `--gpus device=0`, bind `/work/output`, and the
   pinned `swift sft` command.
3. A Worker without `cuda` cannot lease GPU work. An `oci-container`
   Worker cannot lease `gpu-oci-container` work.
4. `execute_gpu_training` returns `gpu-not-run`. Importing the Worker
   client does not load the training adapter.

## References

- [ADR-0045](0045-cpu-oci-container-runtime.md)
- [ADR-0048](0048-pinned-ms-swift-adapter.md)
- [ADR-0053](0053-gpu-experiment-sheet.md)
- [Training backend plan v0alpha1](../protocols/training-backend-plan-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
