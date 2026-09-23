# M3 evidence and acceptance matrix

Status: **R01 integrated in #84 at `7d1bcbe`; R02 integrated in #105 at `9fb8f514` and accepted in its scoped application-service contract.**
Canonical package definitions: [M3 plan](../../plans/m3-development-plan.md).
Ownership and review: [development governance](../../development-governance.md).

## Recording rules

Implementation, integration, verification, and acceptance are separate columns.
Implementers append candidate evidence in their package PR. After integration,
record the actual merge SHA and main CI result; acceptance requires review of the
specified scope. Do not predict a future merge identity or call CI success live
acceptance. Record exact commands, platforms, input/build/runtime identities,
outcomes, limitations, and links. Supersede old records explicitly rather than
rewriting them. Evidence is collected with every package, not deferred to R16.

A package may be implemented and merged while a required real-host check remains
pending-live. That does not complete its live acceptance or checkpoint. A skip,
Mock, config file, or local test cannot substitute for the missing evidence.

## Work-package ledger

| Package | Scope | Implementation / integration | Verification / acceptance | Evidence |
| --- | --- | --- | --- | --- |
| R01 | Scope, capability state, and acceptance baseline | Merged in #84 at `7d1bcbe0c956e0fd7d7ce98f07b6c42c8439cc47` | Maintainer-directed integration; post-merge CI passed | [Plan](../../plans/m3-development-plan.md), [governance](../../development-governance.md), [ADR-0064](../../adr/0064-planning-and-implementation-ownership.md); [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35452438029) |
| R02 | Shared application services | Merged in #105 at `9fb8f5142bb18adffa1423e96ecf2ca43f650432` | Scoped review accepted after P1 fixes; [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35810232891) passed | [R02 integration](#r02-integration-and-scope), [candidate history](#r02-candidate-evidence) |
| R03 | Real native execution contract | Planned | Not yet accepted | Add scoped evidence with R03 |
| R04 | Verifiable code and runtime environment | Planned | Not yet accepted | Add scoped evidence with R04 |
| R05 | Real native execution through the Worker lifecycle | Planned | Not yet accepted | Add scoped evidence with R05 |
| R06 | Cancellation, observation, and crash recovery | Planned | Not yet accepted | Add scoped evidence with R06 |
| R07 | SSH onboarding and doctor | Planned | Not yet accepted | Add scoped evidence with R07 |
| R08 | Two-host artifact transfer and fault acceptance | Planned | Not yet accepted | Add scoped evidence with R08 |
| R09 | Local API and browser authority boundaries | Planned | Not yet accepted | Add scoped evidence with R09 |
| R10 | Read-only research workbench | Planned | Not yet accepted | Add scoped evidence with R10 |
| R11 | Browser approval, execution, cancellation, and restore | Planned | Not yet accepted | Add scoped evidence with R11 |
| R12 | AI proposals, citations, and researcher decisions | Planned | Not yet accepted | Add scoped evidence with R12 |
| R13 | Real evaluation, comparison, and conclusions | Planned | Not yet accepted | Add scoped evidence with R13 |
| R14 | Minimal extension mechanism and permission boundary | Planned | Not yet accepted | Add scoped evidence with R14 |
| R15 | Installation, startup, backup, and recovery | Planned | Not yet accepted | Add scoped evidence with R15 |
| R16 | Independent trials and phase acceptance | Planned | Not yet accepted | Add scoped evidence with R16 |

## Checkpoints

| Checkpoint | Packages | Required evidence |
| --- | --- | --- |
| A | R02–R06 | Real local task, authorized launch/denial, artifacts, actual stop, and crash recovery |
| B | R07–R08 | New authorized two-host native execution, verified transfers, reconnect/cancel/unknown faults |
| C | R09–R13 | Browser proposal/decision/execution and recomputable real evaluation with human conclusion |
| D | R14–R16 | Extension boundary, clean install/restore, independent trials, and scoped closure review |

## Preserved historical acceptance

| Capability | Accepted or verified scope | Canonical evidence |
| --- | --- | --- |
| M1 offline research loop | Accepted offline behavior; no live-model inference | [ADR-0062](../../adr/0062-m1-m2-acceptance-and-m3-boundary.md), [wheel smoke](../m1-m2-maintenance/wheel-smoke.json) |
| Local host-Python helper | Verified unit/loopback helper only | Existing `tests/test_worker_protocol.py`; not generic native entrypoint acceptance |
| CPU OCI | Designated Linux OCI CI and accepted WSL2/Docker path | [ADR-0055](../../adr/0055-live-oci-fault-acceptance.md), [M2 matrix](../m2-wsl2-cuda-live/m2-closure-matrix.md) |
| WSL2/Docker two-host CPU/CUDA/restore | Accepted live at original recorded identities; cuda.9 partial, cuda.10 failed, cuda.11 full-state restore | [M2 matrix](../m2-wsl2-cuda-live/m2-closure-matrix.md), ADR-0062 |
| macOS/MPS LoRA | Separate scoped live profile; not generic native execution | [MPS guide](../../guides/m2-mps-acceptance.md), [live receipt](../../../examples/m2-mps-checkpoint/live-evidence.json), ADR-0062 |
| #81 fixed native noop | Merged, CI-verified helper/refusal; real entrypoint not executed | [ADR-0063](../../adr/0063-m3-native-process-runtime-slice-1.md), `tests/test_native_process_runtime.py` |
| #81 SSH pack | Merged validator/writer tests; actual SSH onboarding/execution pending-live | ADR-0063, `tests/test_native_ssh_onboard.py` |

These records remain valid within their original scope and SHA. They are not
relabelled as unverified because a different platform or a newer runtime has not
been exercised. They also do not supply the new native two-host proof for R08.
Keep `docs/status.json` historical baseline/evidence identities distinct from
per-package implementation and live-runtime identities.

## R02 candidate evidence

Scope: shared application services only. This section preserves evidence
recorded while R02 #105 was an open candidate; the integration identity and
scoped acceptance are recorded below. These pre-merge checks do not prove a
live-host native execution path. No pending-live check is required for R02.
Schema v2 was not migrated; historical event digests are not rewritten.

Commands, run from the repository root on the implementation host:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run pytest --cov=llm_research_os --cov-fail-under=85`
- `uv run researchos schema --check-all`
- `node conformance/digest/verify.mjs`
- `uv build`

Package tests: `tests/test_application_service.py`. They cover CLI/Python
semantic equality, receipt restart, content conflict, stale head and revision,
cross-project refusal, overlapping control/Worker roots, duplicate-run
simulation, decision receipts linked to facts and CAS digests, import
without training extras, duplicate event-id recovery, `expectedHead` at the
decision append and at the first simulation write, and one frozen snapshot
for spec, decision, simulation request, and registry inputs.

Historical implementer report at `a15b106d4fd211f4c6aaa16d92ae859f0b5de390`, after the
simulation `expectedHead` follow-up:
`ruff check`, `ruff format --check`, and `mypy src` passed;
`pytest tests/test_application_service.py tests/test_run_control.py tests/test_simulated_runtime.py`
passed 106 tests. `pytest --cov=llm_research_os --cov-fail-under=85` passed
1458 tests, failed 1, and skipped 10. The failure is
`tests/test_m2_perf.py::test_perf_baseline_100k_keeps_report_lineage_short`
(`append_seconds` 213.72 against a 180 second bound). That test is marked
`slow` and is outside the CI selector `not oci_live and not slow`. Coverage
was 20831/24418 = 85.310017% (`scripts/check_coverage.py` passed). Ten
existing OCI tests were skipped because this host has no OCI runtime. That
skip is not R02 live evidence and does not replace the designated OCI job.
`researchos schema --check-all`, `node conformance/digest/verify.mjs`
(13 vectors), `event_catalog.py --check`, and `project_status.py --check`
passed. `uv build` was not re-run; packaging inputs were unchanged.
Outcomes belong to the PR head, not to the later merge commit.

## R02 integration and scope

PR [#105](https://github.com/victorzhong0110/llm-research-os/pull/105) was
squash-merged into `main` at `9fb8f5142bb18adffa1423e96ecf2ca43f650432` after the
review follow-up head `9e67f86b26b44873bc2f548d739afb09675718fb`.
The [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35810232891) completed successfully on that merge SHA:
Ubuntu Python 3.12/3.13, macOS Python 3.12/3.13, Linux OCI, and the
forward-compat Python 3.14 job passed; authorship and fork DCO jobs were
skipped for the push event. The corrected tree also passed 147 focused local
tests, `uv build`, lint, type, schema, event catalog, and project-status checks.
The unchanged 100k slow benchmark passed on the corrective tree; an earlier
host run failed its 180-second append bound, while a baseline main rerun passed.
Both outcomes remain historical evidence of host timing variance, without a
claim that R02 caused the earlier timeout.

The planning review accepts R02 within the shared application-service contract:
workspace identity binding, common CLI/Python semantics, durable receipts,
conflict and stale-head refusal, and unchanged EventStore schema v2. It does
not accept real native execution, SSH live operation, browser controls, real
evaluation, or Issue #53 closure. R03 remains a separate work package.

## Issue #53 evidence checklist

Review closure independently when the relevant R03–R06 evidence is integrated:

- Plan-bound valid authorization consumed before real native user code starts.
- Denial for wrong/stale/substituted bindings and required expiry/revocation cases.
- Durable Run/Attempt/audit outcomes for launch, failure, and uncertain execution.
- Actual cancellation/stop observation and conservative unknown recovery.
- Explicit supported profile/platform limitations and evidence identities.

Add R08 remote evidence for any remote claim. The maintainer reviews closure;
R01 closes nothing, a package merge does not auto-close it, and R16 is not an
additional blanket prerequisite. Ed25519 audit attestations remain distinct from
Worker launch grants. Publication, paid resources, and public-service acceptance
are separate decisions.
