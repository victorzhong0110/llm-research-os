# cuda.7 report correction (original bytes unchanged)

CAS object `sha256:9da93e29a6263aa05aacb7a61cee15a6f34eccd66832b3471805a65f69daea76`
(910 bytes) is `evt.work.completed.lease.grant.wsl.cuda.7` seq 116. Do not
rewrite that event.

## What the original JSON claimed

- `resumeEvidence.optimizer/scheduler/rng: true` with `globalStep: 20`
- `parametersUpdated: true`
- `checkpoint.path: checkpoint-20` and an `adapterDigest`

## What those fields actually measured

`_cuda_training_report` used `_has_any(...)` (file exists) for
`resumeEvidence`, and forced `parametersUpdated: true` whenever there
was only one checkpoint directory. cuda.7 also wrote `checkpoint-10`
(`saveSteps: 10`), so a first-vs-last adapter compare was possible, but
the report did not distinguish “files present” from “restore executed”,
and the single-checkpoint shortcut would have fired on a 20-only tree.

## Correct reading of the same run

| Field | Honest status for cuda.7 |
| --- | --- |
| Training executed | yes (`executed: true`, 20 finite losses) |
| Checkpoint state files present | yes (optimizer / scheduler / rng / trainer_state) |
| Restore executed | **no** — argv had no `--resume_from_checkpoint` |
| `restore.status` | **unverified** |
| `parametersUpdated` | **unverified from the original report**; a later two-checkpoint compare on host files is still pending host SHA256 |

New reports use `resumeEvidence.kind: checkpoint-state-files` and a
separate `restore` object. cuda.7’s JSON stays as a historical fact.
