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

## Future verification combo (unpinned)

Until a human names an image digest, stop method, and bill, budget for GPU
work stays **unknown**. A request cannot invent a CNY cap. Uncertain
transport after dispatch keeps any reservation (M1-4).

Suggested later combo (not executed here):

| Item | Status |
|---|---|
| Image | OCI digest TBD; do not train against a mutable tag |
| Runtime | `OCIContainerRuntime` behind the same Worker protocol |
| Framework | one pinned training library after the OCI stop/resume loop works |
| Stop | lease cancel + local timeout; cancel request ≠ stopped |
| Bill | unknown until the provider invoice path is named |

`researchos m2 prove` is the CPU stand-in. A Worker without `cuda` MUST NOT
claim `requiredAccelerators: ["cuda"]`. That refusal is tested. CUDA itself
is not run. CPU OCIContainerRuntime (ADR-0045) is the digest-pinned docker
adapter; it is not this GPU slice.

## Event volume

Heartbeats MUST NOT enter the EventStore (ADR-0041). Per-step training
metrics belong in artifacts; events cite digests. M2-0 does not claim
10k/100k event append latency. `WorkerControl` still folds from sequence 0
(Θ(N²) fill). Do not write a training-step fact per optimizer step.
