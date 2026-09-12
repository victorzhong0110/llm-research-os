# cuda.10 restore attempt (failed; not retried)

Issue [#38](https://github.com/victorzhong0110/llm-research-os/issues/38)
stays open. PR [#73](https://github.com/victorzhong0110/llm-research-os/pull/73)
is not merged. Original cuda.7 / cuda.9 CAS JSON and seq 1–142 are
unchanged.

This was the one authorized minimal restore: frozen checkpoint-10,
new task `task.gpu.restore12`, new grant `grant.wsl.cuda.10`, output
`/root/researchos/gpu/output-resume-12`, plan pair `maxSteps=12` /
`saveSteps=2`. It did **not** load optimizer / scheduler / RNG. It did
**not** write checkpoint-12.

## Runtime identity (before `workers run`)

Independent venv of `6e601150dd7fff8d654fbed9954b55353915a794`, not a
symlink onto e47279d, `PYTHONPATH` unset.

| Layer | Identity |
| --- | --- |
| Source commit | `6e601150dd7fff8d654fbed9954b55353915a794` |
| WSL tree | `/root/researchos/src-6e601150dd7fff8d654fbed9954b55353915a794` |
| Python | that tree’s `.venv` 3.12.14 |
| `gpu.py` | `sha256:3bd87a7c7719dc8831c8f3d6294ade651baaf8fffcdc40fd54835fa856136d21` |
| `gpu_restore_observe.py` | `sha256:9b921d4f0d4325ef04f884c439119a92e87028df6ede85c7d45d4be1bede2c9f` |
| Image | `sha256:78a31edde58ca329c3b4d769bc020917b45afa41c8ff4eb9de594ca24b75b151` |
| Source checkpoint-10 adapter | `sha256:3a0260a51c22347a09e69cfaa046f3727fde3a5da800ac2cebea65d3bf78a4d5` |

Receipts: [cuda10-preflight.json](cuda10-preflight.json),
[cuda10-code-identity.json](cuda10-code-identity.json).

## Control plane

Seq **143–153** appended after the 142-event freeze.

| Seq | Event |
| --- | --- |
| 144 | `authorization.grant.recorded` `grant.wsl.cuda.10` |
| 149 | `work.queued` `task.gpu.restore12` |
| 151 | `work.claimed` |
| 152 | `authorization.grant.consumed` |
| 153 | `work.failed` `reasonCode=worker.brick.failed` |

Lease was consumed. Do not reuse this grant. Do not treat this as
`unknown` or as a rerun of cuda.9.

## What broke

Container `3b9e226bde7e` exit 1, not OOM. ms-swift 4.5.2 loaded the
local 0.5B model and the 32-row dataset, then:

```text
PermissionError: [Errno 13] Permission denied: '/work/output/args.json'
```

Host mode after `_prepare_gpu_output_root`: output root `775 root:root`,
checkpoint-10 `777 nobody:nogroup`. Container user is `65534:65534`.
It can read the frozen checkpoint and cannot create `args.json` next to
it. Full log: [cuda10.docker-log.txt](cuda10.docker-log.txt). Host listing:
[cuda10-host-state.json](cuda10-host-state.json),
[cuda10.output-mode.txt](cuda10.output-mode.txt).

No `logging.jsonl`. No `researchos-restore-observe.jsonl`. No
checkpoint-12. Trainer load hooks never ran.

A first `workers run` hit `http-disconnect` because the live serve
certificate was minted with `-days 1` (notAfter 2026-09-10T18:48:55Z).
That attempt did **not** claim the lease. The cert was rotated; the
claimed run above is the training attempt. Grant 10 is consumed-failed.

## What this does not change

- cuda.7 first-train and checkpoint upload stay as previously recorded.
- cuda.9 overlay completion and honest partial restore reading stay as
  [cuda9-report-correction.md](cuda9-report-correction.md).
- CPU two-host, reconnect, cancel: reused, not rerun.
- Restore charter row is still **not** a verified optimizer / scheduler /
  RNG load.

No second grant. No merge. No close of #38.
