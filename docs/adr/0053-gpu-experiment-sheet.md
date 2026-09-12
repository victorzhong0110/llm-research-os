# ADR-0053: GPU experiment sheet without a paid run

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0010, ADR-0045, or ADR-0048. It does not
spend GPU, rent a machine, or claim M2 acceptance.

## Context

ADR-0048 pinned `ms-swift==4.5.2` parse/plan and left the experiment sheet
with TBD GPU, time, and cap. M2 closeout still needs a named combo a
researcher can approve: SKU, image method, duration, single-run cap,
envelope remainder, instance stop vs container stop, disconnect, and
acceptance. Public price roundups are not invoices. A request cannot
record `budget.limit.recorded` for the researcher.

## Decision

1. **Audit the pin against v4.5.2 docs.** Planned argv uses `--tuner_type`,
   not v3 `--sft_type` / `--train_type`. Extra backends stay forbidden.
2. **Name one unpaid combo.** AutoDL RTX 4090 24GB, 45 minute wall,
   proposed cap ¥20, envelope ¥1000 remaining. Do not boot without a
   recorded cap and an explicit 开.
3. **Image method, not a floating tag.** `examples/m2-gpu-image` builds
   `ms-swift==4.5.2` on a CUDA 12.4 base. Identity is the built `sha256:`
   digest. Default verify is `skipped-no-runtime` or `skipped-no-build`.
   `RESEARCHOS_GPU_IMAGE_BUILD=1` may help-check; it MUST NOT pass `--gpus`
   or train. Designated Linux OCI CI MUST NOT set that flag.
4. **Checkpoint resume is overlay argv.** `--resume_from_checkpoint` on
   `checkpoint-1` with the same plan. Unknown MUST NOT auto-rerun.
5. **Cloud instance stop is researcher-console only.** Worker observes
   process/container stop. AutoDL 关机/释放 is not `docker stop`.

## Consequences

- The sheet can be reviewed without a GPU host.
- Issue #38 stays open until a paid run meets the acceptance list.

## Validation

1. `training plan` argv flags are the v4.5.2 names and `gpu: not-run`.
2. Dockerfile pins `ms-swift==4.5.2`; verify script forbids `--gpus`.
3. Sheet lists GPU, image, duration, cap, envelope, stop, disconnect,
   acceptance, and `gpu: not-run`.

## References

- [ADR-0048](0048-pinned-ms-swift-adapter.md)
- [M2 GPU experiment sheet](../guides/m2-gpu-experiment.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
