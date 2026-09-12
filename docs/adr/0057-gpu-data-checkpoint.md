# ADR-0057: Data snapshot and checkpoint artifact loop

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0048, ADR-0053, or ADR-0056. It does not
download Hub weights, start `swift sft`, or claim a GPU resume.

## Context

The GPU profile (ADR-0056) bind-mounts `/work/output` and forbids tmpfs
for training output, but it does not pin Hub revisions, verify an offline
cache, upload checkpoint files into CAS, or distinguish `--adapters` from
`--resume_from_checkpoint`. A 1-step LoRA can still vanish with the
container or be "resumed" as a second spawn.

## Decision

1. **Pin identity separately from the closed plan.** `GpuDataCheckpointBinding`
   records Hugging Face model revision
   `7ae557604adf67be50417f59c2c2f167def9a775` for
   `Qwen/Qwen2.5-0.5B-Instruct`. The ModelScope dataset
   `AI-ModelScope/alpaca-gpt4-data-en` (`#8`) stays `pending-live` until a
   GPU host records its git SHA. Lineage cites Hugging Face
   `vicgalle/alpaca-gpt4` @ `f7e3ded725cb81e8e564e32feb12860f376f2b51`
   (same GPT-4-LLM paper). Optional `contentDigest` is the JCS tree of
   local files.
2. **Offline path does not fetch.** `researchos training snapshot` compares
   local trees, prints prefetch argv, and MUST set `fetched: false`.
   `HF_HUB_OFFLINE=1` / `MODELSCOPE_OFFLINE=1` are operator flags, not
   subprocesses.
3. **Outputs persist then upload with a bound.** Collect walks the host
   directory bound to `/work/output`, puts each regular file into CAS
   (`MAX_PUT_BYTES`, 32 files), and resumes from a prior manifest.
   Symlinks fail closed. This is not tmpfs.
4. **Resume is overlay argv.** `full-checkpoint` adds
   `--resume_from_checkpoint` and loads weights, optimizer, scheduler,
   RNG, and `global_step`. `adapter-only` adds `--adapters` and loads
   adapter weights only. `--resume_only_model` is forbidden. Overlay
   changes `commandDigest` and is a new execution object. Unknown MUST
   NOT auto-rerun.
5. **CPU fixture is not CUDA.** Examples under
   `examples/training-backend/cpu-snapshot` verify the protocol. Receipts
   stay `gpu: not-run`.

## Consequences

- Live Hub snapshots and ModelScope dataset SHA remain `pending-live`
  until recorded on a GPU host after an approved experiment.
- Raising the CAS put bound for real LoRA weights is a later review.

## Validation

1. Sheet binding matches the pinned plan digest; dataset revision is
   `pending-live`; snapshot does not fetch.
2. CPU fixture `contentDigest` values match the committed trees.
3. Overlay argv for full vs adapter differs; loads are explicit.
4. Collect stores `trainer_state.json` / adapter files and resumes after
   an interrupted put.

## References

- [ADR-0048](0048-pinned-ms-swift-adapter.md)
- [ADR-0056](0056-gpu-training-execution-profile.md)
- [Training backend plan v0alpha1](../protocols/training-backend-plan-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
