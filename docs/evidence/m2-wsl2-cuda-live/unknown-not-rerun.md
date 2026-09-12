# unknown ≠ rerun

No dedicated two-host live grant was run for this rule. Cite existing
tests; do not invent a new fault campaign.

| Test | What it proves |
| --- | --- |
| `tests/test_worker_recovery.py::test_unknown_cannot_be_marked_success_or_rerun` | timeout → `attempt.unknown`; reconcile refuses success/rerun; same lease on poll resume |
| `tests/test_worker_recovery.py::test_cpu_checkpoint_is_inspectable_and_not_an_unknown_rerun` | CPU checkpoint inspect ≠ unknown rerun |
| `tests/test_training_checkpoint.py` overlay of `--resume_only_model` | forbidden; unknown overlay must not auto-rerun |
| `apply_resume_overlay` | overlay is a new argv / `commandDigest` |

Live two-host already proved **reconnect** (completed) and **cancel**
(`cancel-observed`). Those are not the unknown path.

`grant.wsl.cuda.8` claimed, then failed `gpu-mount-forbidden`. It was
**not** polled again. Restore ran as a **new** grant (`grant.wsl.cuda.9`)
after the Worker imported the overlay `gpu.py`.
