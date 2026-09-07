# M2 GPU execution-chain acceptance (not M2 close)

Issue #38 stays open. This document is the integration checklist for the
GPU execution-chain stage. It does **not** merge PRs, cut a tag, close a
milestone, spend GPU, or claim CUDA training.

Working language is English. Chinese shop-window: `README.zh-CN.md`.

Baseline: PR [#65](https://github.com/victorzhong0110/llm-research-os/pull/65)
`dc662e4`. `origin/main` at the start of this stage was `17651b1`.

## 1. PR / SHA stack (merge in this order; do not auto-merge)

Each slice carries the upstream fix. Do not land only the tip.

| Order | PR | SHA | Base | Slice |
|---|---|---|---|---|
| 0 | [#65](https://github.com/victorzhong0110/llm-research-os/pull/65) | `dc662e4` | (prior M2) | GPU experiment sheet (unpaid) |
| A | [#66](https://github.com/victorzhong0110/llm-research-os/pull/66) | `4abe1de7771da721339a033560b83bdc71b79b54` | #65 | Process observation `running` / `exited` / `unknown` |
| B | [#67](https://github.com/victorzhong0110/llm-research-os/pull/67) | `238d926a5c4db72a33ebd4310ba1bc6b960e97c2` | #66 | Live OCI cancel / timeout / kill / inspect |
| C | [#68](https://github.com/victorzhong0110/llm-research-os/pull/68) | `384b264726fb25a0ec3f93d97c814f6f7d84ad40` | #67 | Independent `gpu-oci-container` / `execute.gpu` |
| D | [#69](https://github.com/victorzhong0110/llm-research-os/pull/69) | `9abdc4586df835052e98282fb36519bc2d915051` | #68 | Snapshot, overlay resume, bounded CAS collect |
| E | [#70](https://github.com/victorzhong0110/llm-research-os/pull/70) | `8e2059a80dbd9e92161500fb1a9143ee5278b085` | #69 | Two-root pack; `secondHost: not-provisioned` |
| F | this branch | (this commit) | #70 | This checklist |

Required CI on the **tip after merge** (not a substitute for the rows
below): `uv run pytest --cov=llm_research_os --cov-fail-under=85` and
designated `Linux OCI integration` (`pytest -m oci_live` with
`RESEARCHOS_OCI_REQUIRED=1`).

## 2. Authorization, stop, resume, artifact matrix

| Path | What is proven | Evidence | Not proven |
|---|---|---|---|
| Plan authorization | `execute.gpu` is distinct from `execute.oci`; CPU OCI allow-list rejects `device` | `tests/test_worker_gpu.py`; ADR-0056 | Paid grant on a 4090 |
| GPU launch object | Device `nvidia.com/gpu=0` → `--gpus device=0`; network `denied`; `/work/output` bind not tmpfs; no `privileged` / extra mounts | `researchos training bind`; ADR-0056 | Container start |
| Worker lease | `gpu-oci-container` + advertised `cuda`; `oci-container` cannot lease GPU work | `test_oci_container_worker_cannot_lease_gpu_work` | Live CUDA Worker |
| Process stop | Failed `/proc`/`ps` is `unknown`; group children must exit; unverified start token is not signaled | ADR-0054; `tests/test_worker_supervise.py` | GPU process group |
| CPU live stop | Cancel / timeout / Worker kill / control-plane restart / disconnect-after-upload assert host pid | ADR-0051; `tests/test_worker_live_faults.py` | GPU |
| OCI live stop | Cancel, timeout, Worker SIGKILL, control-plane restart, external `docker stop`, inspect failure, second client while alive | §3 | GPU container |
| Resume overlay | `full-checkpoint` loads weights, optimizer, scheduler, RNG, `global_step`; `adapter-only` loads adapter weights only; new `commandDigest` | `researchos training overlay`; ADR-0057 | CUDA `--resume_from_checkpoint` |
| Artifacts | Persistent `/work/output` collect, digest verify, interrupt resume; 1 MiB / 32 files | `researchos training collect`; CPU fixture | Real LoRA bytes (CAS bound) |
| Snapshot | HF model `7ae557604adf67be50417f59c2c2f167def9a775`; dataset git SHA `pending-live`; `fetched: false` | `examples/m2-gpu-checkpoint/data-binding.json` | Live Hub download |

`cancel-observed` requires enough exit evidence. Inspect failure is
`execution-unobserved`, not `cancel-observed`. Cloud instance 关机 is
researcher-console only.

## 3. Linux OCI success and fault evidence

Designated job: GitHub **Linux OCI integration**,
`RESEARCHOS_OCI_REQUIRED=1`, `pytest -m oci_live`. A skip is a fail.

| Combo | Run | Result |
|---|---|---|
| PR #67 / `238d926` | [run 34165589419](https://github.com/victorzhong0110/llm-research-os/actions/runs/34165589419) job `101875870216` | `8 passed, 1139 deselected in 29.00s`; env `RESEARCHOS_OCI_REQUIRED: 1` |
| PR #68 / `384b264` | [run 34166893335](https://github.com/victorzhong0110/llm-research-os/actions/runs/34166893335) job `101879618991` | `8 passed, 1170 deselected in 28.01s` |

Cases in that 8:

1. `tests/test_worker_oci.py` live success brick
2. `test_live_oci_running_cancel_stops_container_then_reconciles`
3. `test_live_oci_timeout_removes_container_stays_unknown`
4. `test_live_oci_killed_worker_leaves_container_recovery_does_not_spawn`
5. `test_live_oci_control_plane_restart_keeps_container_then_observes_cancel`
6. `test_live_oci_external_stop_is_observed`
7. `test_live_oci_inspect_failure_stays_unknown`
8. `test_live_oci_recovery_while_container_alive_does_not_spawn`

This Darwin developer host has no docker: local `oci_live` is skip. That
skip is not designated-CI acceptance.

PR #66 Linux OCI also passed (process-observation stack, before the
fault file). Do not use unit-test counts or coverage percent as OCI
evidence.

## 4. Cross-machine

**pending-live.** No second machine was provisioned. Pack:

```bash
uv run researchos workers pack /tmp/remote-worker-pack \
  --url https://192.0.2.10:8443 \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal
```

`STATUS.json`: `crossMachine: pending-live`, `secondHost: not-provisioned`,
`sharedRootsForbidden: true`. Control EventStore/CAS/workdir ≠ Worker CAS.
Worker copy has CA only. See [m2-cross-machine.md](m2-cross-machine.md).
Loopback isolate tests are not this row.

## 5. GPU execution code and image

| Item | Status |
|---|---|
| Runtime / capability | `gpu-oci-container` / `execute.gpu` in tree; `execute_gpu_training` returns `gpu-not-run` |
| Image method | `examples/m2-gpu-image` (CUDA 12.4 + `ms-swift==4.5.2`); identity is post-build `sha256:` |
| Image digest | TBD until `docker build` / `inspect` on an approved host |
| Help-check | `RESEARCHOS_GPU_IMAGE_BUILD=1 sh examples/m2-gpu-image/verify.sh` runs `swift sft --help` without `--gpus`; designated OCI CI must not set that flag |
| Training deps | Stay out of core `uv.lock` |

This is not a CUDA result.

## 6. Single-approval GPU experiment sheet

The only paid-run approval document is
[m2-gpu-experiment.md](m2-gpu-experiment.md). One 开 covers that sheet
only.

| Gate | Value |
|---|---|
| Environment | AutoDL RTX 4090 24GB, Ubuntu, `gpu-oci-container`, digest-pinned image |
| Cost cap | Record `budget.limit.recorded` **¥20.00 CNY** before boot |
| Envelope | Charter M2 ¥1000 remaining until a recorded consume |
| Stop billing | After observe: AutoDL **关机** ends instance billing; paid data disk still bills until 缩容/释放. Worker MUST NOT stop the cloud instance |
| Wall | 45 minutes (2700 s profile) |
| Acceptance | Sheet list: grant, `work.completed` with `checkpoint-1`, report cites, invoice ≤ ¥20, 关机 |

Until that 开, do not boot, recharge, or start `swift sft`.

## M1 close-out vs M2 still pending

### M1 materials (numbered slices; not Issue #38)

Delivered locally: schema v2, ledger, mock model, evidence import,
OpenAI-compat budget path, static report, `{eventId, sequence}` consume,
question channel, `researchos m1 prove`. ADR-0042. Tag `v0.1.0-m1` is
**not** cut. Issue #38 stays open. JWT launch credentials and public
network defense are not M1-delivered.

### M2 still pending live acceptance

- Paid 4090 run against the experiment sheet
- Two-host Worker (`secondHost` named)
- ModelScope dataset git SHA (now `pending-live`)
- CUDA image `sha256:` after build
- CAS put bound for real LoRA files
- NativeProcessRuntime (not this stage)

Coverage percent and test counts are not substitutes for the rows above.
