# R07/R08 selected-host acceptance checklist

Status: **Prepared; no new live execution recorded. Checkpoint B remains open.**
Instructions: [R08 live acceptance runbook](../../guides/r08-live-acceptance.md).
Requirements: [plan](../../plans/m3-development-plan.md) and
[acceptance matrix](acceptance-matrix.md).

## Local preparation check (2026-10-04)

On the preparation workspace, Linux / Python 3.12.14, the actual
`native ssh-doctor`, `workers run-native` and `workers reconcile-native` help
commands matched the documented interfaces. The installed core's
`posix_start_token(os.getpid())` returned unavailable. Import discovery found
neither PyTorch nor Ray in that core environment. This is a local readiness
check, not an execution or GPU-absence claim. No task or cluster was started.
This workspace cannot supply the designated process-identity live gate; the
selected authorized hosts and GPU environment are still required.

## Runtime identity

Fill this table only from the actual execution. Keep private connection details
and credential bytes out of committed evidence.

| Field | Current record |
| --- | --- |
| Full execution Git SHA and verified main CI | Not selected for live execution |
| Wheel digest and installed package/runtime versions | Pending-live |
| Anonymous controller / Worker host labels and platforms | Pending connection configuration |
| Reviewed project/spec/registry/input identities | Pending-live |
| Original request, Run/Attempt, Worker/grant and authorization citation | Pending-live |
| Actual Worker process identity/observation and output digest | Pending-live |
| Selected supported GPU profile/runtime | Pending environment access/probe |
| Execution times and reviewer | Pending-live |

## Evidence ledger

Replace pending rows only with actual reports, commands, identities and outcomes.
Each report identifies the before/after event high-water mark and applicable
process, transfer, artifact and receipt observations. Keep evidence scoped to
its actual implementation/platform; explicitly supersede corrections.

| Check | State | Evidence / result |
| --- | --- | --- |
| Pinned SSH probe, offline install and idempotent repeat | Pending-live | No selected-host execution |
| TLS and actual authenticated Worker registration | Pending-live | No selected-host execution |
| SSH key/certificate, prerequisites, permissions and disk/port refusals | Pending-live | No selected-host execution |
| CPU native task: input, claim/start, actual process, output and Run facts | Pending-live | No selected-host execution |
| Disconnect before claim / lost claim response | Pending-live | No selected-host execution |
| Tunnel loss during execution | Pending-live | No selected-host execution |
| Controller restart | Pending-live | No selected-host execution |
| Worker client restart and existing-process recovery | Pending-live | No selected-host execution |
| Interrupted input/output transfer | Pending-live | No selected-host execution |
| Lost completion response / identical receipt replay | Pending-live | No selected-host execution |
| Disconnected cancellation / verified group stop | Pending-live | No selected-host execution |
| Unavailable process identity / conservative unknown | Pending-live | No selected-host execution |
| Corrupt or unauthorized paths and resource bounds | Pending-live | No selected-host execution |
| Checkpoint restore / explicit unsupported refusal | Pending-live | No selected-host execution |
| Candidate GPU resource probe, including Kaggle compatibility if selected | Pending-live | No candidate-environment execution |
| Actual supported GPU runtime/task | Pending-live | No new supported-profile execution |
| Supported GPU profile over remote chain | Pending-live | No new remote GPU execution |

## Review and integration

- Candidate evidence: this checklist currently contains no live results.
- Implementation integration: CPU native/Ray slices are already merged; see the
  [collaboration snapshot](../../collaboration-log.md#current-snapshot).
- Evidence PR/head/base, merge SHA and post-merge CI: record only after they exist.
- R07/R08 acceptance and B review: pending; required evidence is not yet present.
- Next package: R09 is authorized after its predecessor is integrated and accepted.
