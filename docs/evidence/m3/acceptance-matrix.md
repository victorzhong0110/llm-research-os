# M3 evidence and acceptance matrix

Status: **R01–R07 integrated; R08 local transfer foundation and HTTPS input/output slices integrated. Checkpoint B is not accepted; freeze after its acceptance and do not start R09.**
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
| R03 | Real native execution contract | Merged in #109 at `1a08bfede3970f9300ba53078d19e6f21a7f8d79` | Reviewed validation-only contract accepted; no live launch | [R03 integration](#r03-integration-and-scope), [candidate history](#r03-candidate-evidence) |
| R04 | Verifiable code and runtime environment | Merged in #111 at `55b72268fcabe02ba0af0e5f1a6f038a515435e4` | Corrected PR CI passed; post-merge main CI not yet cited here | [R04 candidate](#r04-candidate-evidence) |
| R05 | Real native execution through the Worker lifecycle | Merged in #114 at `7abe55c1a8e770a6b0e5a058ea69563edeb7071c` | PR CI passed on Linux/macOS; checkpoint A needs R06 | [R05 candidate](#r05-candidate-evidence) |
| R06 | Cancellation, observation, and crash recovery | Merged in #115 at `62cfad00af76b04a58de27671edf76a1127b0f5a` | [Main CI #258](https://github.com/victorzhong0110/llm-research-os/actions/runs/36695842170) passed; no blanket checkpoint acceptance | [R06 candidate](#r06-candidate-evidence), [integration record](https://github.com/victorzhong0110/llm-research-os/pull/115) |
| R07 | SSH onboarding and doctor | Merged in #116 at `1f8b14226728a3c3c710ea95ea1e3347d40716be` | [Main CI #260](https://github.com/victorzhong0110/llm-research-os/actions/runs/36696795007) passed; authorized-host acceptance pending-live | [R07 candidate](#r07-candidate-evidence), [integration record](https://github.com/victorzhong0110/llm-research-os/pull/116) |
| R08 | Two-host artifact transfer and fault acceptance | Local foundation merged in #117 at `c9e1d3e55e5eb63a597c5cb01460dab76b6ef338`; HTTPS input slice merged in #118 at `65304b0659168d9661dde010ae751c35dedc81b5`; HTTPS output slice merged in #120 at `575a091d41034a758bcac0c4f8bdf737c7157040` | [Main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36850636460) passed for the foundation; [HTTPS input main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36984410531) passed. [HTTPS output main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349) passed. Remote material preparation merged in #122 at `9ae3a0ccd751543fcf1086f9fe530c3d1191e0a0` ([main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37120726534) passed). Remote executor/recovery remain incomplete; two-host and GPU evidence pending-live | [R08 candidate](#r08-candidate-evidence), [review corrections](#r08-review-corrections), [HTTPS input candidate](#r08-https-input-candidate) |
| R09 | Local API and browser authority boundaries | Planned | Not yet accepted | Add scoped evidence with R09 |
| R10 | Read-only research workbench | Planned | Not yet accepted | Add scoped evidence with R10 |
| R11 | Browser approval, execution, cancellation, and restore | Planned | Not yet accepted | Add scoped evidence with R11 |
| R12 | AI proposals, citations, and researcher decisions | Planned | Not yet accepted | Add scoped evidence with R12 |
| R13 | Real evaluation, comparison, and conclusions | Planned | Not yet accepted | Add scoped evidence with R13 |
| R14 | Minimal extension mechanism and permission boundary | Planned | Not yet accepted | Add scoped evidence with R14 |
| R15 | Installation, startup, backup, and recovery | Planned | Not yet accepted | Add scoped evidence with R15 |
| R16 | Independent trials and phase acceptance | Planned | Not yet accepted | Add scoped evidence with R16 |

## R08 HTTPS input candidate

### Integration update (2026-10-02)

PR #118 merged at `65304b0659168d9661dde010ae751c35dedc81b5`.
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36983679149)
and [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36984410531)
passed. The Linux Python 3.12 PR job recorded 1,661 passed, 12 OCI-only deselected,
zero failures/skips, and unrounded statement-plus-branch coverage 85.381944%.
The local fresh locked environment recorded 1,645 passed, 12 namespace/process
observation failures, four skips, 12 deselected and 84.902777% coverage; it did not
pass the CI coverage gate. No skip or threshold was added to hide those failures.
Remote outputs, durable remote staging/execution/recovery, and authorized two-host
and GPU evidence remain incomplete. Checkpoint B is not accepted; R09 is not started.


Base: verified main `c9e1d3e55e5eb63a597c5cb01460dab76b6ef338`, whose
[post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36850636460)
passed. The #117 foundation is integrated; its historical candidate records
below remain historical rather than current integration status.

This slice adds an HTTPS native input endpoint and bounded pinned-TLS client.
Actual recorded Worker grants authorize only immutable planned native
bundle/lock/inventory/input digests. Revoked grants, cancellation and expired
claimed leases refuse downloads. Downloads/replays append no facts and never
claim or launch work. The protocol and residual security boundaries are in
[the input protocol](../../protocols/native-input-transfer-v0alpha1.md) and TM-069.

Local Linux/Python 3.12.14 candidate checks:

- `uv run pytest -q tests/test_native_input_transport.py tests/test_native_transfer_security.py tests/test_worker_isolate.py tests/test_evidence.py` — 69 passed.
- Earlier scoped Worker/protocol/fault/recovery/local-transfer regression — 82 passed before the final cancellation regression was added.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` — passed.
- Schema freshness, event catalog, project status, 13 JCS vectors and `uv build` — passed.

An initial broader run using restored dependencies returned 1641 passed,
15 failed, 4 skipped and 12 deselected, with 84.875% reported coverage. It is
not a passing gate. Three PDF failures came from that restored interpreter
setup and pass in the fresh locked environment; the other failures exercise
AF_UNIX and process observation in this restricted container. Fresh full-suite
results and standard CI must be recorded in the PR before integration.

This is one independently reviewable R08 slice. Remote output upload, durable
remote staging orchestration, remote native launch and full restart/fault
integration are implementation gaps. Authorized two-host and GPU live evidence
are still pending-live. No R08 full acceptance or Checkpoint B closure is claimed.

## R08 HTTPS output candidate

### Integration update (2026-10-03)

PR #120 merged at `575a091d41034a758bcac0c4f8bdf737c7157040`.
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37028030342)
and [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349)
passed all five Python jobs and Linux OCI; PR Human authorship passed. Linux
Python 3.12 recorded 1,697 passed, 12 OCI-only deselected, zero failures/skips,
85.447% reported statement-plus-branch coverage and a passing unrounded gate.
The fresh locked local suite recorded 1,681 passed, the same 12 host namespace/
process-observation failures, four skips, 12 deselected and 84.956% reported
coverage. It did not pass the local coverage gate; no new skips or threshold
changes were added. This records integration, not full R08 or B acceptance.



Base: verified main `6e1e3b0e4fba0776f63e816f55f5a03e4048df2e`, whose
[final main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37021177400)
passed after the project tour and maintenance consolidation. This output slice
is candidate evidence until its PR is merged and main verification is recorded.

The pinned HTTPS output endpoint verifies one canonical native result for an
already consumed, execution-bound lease. Original verified CAS bytes precede
one durable Worker completion; exact replay after acknowledgment loss or
controller restart returns the same fact even after grant expiry/revocation.
Changed output, foreign session/scope, incomplete authorization, cancellation,
insufficient disk, unsafe locks, and missing/damaged completed CAS refuse.
Authorization is rechecked after publication and the EventStore head binds the
final append against concurrent cancellation/revocation. Native HTTP callers
cannot bypass the endpoint through generic artifact upload or completion.
Generated schemas and valid/invalid examples define the output and receipt.
See [the output protocol](../../protocols/native-output-transfer-v0alpha1.md)
and TM-070 for the exact boundaries.

This slice neither launches a process nor appends Run/Attempt lifecycle facts.
The reported full request digest is syntax checked, not independently rebuilt;
full result verification belongs to the controller's execution integration.
Durable remote staging, remote executor/recovery and new authorized two-host
fault evidence remain gaps. Checkpoint B is open, and R09 is not started.
Candidate check results are recorded in the PR before integration.

## R08 bound request context candidate

Base: verified main `575a091d41034a758bcac0c4f8bdf737c7157040` with passing
[main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349).
This slice reconstructs the existing full reviewed request from the exact human
authorization fact, recorded grant and immutable queued execution, and delivers
it over bounded pinned HTTPS without creating authority, claims or facts. The
output endpoint requires its reported request digest to match this full
reconstruction; syntax-only checking of that citation is superseded by this
candidate. Existing execution/configuration and grant semantics are retained.
See [the context protocol](../../protocols/native-request-transfer-v0alpha1.md)
and TM-071. Integrated in [#121](https://github.com/victorzhong0110/llm-research-os/pull/121)
at `e5f01f32f668842604506a0b13b1d332e81c7061`; final-head CI
[37079684137](https://github.com/victorzhong0110/llm-research-os/actions/runs/37079684137)
passed all five Python jobs, Linux OCI and authorship. Linux Python 3.12 passed
1731 selected tests, with 12 OCI-only deselected and zero failures/skips.
[Post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37080366169)
passed all five Python jobs and Linux OCI at that exact merge commit. Local
final-head evidence was 1715 passed, the same 12 host namespace/process failures,
4 skips and 12 deselected; unrounded coverage was 85.025624%. The local suite
still failed due to those environment-sensitive failures; no gates were weakened.
Remote material staging, executor/recovery integration and new authorized
two-host/GPU evidence remain open; no Checkpoint B acceptance or R09 start.

## R08 remote material preparation candidate

Base: verified main `e5f01f32f668842604506a0b13b1d332e81c7061` and passing
[main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37080366169).
This slice adds a closed pinned material index and exact bundle-member,
interpreter/review/configuration downloads, plus Worker-local durable staging
and atomic preparation. It verifies actual Worker environment bytes and rechecks
live metadata before publishing the existing non-launching R04 receipt. The
Worker receives no controller database or HMAC key. Persistent journals retain
zero starts; corrupted caches/stages/workspaces refuse without repair. Review
also requires private CAS/staging parents and synchronizes newly created nested
directory entries before atomic workspace publication. These checks are in the
implementation and refusal tests, not waived by transport-only success.

See [the protocol](../../protocols/native-material-preparation-v0alpha1.md),
TM-072 and the slice PR for exact-head validation/CI evidence. Required
unsupported isolation and remote checkpoint restore explicitly refuse. Remote
executor/Run integration and process recovery remain implementation gaps, and
new authorized two-host/GPU proof remains pending-live. This is candidate
preparation behavior, not R08 full acceptance or Checkpoint B closure. No R09.

## R08 controller-bound remote claim candidate

Base: verified main `9ae3a0ccd751543fcf1086f9fe530c3d1191e0a0` (#122),
with passing [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37120726534).
The native HTTPS poll boundary requires actual controller-owned spec/registry,
rebuilds the authorized execution binding and queues one bound Run/Attempt
before existing Worker grant consumption. Partial lifecycle prefixes replay
exactly; any existing lease returns resumed, including partially claimed leases.
Attempt remains queued, with no process start or remote PID observation.
Missing context/TLS, drift, cancellation/revocation, foreign Run and unknown
Attempt without a lease refuse. The PR records final-head tests and review.
Remote launch/process recovery and new authorized-host evidence remain open.

| Evidence dimension | Current status | What it does not establish |
| --- | --- | --- |
| Remote CPU native chain and faults | New two-host execution pending-live; transport/preparation/claim tests use real local TLS | GPU availability or GPU execution |
| Supported GPU runtime | New environment compatibility and real task pending-live; Kaggle is a candidate resource | Remote connection or process recovery |
| Remote GPU integration | New authorized supported-profile execution and fault evidence pending-live | Inferred from either row above |

These separate records preserve the existing R08 acceptance requirements.
Checkpoint B is open; freeze after its explicit acceptance; no R09.

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

## R03 candidate evidence

Scope: reviewed-native request/report contract only. The validator does not
import an entrypoint, spawn a process, consume a Worker grant, or append a
Run/Attempt fact. `launchAllowed` is false. This section preserves the original
candidate evidence before the review fixes. It is not the merge SHA or live
execution. Issue #108 is a prior CI rerun note and is not R03 execution
evidence. Real entrypoint execution remains R05. Issue #53 stays open.

Commands below were run on the original candidate tree before #109's head was
published. The original head `b7b3ab69082d12c8a0bd0bcfabdddf5c91e48b61` is not the merge
SHA. Host: Linux 6.12.94+ x86_64, CPython 3.12.3. `observe_host_feasibility()`
on that host reported `linux/x86_64`, with network, filesystem, memory,
process-group, wall-clock, and output-byte enforcement all false, and
`launch_implemented` false.

- `uv run ruff check .` passed
- `uv run ruff format --check .` passed
- `uv run mypy src` passed
- `uv run pytest -m "not oci_live and not slow" --cov=llm_research_os --cov-fail-under=85` passed: 1520 passed, 12 deselected, coverage 21434/25113 = 85.350217%
- `uv run python scripts/check_coverage.py coverage.json` passed
- `uv run researchos schema --check-all` passed
- `node conformance/digest/verify.mjs` passed (13 vectors)
- `uv run python scripts/event_catalog.py --check` passed
- `uv run python scripts/project_status.py --check` passed
- `uv build` passed

Package tests: `tests/test_native_reviewed_execution.py` (62 passed inside
the suite above). They cover the generated schemas, valid Linux and macOS
documents, stale or substituted bindings, expiry, revocation, replay, resumed
claim, unsupported profile and platform, required but unenforced isolation,
and the absence of entrypoint import or subprocess. A darwin document checked
on this Linux host is a contract result, not a live macOS run. No pending-live
host is required for this validation-only package; R05/R06 live execution
remains absent. Twelve deselected tests are the existing `oci_live` and `slow`
selectors, not R03 evidence.

## R03 integration and scope

PR [#109](https://github.com/victorzhong0110/llm-research-os/pull/109)
merged at `1a08bfede3970f9300ba53078d19e6f21a7f8d79`; the final PR
head was `b6c3ad7e66e5c088c8cc60288f4917059b268483`. Review fixes
accepted an authorization containing `execute.native` plus other capabilities,
bound the grant contract view to the Run, and rejected duplicate JSON keys,
invalid UTF-8, excessive JSON nesting, and oversized numeric literals with a
contract error. Regression coverage is in `tests/test_native_reviewed_execution.py`;
the grant fixtures include a foreign-Run denial. The final guide explicitly
labels caller-provided citations as contract fixtures. R04/R05 must rebuild
real facts and bytes before using a report for preparation or launch.

[Final PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35846797682)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, Linux OCI,
and human-authorship checks. The [post-merge main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35847460260)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, and Linux OCI;
authorship and fork-only DCO jobs were skipped on the main push.
Local review-host checks passed 68 targeted tests,
ruff, format, mypy, generated schemas, digest, event catalog, project status,
and `uv build`. The local full selection had 1523 passed, 2 skipped,
12 deselected, and 85.357% coverage; one unrelated Unix-socket artifact test
failed because the review container denied socket creation. GitHub CI ran that
test successfully on its supported runners.

Acceptance is limited to a non-launching request/report contract and its
validator. No entrypoint execution, real grant consumption, real host
enforcement, or live macOS execution was accepted. Issue #53 remains open;
R04 is the next package.

## R04 candidate evidence

Scope: verifiable code and runtime environment only. Preparation rebuilds the
authorization fact, HMAC grant, and CAS bytes, then writes or diagnoses a
private workspace. It does not import an entrypoint, spawn a process, install
a package, consume a Worker grant, or append a Run/Attempt fact.
`launchAllowed` is false. This section is candidate evidence for the open PR
head. It is not a merge SHA, not acceptance, and not live execution. Real
entrypoint execution remains R05. Issue #53 stays open.

The first fixture is the CPU brick at
`examples/native-reviewed-preparation/brick/task.py`. Valid and invalid
documents live beside it. The static Linux receipt uses a synthetic
interpreter digest and is a document fixture, not a live prepare of that
host. Package tests build the interpreter document from the process under
test. No GPU or training extra is required. No pending-live host is required
for this non-launching package.

Commands, run from the repository root on the candidate head
`c27495e67bef7d1095d3a86d63a113991252db34`. Host: Linux 6.12.94+ x86_64,
CPython 3.12.3. Base: `1a08bfede3970f9300ba53078d19e6f21a7f8d79`.

- `uv run ruff check .` passed
- `uv run ruff format --check .` passed
- `uv run mypy src` passed
- `uv run pytest -m "not oci_live and not slow" --cov=llm_research_os --cov-fail-under=85` passed: 1543 passed, 12 deselected, pytest-cov total 85.249%
- `uv run coverage json -o coverage.json` from that `.coverage` file, then `uv run python scripts/check_coverage.py coverage.json` passed: 22377/26249 = 85.248962%. The first invocation without a JSON report failed only because the file was absent (`Errno 2`); it was not a coverage-floor miss
- `uv run researchos schema --check-all` passed
- `node conformance/digest/verify.mjs` passed (13 vectors)
- `uv run python scripts/event_catalog.py --check` passed
- `uv run python scripts/project_status.py --check` passed
- `uv build` passed

Package tests: `tests/test_native_reviewed_preparation.py` (17 passed inside
the suite above). They cover a fresh workspace, repeat prepare, substitution
of code, config, inputs, and environment identity before user code,
mismatched and incomplete or damaged trees, expired, forged, revoked, and
consumed grants, `execute.local`, symlink rejection, CLI prepare/doctor, and
the absence of entrypoint import or subprocess. Twelve deselected tests are
the existing `oci_live` and `slow` selectors, not R04 evidence. No
pending-live host is required for this non-launching package.

Review follow-up on PR #111: the original candidate compared the dependency
lock and inventory to each other without checking installed packages, and its
interpreter document only named a CPython version, ABI, and platform. A
missing pinned dependency still produced `prepared` and `ready` on that head.
The corrected candidate hashes the host interpreter executable and every
listed installed distribution file, checks those bytes at prepare and doctor,
and refuses missing or altered dependencies. Regression tests cover a missing
package, valid installed package, wrong package digest, changed installed file,
wrong interpreter digest, and an executable path changed after preparation.
The generated interpreter schema, example, protocol, and guide changed with
the model. The R03 acceptance row from main #110 is preserved; the stale R03
integration note originally on this R04 branch was superseded.

On the review Linux container (CPython 3.12.14), the focused R04 suite had
19 passes. Ruff, formatting, mypy, and generated schema checks passed on the
corrected tree. The full `not oci_live and not slow` run had 1530 passes,
12 failures, 3 skips, and 12 deselections; one failure came from denied Unix
socket creation, and the others from host process observation/cancellation
restrictions. Coverage on that interrupted run was 84.207%, below the 85%
gate; this is **not** a passing full-suite result. Required GitHub CI must
validate the corrected head on supported runners before integration.

PR #111 was subsequently merged as `55b72268fcabe02ba0af0e5f1a6f038a515435e4`.
The corrected PR head `7b33809ab4f0774ecc3c145864bb7f3b89bbf9b4`
passed [CI run 36421032133](https://github.com/victorzhong0110/llm-research-os/actions/runs/36421032133)
on Ubuntu 3.12/3.13/3.14, macOS 3.12/3.13, and Linux OCI. Ubuntu 3.13
recorded 1545 passed, 12 deselected, 22441/26328 = 85.236250% coverage.
The earlier failing local container run above remains a separate record.

## R05 candidate evidence

Scope: `execute_reviewed_native` and `researchos native execute-reviewed` run
one prepared reviewed Python Attempt. The dedicated Worker runtime/media pair
binds the planned task's R03 `configDigest` to its CAS bundle and
`execute.native` capability. The entrypoint is imported only by a fixed
isolated-mode child. The parent checks R04 material, writes an fsynced launch
intent, consumes Worker authority, records Run/Attempt facts, starts the child
behind a pipe barrier, fsyncs process identity, and releases the barrier.
The child rechecks each prepared file against a pre-gate manifest, freezes
reviewed source in memory, and imports only those verified module bytes.
It accepts the contracted dotted callable names. Before success, the parent
requires process-group exit observation; exceptional cleanup signals the group
even when its leader has exited. Success stores a task-identified canonical JSON artifact in CAS,
then records `work.completed`, `attempt.succeeded`, and `run.completed`.
Observed task exceptions record Worker and Run failure facts. After uncertain
persistence, the consumed grant and launch intent block automatic redispatch.

Local Linux CPU tests cover deterministic output and CAS verification,
duplicate refusal, prepared-code substitution, pre-gate revocation and
expiry, substitution after child creation but before import, failed task
facts, identity-persistence failure after child creation, and CLI parity.
Focused command on the candidate tree:
`uv run --no-sync pytest -q tests/test_native_reviewed_child.py
tests/test_native_reviewed_runtime.py
tests/test_native_reviewed_preparation.py tests/test_native_reviewed_execution.py
tests/test_worker_protocol.py tests/test_event_catalog.py` — **127 passed**
after adding intent replay, post-preflight receipt/code substitution, stdout
bound, symlinked state directory, and a failed `attempt.started` persistence
case after grant consumption. The runner unit tests cover malformed/oversized
frames, path traversal, symlinks, byte substitution, structured success, and
task exceptions; the separate integration tests still execute an actual child.
The interpreter's actual executable image is hashed through Linux procfs
when accessible; hosts hiding process entries and macOS rehash the reviewed
interpreter path while the child remains behind the barrier. This fallback
does not prove the kernel's loaded inode identity. Network, filesystem,
memory, and process-count isolation is not claimed; R04 rejects any
unenforceable restriction marked required. R06 still owns cross-restart
observation, cancellation, and checkpoint recovery. No paid cloud or SSH
host was used. This is candidate implementation evidence, not maintainer
acceptance or a claim that a result is scientifically valid.

The local scratch container denies Unix socket creation and hides other
processes' `/proc` entries. Those restrictions break pre-existing Worker
observation and socket tests. The complete local run on this branch reported
15 failures, 1532 passed, 3 skipped, 12 deselected, and 84.291% coverage;
it is **not** passing CI evidence. The R05 tests themselves and targeted
contract/Worker regressions run separately below; supported GitHub runners
must decide the full required matrix before merge.

The first PR #114 CI run `36457193021` passed Linux OCI and the authorship
gate. Its Python tests passed (Ubuntu 3.12/3.13: 1553 passed, 12 deselected;
macOS 3.12/3.13: 1552 passed, 1 skipped, 12 deselected), but the coverage gate
failed: 84.984% on Ubuntu, 84.939% on macOS 3.12, and 84.988% on macOS
3.13. The optional Ubuntu
3.14 job also completed 1553 tests and failed only its 84.988% coverage
gate. The six added negative tests above are the follow-up for this real
coverage shortfall; a new CI run is required before review readiness.

Second CI run `36458092929` at head `64193e4b` passed Ubuntu 3.12 and 3.13,
including 1559 tests each and unrounded coverage 85.016092% and 85.004865%.
Linux OCI and human authorship passed. The optional Ubuntu 3.14 job completed
1559 tests but was still 84.997% covered. Runner branch tests were added
after this run.

Verified implementation head `79701ba4e0952eb6cb9db108ab225ba25f1f6c8f`:
[CI run 36524778920](https://github.com/victorzhong0110/llm-research-os/actions/runs/36524778920)
passed Ubuntu Python 3.12/3.13/3.14 (1571 passed, 12 deselected in each),
macOS Python 3.12/3.13 (1570 passed, 1 skipped, 12 deselected in each),
Linux OCI integration, and human authorship. The unrounded coverage range was
85.148293%–85.219176%, above the 85% gate. Regression tests cover an unlisted
unchecked `.pyc` alongside unchanged reviewed source, a dotted callable, a
surviving descendant after leader exit, and a descendant retaining pipes past
the wall-clock limit. The standalone runner reproduction and CI establish these
specific repairs; cancellation and restart reconciliation remain R06.

## R06 candidate evidence

R06 starts at main `7abe55c1a8e770a6b0e5a058ea69563edeb7071c`.
`reconcile_reviewed_native` reads the fsynced R05 launch intent, rebuilt
Worker grant/lease and Run facts, and saved process identity. A new Worker
instance can request observed stop for an already consumed lease. The fixed
profile sends TERM, waits three seconds for process-group exit, then KILL if
needed. A Linux start token or a Darwin process start observation must match;
missing identity, PID reuse, failed probes, and ambiguous outcomes remain
unknown. Post-consumption grant revocation becomes a Run cancellation request.
Cancelled is appended only after the group observer reports exited. A consumed
lease may record observed cancellation after grant expiry/revocation without
minting new launch authority. Reconciliation never redispatches an Attempt.

The companion `NativeRestoreClaim` requires a completed source Run and Worker
artifact, verified CAS bytes, distinct target Run/Attempt, matching reviewed
code/environment, an exact checkpoint input, and mode-specific state fields.
It does not assert that generic user code actually loaded state; the reviewed
task owns that behavior. `full-state` requires model, optimizer, scheduler,
and RNG fields; `adapter-only` requires adapter data and does not claim
optimizer restoration. The source/target lineage claim is saved with the new
launch intent. CLI exposes `native reconcile-reviewed` and optional restore
claim/source request arguments on `native execute-reviewed`.

Candidate tests: `tests/test_native_reviewed_recovery.py` exercises a real
sleeping task, cancellation using a newly constructed Worker/EventStore,
idempotent reconciliation, missing identity, PID reuse refusal, a still-running
Attempt without redispatch, concurrent Worker and Run cancellation fact appends,
and a
revoked/expired consumed grant that remains unknown until observed exit.
`tests/test_native_reviewed_checkpoint.py` checks a real completed source
artifact, accepts an adapter-only envelope, and rejects missing state,
incompatible mode, lineage, environment, artifact size, and digest. The
pre-claim gate rejects checkpoint input without its source and restore claim.
This scratch host cannot consistently observe process groups, even when its
start-token probe succeeds; supported Linux/macOS CI supplies the live stop
and restart result. The first [R06 CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36533850590)
found a concurrent event-ID race. Its [corrected successor](https://github.com/victorzhong0110/llm-research-os/actions/runs/36552639786)
at `bbf158f` passed the Linux 3.12/3.13 and OCI jobs, while macOS lacked
0.013 percentage points of coverage and the optional 3.14 job exposed a test
using its own ABI as an incompatibility fixture. The next
[CI run](https://github.com/victorzhong0110/llm-research-os/actions/runs/36553519194)
at `0dfc8a5` passed Linux 3.12/3.13/3.14, macOS 3.12, OCI, and authorship.
Its macOS 3.13 run exposed a second concurrent Run preflight race: the same
`attempt.cancelled` event had already made the Attempt terminal. The final
candidate handles that state only when the exact event is persisted, and its
real stop test now includes a descendant that must not survive cancellation.

Final code candidate `21792828c42ef2725ae049f52f689d5744b7ab42`:
[PR CI #251](https://github.com/victorzhong0110/llm-research-os/actions/runs/36554473144)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, Linux OCI, and
authorship. Each Python job passed 1,583 tests (12 OCI-only tests deselected).
The unrounded coverage range was 85.023693%–85.089814%, above the 85% gate.
The live test starts a reviewed task and a descendant, records a Run
cancellation, reconstructs a new Worker/EventStore, observes group exit,
verifies `cancel-observed` and `run.cancelled`, and checks that the descendant
does not run after stop. Synthetic fault tests separately cover an expired,
revoked consumed grant, PID reuse, unavailable identity, and two competing
reconcilers. This is PR verification, not post-merge CI or maintainer
acceptance; Checkpoint A remains under review until integration review.

## R07 candidate evidence

R07 is stacked on the R06 candidate branch at
`194802d9180365a9bc8a0a45b7fde99104e1662b`; R06 acceptance and merge are
still prerequisites for an integrated R07. The doctor adds explicit pinned
OpenSSH probe, deterministic offline wheelhouse installation in a private
user-owned runtime, and authenticated TLS Worker identity verification on the
existing Worker plane. The SSH pack's `pending-live` marker is not promoted by
these actions; native `--transport ssh` remains unavailable for tasks.

Local verification uses a fake SSH transport that executes the same fixed
remote program and stdin locally. It covers host-key mismatch, private-key
permissions, absent workdir, port conflict, offline wheel install/repeat/failure
cleanup, Worker registration and CA mismatch, and disconnect. The Worker
identity check appends no facts. The local transport and loopback Worker are
not an authorized second machine, so clean-host onboarding, actual host-key
rotation, network faults, and cross-machine Worker reachability remain
`pending-live`. No control SQLite, CAS, or TLS private key was sent in these
tests. The candidate does not enable an SSH task executor. Explicit, reviewed reverse
loopback tunneling is available for Worker verification; actual tunnel evidence
on an authorized second host remains pending-live.

Repository verification in this execution environment also exposed a
pre-existing R06 process-group observation ambiguity: the signal namespace
reported a present group while `/proc` exposed members under different PID
identities. The candidate now reports `unknown` when the two views disagree;
the focused descendant and synthetic regression tests pass. The Unix socket
artifact-store test cannot run here because socket creation returns `EPERM`;
that environmental exclusion is reported separately from the CI matrix.

Candidate checks on the Linux Python 3.12 implementation container:

- `pytest -q tests/test_native_ssh_live.py tests/test_native_ssh_onboard.py tests/test_worker_supervise.py::test_procfs_observation_and_group_listing tests/test_native_reviewed_runtime.py::test_descendant_cannot_outlive_recorded_success`: 62 passed, 2 skipped (no usable IPv6 link-local interface).
- `ruff check .`, `ruff format --check .`, `mypy src`, `researchos schema --check-all`, JCS conformance (13 vectors), and `git diff --check`: passed.
- Broader `pytest -q -m 'not oci_live and not slow' -k 'not test_source_symlink_directory_and_special_files_are_rejected' --cov=llm_research_os --cov-fail-under=85` before the final focused coverage additions: 1,575 passed, 11 failed, 4 skipped, 13 deselected; 83.661% coverage. Eleven existing live process-observation tests cannot resolve PIDs across this container's mixed signal/procfs views. The excluded Unix socket test raises `EPERM` here. This is **not** a passing full gate; standard CI must establish coverage and platform behavior for the final candidate.


## R08 candidate evidence

Scope: grant- and task-scoped file transfer only. `researchos native transfer`
copies manifest digests between one CAS and one directory. It does not list a
CAS, follow symlinks, or start a second lease when a journal already names one.
Fault classification keeps `unknown` and `cancel-requested` distinct from
`success`, `failure`, and `stopped`. A verified checkpoint can be copied into
the designated new Attempt; an unsupported restore is refused.

This section is candidate evidence for the open PR. It is not a merge SHA, not
maintainer acceptance, and not two-host proof. No second machine was
authorized. `gpu-oci` and `macos-mps` stay `pending-live`. Historical
cuda.1–11 and M2 OCI records are not reused. Issue #53 stays open.

The local CPU check runs one reviewed native task on the implementation host,
then copies only that task's result artifact. The receipt records
`native-scoped-transfer/v0alpha1`, the host `runtime` string, the manifest
digest, and the process identity saved by that task. That host is not a second
machine.

Package tests: `tests/test_native_transfer.py`.

## R08 review corrections

The original candidate `6382b0d4211766188daad61fb550eb9caf6f6d03` passed
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36838992563).
Review found temporary-journal symlink writes, path check/open races, short
write publication, interrupted-file retry and concurrent journal claim issues.
The follow-up pins directory descriptors, writes private exclusive temporary
files completely, publishes files without overwrite only after fsync, and
holds a journal lock across bounded read/modify/atomic publication. FIFO and
oversized journal reads are refused. Targeted transfer/security tests passed
29 cases locally; the original R07 SSH suite also passed 38 cases on this host.
Static, schema, digest and generated-state checks passed. Final candidate CI
must verify the published follow-up at its actual SHA.

The broader local run returned 1,624 passed, 12 failed, 4 skipped and 12
deselected, with 84.731% coverage. One unchanged artifact test cannot create
an AF_UNIX socket (`EPERM`); eleven unchanged Worker fault/MPS/supervision
tests cannot observe process identities in this container's mixed signal/procfs
views. This is not a passing full gate. Standard Linux/macOS CI must establish
the supported-platform results and the unrounded coverage floor. New regression
tests added after collection are included in the final candidate's CI run.

This explicitly supersedes any interpretation of the original candidate as
implemented authenticated two-host transfer. The helper trusts local manifest
correlation IDs; it does not consume a launch grant, contact another host or
exercise real disconnect/restart faults. Those remain R08 implementation work,
separate from missing authorized-host evidence. Local identity metadata is not
a new live process observation. Checkpoint B, R08 full acceptance and Issue #53
closure are not claimed. R06/R07 integration rows above supersede their old
candidate-only ledger entries; their historical candidate evidence is preserved.

Follow-up `a4e7fa89454aef18ec205aa424500cc1b780d17b` passed all Linux jobs,
OCI and macOS Python 3.13 in [CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36848733227).
macOS Python 3.12 reached 85.369% coverage but failed the competing-thread
claim regression (one claimant returned `transfer-journal-invalid`). The next
fix pairs an in-process mutex with the inter-process flock and creates the
stable lock inode exclusively before reopening it. A separate-process claim
regression complements the thread test. No failed CI is recorded as passing.

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


R07 follow-up: PR #116 at `087da05` passed all 1,594 selected tests on Ubuntu
3.13, but failed the 85% coverage gate at 84.804%. The follow-up adds remote
entrypoint/input refusal and bounded SSH response tests plus a loopback-only
reviewed tunnel. This newer container denies even TCP socket creation (`EPERM`);
focused checks here returned 73 passed, 2 failed (socket permission), 2 skipped.
Standard CI must verify the follow-up at its actual published commit.

After local loopback permission was granted, the restored focused suite passed
77 tests. Additional prerequisite/timeout cases are included in the final
candidate. Ruff, format and mypy checks passed. Full standard CI remains the
authoritative cross-platform and coverage gate for this follow-up.

At `4ff19dffae6e7d072a5d3775b2bc4c1129be48c8`, CI run
[255](https://github.com/victorzhong0110/llm-research-os/actions/runs/36671646529)
passed Ubuntu Python 3.12/3.13/3.14 and Linux OCI. macOS 3.13 passed all
1,609 selected tests but coverage was 84.984%, below the gate. The local
complete suite also passed 1,609 tests with 84.991% coverage. The next
follow-up adds prerequisite, credential privacy, bounded pack and failed-install
cleanup tests; its 37 SSH tests, ruff, format and mypy checks passed locally.

At `f0b8914fe6b6f9368c5ad8eef9727600d7828d98`, CI run
[256](https://github.com/victorzhong0110/llm-research-os/actions/runs/36672183995)
passed all Ubuntu/OCI checks. macOS coverage reached 85.106%, but the output
limit fixture's shell pipeline encountered a denied group cleanup signal,
masking its original bound error. The follow-up preserves that error, falls
back to killing its own SSH child, and uses a single-process output fixture.
The 38 SSH tests and static checks passed locally before publication.
