# M2 GPU experiment sheet (not executed)

This is a later paid-run checklist. It is **not** a GPU result, **not**
M2 acceptance, and **not** authorization to spend the ¥1000 envelope.

Do not rent a cloud GPU, do not recharge, and do not subscribe in this
slice. `researchos training plan` only prints argv.

Constraint: [ADR-0048](../adr/0048-pinned-ms-swift-adapter.md).
Protocol: [Training backend plan v0alpha1](../protocols/training-backend-plan-v0alpha1.md).

## Combo (pinned, not run)

| Item | Value | Status |
|---|---|---|
| Backend | `ms-swift==4.5.2` (`swift sft`, `--tuner_type lora`) | Parse/plan only |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` | Not downloaded here |
| Data | `AI-ModelScope/alpaca-gpt4-data-en#8` | Not downloaded here |
| Image | OCI digest **TBD** (must be digest-pinned; no floating tag) | External |
| Runtime | `OCIContainerRuntime` + `execute.oci` (ADR-0045) | CPU path exists; GPU image missing |
| Accelerators | Worker must advertise `cuda`; else refuse | Tested on CPU; CUDA not run |
| Environment | CUDA toolkit / GPU SKU **TBD** by the researcher | External |
| Estimated time | Unknown until the named GPU and image exist | Not measured |
| Single-run cost cap | **Unknown**. A request cannot invent a CNY cap. Do not spend ¥1000 until the researcher names the invoice path and a recorded `budget.limit.recorded` | Not billed |
| Stop | Lease cancel + local timeout. Cancel request ≠ observed stop (ADR-0046). GPU process signal is external verify | CPU proven; GPU pending |
| Checkpoint / resume | `--save_steps 1` on the planned argv; CPU inspectable checkpoint already proven. GPU restore from adapter checkpoints is external verify. Unknown work MUST NOT auto-rerun or mark success | CPU proven; GPU pending |
| Failure handling | Nonzero exit is `failed`. Timeout/kill/disconnect is `unknown`. CAS without `work.completed` is not success. Reconcile Run/Attempt from facts | CPU proven; GPU pending |

## Command that is allowed now

```bash
uv run researchos training plan \
  examples/training-backend/valid/ms-swift-sft.json \
  --format json
```

Receipt MUST show `executed: false` and `gpu: not-run`.

## External verification remaining

- Live docker engine with a digest-pinned CUDA image that contains
  `ms-swift==4.5.2`
- Named GPU SKU, wall-clock budget, and invoice path
- One recorded CNY cap before any paid call
- Observed stop of a CUDA process (not only a cancel request)
- Restore from an ms-swift checkpoint after `unknown`
- Researcher decision to spend (this sheet cannot mint that)

Until those exist, do not say real training ran and do not close Issue #38.
