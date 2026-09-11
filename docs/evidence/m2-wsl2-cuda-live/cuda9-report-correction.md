# cuda.9 report correction (original bytes unchanged)

CAS object `sha256:b1c3527d6bb4053a85dfbd95cb51011bf0158ce8b6172ff41e87dd64c5d5ab0c`
is `evt.work.completed.lease.grant.wsl.cuda.9` seq 140. Do not rewrite
that event. The live Worker imported overlay `gpu.py`
(`PYTHONPATH`, SHA-256 `ea573935…8932`); that is not a later HEAD.

Host observation: [cuda9-restore-host.json](cuda9-restore-host.json),
[cuda9-host-observation-supplement.json](cuda9-host-observation-supplement.json).

## What the original JSON claimed

- `restore.status: verified`
- `restore.loads`: weights, optimizer, scheduler, rng, global_step
- `restore.loadBasis: argv --resume_from_checkpoint`
- `restore.fromStep: 10`, `toStep: 20`
- `parametersUpdated: true`
- checkpoint-20 adapter
  `sha256:9d5ec47068c05809c4fb23f8d9e3d624e3c1279b10308edc6cd355b099c8ff58`

Those `loads` were the overlay **request** (argv). The reporter treated
argv + `fromStep < toStep` as a full restore.

## Honest reading of the same run

| Item | Status | Basis |
| --- | --- | --- |
| Restore executed (overlay) | yes | grant `resume: full-checkpoint`; `args.json` `resume_from_checkpoint=/work/output/checkpoint-10` |
| `requestedLoads` | weights, optimizer, scheduler, rng, global_step | overlay argv |
| `observedLoads.global_step` | **verified** | `logging.jsonl` first marker `11/20` ([cuda9-restore-host.json](cuda9-restore-host.json), supplement) |
| `observedLoads.weights` | **verified** | source checkpoint-10 adapter `sha256:3a0260a51c…a4d5` ≠ this-run checkpoint-20 adapter `sha256:9d5ec470…ff58`; checkpoint-20 `trainer_state.json` mtime is after checkpoint-10 (copy from freeze) and matches the new `logging.jsonl` / root `args.json` window |
| `observedLoads.optimizer` | **unverified** | no “loading optimizer” (or equivalent) line in `logging.jsonl` |
| `observedLoads.scheduler` | **unverified** | no framework scheduler load log |
| `observedLoads.rng` | **unverified** | no framework rng load log |
| Overall `restore.status` | **partial**, not `verified` | argv + step growth are not enough |
| Leftover checkpoint-20 | **not leftover** | mtime of resume `checkpoint-20` is new vs freeze-copied `checkpoint-10`; identical adapter SHA vs cuda.7 frozen checkpoint-20 is deterministic resume, not a pre-copied product |
| Code identity | overlay + `PYTHONPATH` | [code-identity.md](code-identity.md); not HEAD |

No restore loads were observed on this document's cuda.9 runtime.
`grant.wsl.cuda.10` was later issued for Trainer-load observation and
**failed** before those loads ([cuda10-failure.md](cuda10-failure.md)).
The leftover-vs-this-run question for cuda.9 is settled by existing host
mtimes and logging markers. Optimizer/scheduler/rng on cuda.9 stay
unverified.
