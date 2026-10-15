# R07/R08 selected-host acceptance checklist

Status: **Partial live evidence recorded 2026-10-15 (UTC+8). Two-host native CPU
execution, verified transfer, reconnect observation, disconnected cancellation, and
pre-claim retained intent are recorded below. SSH onboarding/install, GPU probe/task, and
Checkpoint B acceptance remain open.**
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
| Full execution Git SHA and verified main CI | `c6b21b929ed35c853116fcd186559f9caad1e9ae` (main; package software slices include #127/#128). Live run used this SHA on both hosts. |
| Wheel digest and installed package/runtime versions | Source checkout `uv sync --locked --all-groups`. Controller: CPython 3.12.14 / Linux x86_64. Worker: CPython 3.12.13 / macOS arm64. Worker interpreter digest `sha256:36984af9f922aec72ba5b03e811ee92512268785007192e20f826cbd07cf8d04`. |
| Anonymous controller / Worker host labels and platforms | Controller host `ctl-linux-a` (Linux x86_64). Worker host `wrk-darwin-a` (macOS arm64). Cross-host control-plane reachability via operator SSH local-forward to controller loopback HTTPS (TLS CA pin). |
| Reviewed project/spec/registry/input identities | Project `project.reviewed`. Native reviewed CPU fixture (corpus `{"rows":1}\n`, expected output digest `sha256:815853a11c4f2e2e5355f547308cd7c6054f85ba6a324b2c37beb8edbec1fb93`). Synthetic test actors/grants (engineering demonstration, not production grant provisioner). |
| Original request, Run/Attempt, Worker/grant and authorization citation | Distinct staged worlds per scenario (`run.1` / `attempt.1` / `grant.native` / `lease.grant.native`). Authorization events present before each dispatch. |
| Actual Worker process identity/observation and output digest | Worker `posix_start_token` available (`darwin-lstart`). Process identity kind `posix-pg`. s1 output digest matched on Worker CAS and controller CAS. |
| Selected supported GPU profile/runtime | Pending-live (not in this run) |
| Execution times and reviewer | 2026-10-14T21:35:45Z–2026-10-14T22:29:47Z (UTC). Operator session on authorized hosts. |

## Evidence ledger

Replace pending rows only with actual reports, commands, identities and outcomes.
Each report identifies the before/after event high-water mark and applicable
process, transfer, artifact and receipt observations. Keep evidence scoped to
its actual implementation/platform; explicitly supersede corrections.

| Check | State | Evidence / result |
| --- | --- | --- |
| Pinned SSH probe, offline install and idempotent repeat | Pending-live | Not exercised in this run (R07 onboarding path out of this session's scope) |
| TLS and actual authenticated Worker registration | Observed (partial) | Controller loopback HTTPS with pinned CA fingerprint; Worker `run-native` authenticated and claimed work. Not a packed `ssh-doctor verify-worker` record. |
| SSH key/certificate, prerequisites, permissions and disk/port refusals | Pending-live | Not exercised |
| CPU native task: input, claim/start, actual process, output and Run facts | **Pass** | Scenario s1 (`ctl-linux-a` serve + `wrk-darwin-a` `workers run-native`). Receipt disposition `completed`, sequence 14, `launchAllowed: false`, eventId `evt.native.remote.run.1.attempt.1.run.completed`. Controller high-water 14 / `runStatus=completed`. Event prefix includes `work.claimed` → `authorization.grant.consumed` → `attempt.started` → `work.completed` → `attempt.succeeded` → `run.completed`. Worker retained `.intent/.claim/.identity/.start/.result/.outcome`. |
| Disconnect before claim / lost claim response | Partial; pre-claim disconnect observed | Scenario s4. Intent written then tunnel dropped before `.claim`. Worker error `http-disconnect`. Controller remained sequence 4 (grant not consumed; no `work.leased`/`work.claimed`). State retained only `.intent`+`.lock`. `reconcile-native` → `native-outcome-unrecorded` (observation only). Immediate `run-native` retry → `native-intent-exists` (no replacement launch). Replay identical. Loss of a response after a successful claim was not exercised and remains pending-live. |
| Tunnel loss during execution | **Pass** | Scenario s2. After `.identity` and workspace `started`, tunnel and Worker client killed; child pid/pgid remained alive on Worker. Controller later restarted. |
| Controller restart | **Pass** | Scenario s2. Controller stopped and restarted against the same database/TLS/native context; subsequent reconcile observed the original Attempt (sequence advanced from retained facts, no duplicate start). |
| Worker client restart and existing-process recovery | **Pass** | Scenario s2. After Worker SIGKILL, `reconcile-native` returned disposition `running` (sequence 11, `attempt.started`, `launchAllowed: false`) while original `posix-pg` child still matched saved identity. No new child launch. Later unsupervised exit without harvested `.result` settled as conservative `unknown` (sequence 12); identical replay; no fabricated completion. |
| Interrupted input/output transfer | Pending-live | Not separately fault-injected in this run (s1 completed transfer without mid-upload interrupt) |
| Lost completion response / identical receipt replay | Partial; fault pending-live | Scenario s1. Immediate `reconcile-native` after completed `run-native` reproduced the exact receipt bytes (`cmp` identical); controller sequence remained 14 (no duplicate facts). The completion response was received; response-loss injection was not exercised. |
| Disconnected cancellation / verified group stop | **Pass** | Scenario s3. Long-running child started; tunnel/Worker killed while child alive; controller appended `run.cancel.requested` while disconnected (sequence 12, `runStatus=running`). After reconnect, `reconcile-native` returned disposition `cancelled` (sequence 15, eventId `…run.cancelled`); child process exited; `.cancelled` retained; identical receipt replay. Controller events: `run.cancel.requested` → `work.failed` → `attempt.cancelled` → `run.cancelled`. |
| Unavailable process identity / conservative unknown | Pending-live; related unknown observations only | Scenario s2 terminal `unknown` after unsupervised exit without `.result`, and scenario s4 pre-claim unknown. s2 had an available `darwin-lstart` identity; s4 never launched a process. Neither exercises unavailable identity. No PID-reuse claim or invented terminal completion. |
| Corrupt or unauthorized paths and resource bounds | Pending-live | Not exercised on selected hosts in this run |
| Checkpoint restore / explicit unsupported refusal | Pending-live | Not exercised |
| Candidate GPU resource probe, including Kaggle compatibility if selected | Pending-live | No candidate-environment execution |
| Actual supported GPU runtime/task | Pending-live | No new supported-profile execution |
| Supported GPU profile over remote chain | Pending-live | No new remote GPU execution |

## Scenario receipts (redacted)

Private URLs, credential bytes, host addresses, and absolute operator paths are omitted.

### s1 — completed CPU + transfer + replay

- Worker receipt: disposition `completed`, sequence `14`, bindingDigest `jcs-sha256:47b9050dd2c2e516e2634ae4dce8ae86b4412a6e3edf27b2c509c26894de93c0`.
- Output artifact digest `sha256:815853a11c4f2e2e5355f547308cd7c6054f85ba6a324b2c37beb8edbec1fb93` present in Worker CAS and controller CAS.
- Times (UTC): start ~2026-10-14T21:35:45Z, complete ~2026-10-14T21:36:01Z.

### s2 — reconnect / surviving child

- Identity (redacted): kind `posix-pg`, startToken scheme `darwin-lstart`.
- Reconcile while child alive: disposition `running`, sequence `11`.
- After unsupervised exit: disposition `unknown`, sequence `12`; identical replay.
- Controller final: `runStatus=unknown`, high-water 12.
- Times (UTC): ~2026-10-14T22:26:53Z–2026-10-14T22:27:53Z.

### s3 — cancel while disconnected

- Cancel requested on controller while Worker disconnected: sequence 12 includes `run.cancel.requested`.
- Reconcile after reconnect: disposition `cancelled`, sequence `15`, bindingDigest `jcs-sha256:e1d0f5c9f95e4fbf1ff926e58a2fcca52dd38a68e6e4d2ee6228d3737583938c`; identical replay; process group stopped.
- Times (UTC): ~2026-10-14T22:28:42Z–2026-10-14T22:29:06Z.

### s4 — pre-claim disconnect; retained intent

- After disconnect: Worker ProblemReport `http-disconnect`; state has intent only.
- Controller unchanged at sequence 4 (grant not consumed).
- Reconcile ProblemReport type `native-outcome-unrecorded`; retry `run-native` ProblemReport type `native-intent-exists`.
- Times (UTC): ~2026-10-14T22:29:27Z–2026-10-14T22:29:47Z.

## Review and integration

- Candidate evidence: this checklist now records selected two-host native CPU
  execution, transfer, reconnect observation, disconnected cancel, and pre-claim
  retained intent. Remaining R07 onboarding faults, transfer-interrupt injection, bounds
  corruption, checkpoint restore, completion-response loss, post-claim response
  loss, unavailable-identity injection, and all GPU rows stay pending-live.
- Implementation integration: CPU native/Ray slices are already merged; see the
  [collaboration snapshot](../../collaboration-log.md#current-snapshot).
- Evidence PR: #150, original head `5b7946b9001d4360d26f8df2ecce14d231fd1f5f`,
  execution base `c6b21b929ed35c853116fcd186559f9caad1e9ae`. Review corrected
  overclaimed combined rows on 2026-10-15; this is integration of a partial
  operator report, not independent reproduction or complete live acceptance.
  Final correction head/checks and merge identity are tracked in #150.
- R07/R08 acceptance and B review: still pending maintainer review; GPU and
  onboarding gaps prevent claiming Checkpoint B closed.
- R09 was integrated in #131 at `73e1386cd5c3d6cafbc91798b62a5b04460cfc93`
  under the recorded maintainer authorization for sequential implementation and
  merges. This evidence does not close B or change that authorization.
