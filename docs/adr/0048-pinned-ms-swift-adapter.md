# ADR-0048: Pinned ms-swift adapter without core GPU execution

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0010, ADR-0012, or ADR-0045. It does not
claim M2 acceptance or a real training run.

## Context

Charter M2 asks for one real training-framework adapter (ms-swift is the
provisional choice) that can be deleted without breaking the core or the
generic Python brick. Core dependencies must not include ms-swift, CUDA,
or torch (ADR-0012). This machine has no GPU run in this slice.

## Decision

1. **Pin `ms-swift==4.5.2`.** The closed `TrainingBackendPlan` maps to
   `swift sft` argv using v4 `--tuner_type`. Other backends, versions,
   models, or extra fields fail closed.
2. **Keep the adapter out of the core environment.** Do not add ms-swift
   or torch to core `project.dependencies` or `uv.lock`. Probe uses
   `importlib.util.find_spec("swift")` and MUST NOT import torch.
3. **Parse and plan only.** `researchos training plan` prints argv with
   `executed: false` and `gpu: not-run`. It MUST NOT subprocess.
4. **CPU loop stays independent.** `m2 prove`, `m2 oci`, `m2 bench`, and
   the host-python brick MUST NOT import `llm_research_os.training`.
5. **GPU experiment sheet is not a run.** Environment, model/data, time,
   cost cap, stop, checkpoint, and failure handling are written as a
   later paid-run checklist. Cost stays unknown until a researcher names
   a bill. Do not spend the ¥1000 envelope here.

## Consequences

- Deleting `llm_research_os.training` leaves the CPU Worker loop intact.
- Live ms-swift / CUDA verification remains an external item.
- ADR-0010 stays "direction accepted"; this slice is the parse/plan
  adapter, not M2 validation.

## Validation

1. Valid pinned plan prints `swift sft` argv and `executed: false`.
2. Wrong version, backend, model, or extra field fails closed.
3. AST/import tests show CPU paths do not load the adapter.
4. GPU sheet lists stop, checkpoint, cost, and failure rules without
   claiming a GPU result.

## References

- [ADR-0012](0012-python-and-dependencies.md)
- [Training backend plan v0alpha1](../protocols/training-backend-plan-v0alpha1.md)
- [M2 GPU experiment sheet](../guides/m2-gpu-experiment.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
