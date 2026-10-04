# Close R07/R08 on actual authorized hosts

Current state: software slices are merged; new selected-host evidence is
**pending-live**. This runbook prepares the remaining acceptance work, not a
record that it ran. The maintainer's 2026-10-04 direction is to complete through
R16 sequentially, integrating and accepting each predecessor first. The
[M3 plan](../plans/m3-development-plan.md) defines the unchanged gates.

## Inputs needed to run

The maintainer has confirmed that two hosts and a GPU environment exist. The
current execution environment has no supplied connection configuration or Kaggle
execution arrangement. Supply access through the existing private credential
channel, not this document or a public PR.

| Input | Needed for |
| --- | --- |
| Controller and Worker access/configuration, dedicated account and owned directories | Operate two actual machines; separate Worker roots from controller data |
| Independently verified SSH host key and private identity-file location | Pinned R07 probe, install and tunnel; no agent forwarding |
| Approved tunnel/port arrangement and public Worker CA | Verify the existing authenticated HTTPS Worker endpoint across the hosts |
| Target-compatible reviewed wheelhouse and original spec/registry/request | Install the exact build and bind execution to the reviewed task and live grant |
| Selected supported GPU profile and access to that environment | Actual compatibility/task verification, separately from remote connectivity |
| For a Kaggle candidate: an executable notebook/session or returned probe output | Determine compatibility; do not assume a notebook supports SSH, OCI or recovery |

No additional permission question is needed for previously authorized in-scope
resources. Missing connection details still prevent execution. Record public
evidence using anonymous host labels; keep connection addresses and secrets in
private configuration.

## 1. Fix the evidence identity

Choose the latest verified main at execution time. Record the full Git SHA,
wheel SHA-256, runtime versions, reviewed spec/registry/input identities,
authorization citation, project/Run/Attempt, and Worker/grant IDs. Record a UTC
or timezone-qualified time for each operation. Do not reuse historical M2
hardware results as proof of this build.

The preparation baseline for this runbook is
`main@0acb62bad5dd0a54cb305bf89b2bc9deebb0427b`;
[main CI 37183362803](https://github.com/victorzhong0110/llm-research-os/actions/runs/37183362803)
passed. It contains the verified #128 CPU implementation and #129 communication
record. Select the actual execution SHA after this documentation change merges.

## 2. Onboard and verify the Worker

Follow [SSH onboarding](m3-native-ssh-onboarding.md) for the pinned pack,
`ssh-doctor` probe, offline pinned-wheel installation, idempotent repeat, and
authenticated Worker verification. Exercise bad key/certificate, prerequisites,
permissions, disk/port conflicts and disconnect outcomes on the authorized
resources. Keep evidence of actual TLS and Worker registration; successful SSH
or tunnel creation alone is insufficient.

Use the [native Worker CLI](native-worker-cli.md) with the original reviewed
controller spec/registry. Provision only the scoped Worker credential and public
CA on the Worker. Never copy the controller database, entire CAS, signing key or
TLS private key to it. The Worker must retain its own private CAS and state.

## 3. Execute and reconcile the CPU task

Create the reviewed bounded task and existing Run/Attempt/grant through the
current services. Save the original reviewed request before dispatch. Use
`researchos workers run-native` exactly once; after an uncertain response or
restart use `researchos workers reconcile-native` with that same request and
retained state. See [execution/recovery behavior](native-remote-execution.md).

The first receipt, actual Worker-local process identity/observation, output CAS
digest and controller event prefix must agree. Reconciliation must not poll for
another task, consume new launch authority, create a replacement child, or append
duplicate completion facts. A command exit code of zero can represent a handled
running observation; inspect the receipt disposition before recording completion.

## 4. Collect fault evidence on the two selected machines

Use bounded reviewed fixtures and faults affecting only this owned task/tunnel.
Run each scenario with distinct Run/Attempt identities except where the scenario
explicitly tests recovery/replay of the original identity. Preserve state before
and after each interruption; do not erase uncertain intent to force a rerun.

| Scenario | Evidence and required outcome |
| --- | --- |
| Disconnect before claim or lose its response | Original binding and claim/lease record; uncertain/resumed claim never starts a replacement task |
| Lose tunnel during execution | Worker-local identity, disconnect interval and subsequent observation; no duplicate start or fabricated completion |
| Restart controller | Reopen the existing database, TLS/authority state and journal; reconcile the same Attempt and immutable documents |
| Restart Worker client while its task survives | Retained native state and actual saved-group observation; recovery observes the original process |
| Interrupt input/output upload | Scoped journal and integrity checks; bounded retry resumes transfer or returns a precise refusal |
| Lose completion response | Same immutable output/outcome replays; controller facts and CAS identity do not duplicate or change |
| Request cancellation while disconnected | Cancellation intent remains distinct from observed stop; reconnect stops only the verified saved group |
| Make process-identity observation unavailable | Conservative unknown/refusal; no PID-reuse claim, replacement launch or invented terminal stop |
| Corrupt material, change a path or exceed bounds | Rejection before unsafe publication/execution; no unrelated files or controller data exposed |
| Restore a checkpoint to a new Attempt | Verified matching checkpoint and fresh authority, or explicit unsupported-restore refusal; never silently restart from scratch |

Designated single-host CI tests cover important implementation behavior but do
not replace these selected two-host observations. Save bounded redacted reports
and artifact/event identities in the [evidence checklist](../evidence/m3/r08-live-acceptance.md).

## 5. Probe the GPU candidate separately

On the candidate compute environment, use the installed reviewed core wheel,
existing CUDA-capable PyTorch environment and the pinned optional Ray 2.59.0
extra. Keep that environment separate from the controller. Do not replace the
notebook's PyTorch/driver or claim a runtime profile from GPU advertisement.

The existing finite [resource probe](../../examples/r08-ray-jobs/README.md)
can run in a Kaggle notebook terminal/cell after its dependencies are available:

```bash
python examples/r08-ray-jobs/probe.py \
  --device cuda --name r08-candidate-gpu-01 --state /tmp/r08-candidate-gpu-01
```

This starts an explicitly owned authenticated loopback Ray cluster and executes
the fixed small CUDA calculation. Record exact package/build versions, backend
status and result, including GPU/CUDA/PyTorch identity. Nonzero exit, unknown
status, absent result or unavailable GPU remains an unavailable/pending result.
Keep the probe state for inspection; do not reuse an uncertain identity to force
a second submission. This is a resource probe, with zero project task starts
and zero appended lifecycle facts; it is neither a supported-profile task nor
remote acceptance evidence.

Then exercise an already supported GPU task/profile with its existing pinned
runtime, authority and output checks. If the candidate cannot support that
profile, record the specific incompatibility and use an authorized compatible
environment. A successful CUDA calculation does not certify OCI support, SSH
onboarding, GPU task execution, checkpoint restore or remote fault recovery.

## 6. Review B, merge, then start R09

Review the actual R07/R08 evidence against every acceptance bullet and the
matrix. Keep these conclusions separate: remote connectivity/CPU faults,
supported GPU runtime/task, and remote GPU integration. Unperformed checks stay
pending-live; no Mock, ordinary skip or historical M2 evidence closes them.

Fix defects in sequential R08 slice PRs, rerun the affected real paths, and merge
after required checks. Commit actual evidence and an explicit scoped B review.
Only after R08 is integrated and accepted may R09 start from verified main.
Repeat the existing merge/acceptance gates for R09–R16. R16 requires two real
independent trial users; the maintainer handles their invitations. Software
completion cannot manufacture those trials or a human research conclusion.
