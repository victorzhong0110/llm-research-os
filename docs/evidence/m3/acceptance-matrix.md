# M3 evidence and acceptance matrix

Status: **R01 under review in PR #84; not merged or accepted by this file.**
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
| R01 | Scope, capability state, and acceptance baseline | Documentation proposed in #84; unmerged | Candidate checks; maintainer review pending | [Plan](../../plans/m3-development-plan.md), [governance](../../development-governance.md), [ADR-0064](../../adr/0064-planning-and-implementation-ownership.md); record new head and CI after push |
| R02 | Shared application services | Planned | Not yet accepted | Add scoped evidence with R02 |
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
