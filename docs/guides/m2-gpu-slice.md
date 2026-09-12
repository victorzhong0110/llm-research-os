# M2 GPU slice (direction only)

This is not a paid run. Do not rent a cloud GPU, do not spend the ¥1000
envelope, and do not treat this document as a completed CUDA loop.

M2-0 already carries the fields a later GPU Worker needs:

- Worker `accelerators` advertisement (`cuda` when present)
- Work `requiredAccelerators`
- CAS `imageDigest` (immutable; later an OCI digest, not a floating tag)
- Lease expiry, revoke, idempotent complete
- `attempt.unknown` / `attempt.lost` when stop is requested but outcome is
  not observed

## Named combo (unpaid)

The named sheet is [M2 GPU experiment](m2-gpu-experiment.md) (ADR-0053):
AutoDL RTX 4090, 45 minute wall, proposed ¥20 cap, CUDA image method.
That is a reviewable combo, not a recorded `budget.limit.recorded` and not
开. Cost stays unknown until the researcher records the cap. Uncertain
transport after dispatch keeps any reservation (M1-4).

`researchos m2 prove` is the CPU stand-in. A Worker without `cuda` MUST NOT
claim `requiredAccelerators: ["cuda"]`. That refusal is tested. CUDA itself
is not run. CPU OCIContainerRuntime (ADR-0045) is the digest-pinned docker
adapter; it is not this GPU slice.

## Event volume

Heartbeats MUST NOT enter the EventStore (ADR-0041). Per-step training
metrics belong in CAS metric chunks; events cite digests
([ADR-0047](../adr/0047-eventstore-performance-and-metric-sampling.md)).
Do not write a training-step fact per optimizer step. `researchos m2 bench`
records 10k/100k EventStore timings; those numbers are not SLA.

The pinned parse/plan adapter and the unpaid experiment sheet live in
[M2 GPU experiment](m2-gpu-experiment.md). ADR-0053 names AutoDL RTX 4090,
a 45 minute wall, and a proposed ¥20 cap. That sheet is not a CUDA result.
