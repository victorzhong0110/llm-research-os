# M3 evidence and acceptance matrix (stub)

Status: **Stub** published by R01. Per-package rows are added as each
R02–R16 package lands. Do not edit prior package rows without an
explicit acceptance record.

This matrix enumerates the R02–R16 packages from
`docs/plans/m3-development-plan.md`. Its purpose is to give future R14
external trials and the R16 closure ADR a single reference. The pre-M3
evidence pointers (`docs/evidence/m1-m2-maintenance/`,
`docs/evidence/m2-wsl2-cuda-live/`) and the merged slice 1 records
(`#81`) remain canonical for their packages.

## How a row is added

A package's row is added in the same PR that ships the package (or in
the R15 publication PR). A row cites:

- the merged commit on `main` after the package lands;
- the test/CLI/entry-point path that proves each acceptance bullet;
- the related evidence pack under `docs/evidence/m3/`, with a distinct
  implementation SHA versus accepted-evidence SHA.

The R01 row is the plan file itself, since R01 is documentation only.

## Stub rows

| Package | Plan entry | Status | Per-package evidence | Notes |
| --- | --- | --- | --- | --- |
| R01 | Scope freeze + current entrypoints | merged via this PR | `docs/plans/m3-development-plan.md`; `docs/evidence/m3/acceptance-matrix.md`; `docs/status.json` (NativeProcessRuntime row text); `CONTRIBUTING.md`/`.zh-CN.md`; `docs/guides/first-experiment.md`; `README.md`/`.zh-CN.md` (link list); `CHANGELOG.md` (Unreleased) | Documentation only; no runtime code merged |
| R02 | Application services | planned | (filled by R02 PR) | — |
| R03 | Web API | planned | (filled by R03 PR) | — |
| R04 | Read-only UI | planned | (filled by R04 PR) | — |
| R05 | Native profile contract | planned | (filled by R05 PR) | Builds on the merged slice 1 profile-free execution |
| R06 | NativeProcessRuntime + `#53` | planned | (filled by R06 PR) | Closes `#53` |
| R07 | SSH onboarding | planned; pack writer merged via `#81` | (filled by R07 PR) | Flips `STATUS.json` from `pending-live` to `live` |
| R08 | Two-host faults | planned | (filled by R08 PR) | — |
| R09 | Research workflow + AI proposal | planned | (filled by R09 PR) | — |
| R10 | Web execution, cancel, restore | planned | (filled by R10 PR) | — |
| R11 | Minimal real evaluation | planned | (filled by R11 PR) | Recommended addition accepted in R15 |
| R12 | Extension boundary | planned | (filled by R12 PR) | — |
| R13 | Packaging, startup, diagnostics | planned | (filled by R13 PR) | — |
| R14 | External trials | planned | (filled by R14 PR) | Two audience-matching trials; one with SSH |
| R15 | Evidence index publication | planned | (filled by R15 PR) | Aggregates this matrix; updates generated status |
| R16 | Closure ADR + publication gate | planned | (filled by R16 PR) | Decides accept/defer; never publishes by itself |

## Pre-M3 evidence

| Acceptance | Path | Notes |
| --- | --- | --- |
| M1 offline checkpoint | `docs/evidence/m1-m2-maintenance/wheel-smoke.json` and `tests/test_m1_checkpoint.py` | ADR-0062 |
| M2 WSL2 + Docker local/two-host | `docs/evidence/m2-wsl2-cuda-live/m2-closure-matrix.md` | ADR-0062; cuda.11 only |
| M2 mac/MPS LoRA | `docs/evidence/m1-m2-maintenance/` and the WSL acceptance matrix | LoRA process-group profile only |
| M3 slice 1 noop helper | `tests/test_native_process_runtime.py`; ADR-0063; TM-064 | Merged via `#81`; SSH refused; entrypoint not imported |
| M3 slice 1 SSH onboarding | `tests/test_native_ssh_onboard.py`; ADR-0063; TM-065 | Merged via `#81`; pack only; `STATUS.json` stays `pending-live` |

## Constraints carried forward

The matrix does not relax the following inherited constraints:

- Ed25519 attestations (`#78`) are audit evidence, not launch authority.
- HMAC Worker grants (M2-0) remain the trusted launch authority under the
  reviewable expiry / revoke lifecycle.
- OCI, MPS, GPU, and Darwin kernel-namespace claims require their own
  package evidence; merging one package never relabels another.
- Paid cloud spend stays ¥0; first-paid-task criterion from
  `charter §14.5` is not addressed by local acceptance.
- Public MVP and multi-tenant claims remain deferred.

## Pointers for future editors

- Use exact, minimal, scoped diffs. A row cites the PR that delivered it,
  not the matrix-editing commit.
- Preserve `docs/status.json` accepted-evidence identity (`57ffdae`) and
  implementation baseline (`7e5fc33`); matrix SHA is recorded per row.
- The generated status block in `README.md` and `README.zh-CN.md` is
  rendered from `docs/status.json`; do not hand-edit it.
