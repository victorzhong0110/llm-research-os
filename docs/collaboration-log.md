# Collaboration communication log

Shared communication record for the planning/review assistant and assigned
implementers. The maintainer requested this repository-local record on
2026-10-04. Read it when starting or resuming work; maintain it alongside each
related slice. Record project decisions and handoffs, with links to their
evidence, rather than copying entire conversations or unrelated personal memory.

## How to maintain this file

- Refresh the current snapshot when implementation, integration, verification,
  acceptance, or a blocker changes. Identify the exact baseline and evidence.
- Append messages using a unique sequential ID, ISO date/time with timezone,
  sender, recipient, subject, state, evidence, and next action/owner.
- Reply with a new message referencing the original ID. Preserve earlier messages;
  corrections explicitly supersede the relevant statement. Refresh the open
  handoff table when a reply resolves or changes an item.
- Distinguish `open`, `acknowledged`, `blocked`, and `resolved`. A written message
  does not establish that another collaborator read or accepted it. Each sender
  records their own acknowledgement; never invent another assistant's reply.
- Include branch/head/base, PR, actual checks, and known gaps in delivery/review
  messages. Link full reports instead of duplicating CI logs.
- Record missing inputs precisely. Keep credentials, tokens, private keys,
  private host access details, and personal conversation contents out of the log.
- Follow [AGENTS.md](../AGENTS.md), [governance](development-governance.md),
  the [M3 plan](plans/m3-development-plan.md), and the
  [acceptance matrix](evidence/m3/acceptance-matrix.md). Messages do not change
  acceptance criteria or grant additional execution, merge, host, or spending
  authority. Starting other agents still requires an explicit assignment.

## Current snapshot

Snapshot date: **2026-10-05, sequential PR integration review**. Verified reviewed integration:
`bc0bcbcc229aa0cc74648f798c49a0f1bcaebad6` (#135), final-head CI 37232561416
passed. #134 integrated at `89b9ab4f021ff8e3d1e53ef041989ab11605da57` after
final-head CI 37230774848 passed. Historical live execution baseline remains
`ed6fb30d6cb239ad37a34404814183764bce2a58` at its recorded platforms.
Historical verified documentation main: `0acb62bad5dd0a54cb305bf89b2bc9deebb0427b`
([main CI 37183362803](https://github.com/victorzhong0110/llm-research-os/actions/runs/37183362803)
passed). Documentation changes do not advance the execution baseline.

| Item | State and evidence |
| --- | --- |
| Current package | #133–#135 are integrated; #136 is a reviewed and repaired partial slice. Final integration SHAs and final-head checks are recorded at [#135](https://github.com/victorzhong0110/llm-research-os/pull/135) and [#136](https://github.com/victorzhong0110/llm-research-os/pull/136). R11–R14 full acceptance and B/C/D live evidence remain open. |
| Native Worker CLI | [#127](https://github.com/victorzhong0110/llm-research-os/pull/127) merged; reviewed CPU execution and observation-only recovery. |
| Optional Ray CPU project jobs | [#128](https://github.com/victorzhong0110/llm-research-os/pull/128) merged at the baseline above; fixed installed driver, durable single submission and native recovery outside Ray. |
| Baseline verification | [Main CI 37144839460](https://github.com/victorzhong0110/llm-research-os/actions/runs/37144839460) passed all five Python and actual Ray project/resource, native and OCI gates. Linux 3.12: 1973 passed, zero failures/skips, coverage 26871/31324 = 85.784063%. Ray project gate: 3 real tests; native gate: 15 real tests. |
| Acceptance gaps | GPU/Kaggle runtime evidence and newly selected actual two-host native/fault evidence remain pending-live. CPU integration does not close these gaps or B. |
| Resource reporting | Controller/remote connectivity, CPU availability and GPU availability must be reported separately. |
| Responsibility | Maintainer assigned Codex to review, repair and integrate all open PRs; no additional package is started. |
| Downstream gate | Any separately assigned next package fetches current main and preserves the reviewed #133–#136 repairs. R08 connection/GPU inputs remain separate, see COMM-0004. Cleanup of existing PRs does not start R15. |

## Open handoffs

| Message | Recipient | State | Next action / owner |
| --- | --- | --- | --- |
| COMM-0004 | Maintainer / resource owner | Blocked on missing input | Supply existing private host connection configuration and GPU/Kaggle execution access so Codex can collect actual R07/R08 evidence. |
| COMM-0005 / COMM-0006 | Planning/review assistant and maintainer | Resolved for integration by COMM-0008 / COMM-0009 | Bounded local transport approved; explicit maintainer direction superseded withheld merges. No phase acceptance inferred. |
| COMM-0007 | Planning/review assistant and maintainer | Open; awaiting review | Review the R10 dependency lock and the deferred React Flow graph library. |
| COMM-0008 | Planning/review assistant and maintainer | Open; awaiting decision | Decide whether R11's missing start/reconnect/restore may be deferred past R12, given R08's pending-live native evidence. |

COMM-0002 was acknowledged by Codex in COMM-0003. Its evidence gaps remain open;
the acknowledgement does not establish acceptance. COMM-0005 and COMM-0006 are
review requests raised by the R09 slice, not acknowledgements by anyone else.

## Message history

### COMM-0001 — Establish the shared record

- Date/time: 2026-10-04T14:25:21+08:00 (maintainer request time).
- From: Maintainer, recorded by Codex.
- To: Planning/review assistant and assigned implementers.
- Subject: Maintain a communication file inside this repository.
- State: Acknowledged by Codex; initial record prepared in this change.
- Request: Keep durable communication between collaborators in the repository.
- Response: Add this record and its discovery/maintenance instruction to
  `AGENTS.md`; seed verified project state and the pending handoff below.
- Evidence: Maintainer instruction in the current project conversation;
  existing [development governance](development-governance.md).
- Next action / owner: Each collaborator reads and updates this file in their
  related work. Integration of this initial documentation is tracked by its PR;
  this entry does not predict a merge SHA or another collaborator's response.

### COMM-0002 — R08 CPU integration handoff

- Date: 2026-10-04 (Asia/Taipei).
- From: Codex, planning/review and implementation.
- To: Next explicitly assigned collaborator.
- Subject: Preserve verified CPU integration and complete only authorized R08 work.
- State: Open; awaiting an actual collaborator acknowledgement.
- Delivery: Native CLI and Ray CPU project execution are merged and verified at
  the snapshot baseline. Unknown/lost submission state permits observation only;
  recovery must not poll or launch a replacement task.
- Evidence: [#128 delivery and review](https://github.com/victorzhong0110/llm-research-os/pull/128),
  [baseline main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37144839460),
  [R08 acceptance requirements](plans/m3-development-plan.md#r08-two-host-artifact-transfer-and-fault-acceptance).
- Gaps / inputs: New actual two-host and supported GPU evidence remains missing.
  Verify the specific authorized hosts, access and GPU environment when assigned;
  this message supplies no credentials or new resource authorization. Mocks,
  ordinary skips and historical M2 hardware evidence cannot replace new R08 proof.
- Next action / owner: The next assigned collaborator replies to COMM-0002 with
  their scope, actual branch/base, available inputs and remaining blockers. Keep
  B open and R09 unopened until the required acceptance review is complete.

### COMM-0003 — Resume sequential delivery through R16

- Date/time: 2026-10-04T18:41:11+08:00 (maintainer instruction time).
- From: Codex, recording and acknowledging the maintainer's assignment.
- To: Maintainer and subsequent assigned collaborators.
- Reply to: COMM-0002.
- State: Acknowledged by Codex; handoff accepted, live evidence still pending.
- Message / decision: Complete all remaining packages, merging the preceding
  package before starting the next. This supersedes the previous freeze after B.
  Existing package definitions, acceptance dependencies and resource boundaries
  continue to apply. Codex continues implementation and review sequentially.
- Branch / head / base / PR: `docs/sequential-r08-r16-acceptance`, based on verified
  main `0acb62bad5dd0a54cb305bf89b2bc9deebb0427b`; exact submitted head and checks
  are tracked by this documentation PR.
- Evidence / checks: [Verified main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37183362803);
  [updated canonical plan](plans/m3-development-plan.md#maintainer-execution-direction-complete-sequentially-through-r16).
- Gaps / required inputs: R07/R08 selected-host and supported GPU proof; see
  COMM-0004. This direction update does not claim B acceptance or start R09.
- Next action / owner: Codex merges the direction/runbook change, then collects
  R07/R08 evidence when the missing resource configuration is available.

### COMM-0004 — Missing execution inputs for the R08 acceptance gate

- Date: 2026-10-04 (Asia/Taipei), after COMM-0003.
- From: Codex.
- To: Maintainer / owner of the selected compute resources.
- Reply to: COMM-0003.
- State: Blocked on missing execution input, not an additional merge approval.
- Message / decision: Prior project context confirms two hosts and a GPU exist,
  but no reusable connection configuration or Kaggle session/execution arrangement
  was supplied. CPU software and designated single-host gates are already merged.
  The [runbook](guides/r08-live-acceptance.md) and
  [pending evidence checklist](evidence/m3/r08-live-acceptance.md) prepare the
  required selected-host runs without claiming they occurred.
- Evidence / checks: Existing CPU baseline in the snapshot; resource availability
  is not inferred from that baseline or historical M2 hardware evidence.
- Gaps / required inputs: Privately supplied host connection configuration,
  trusted host-key/identity location and approved tunnel arrangement, plus selected
  GPU environment access or candidate probe output. No secret belongs in this file.
- Next action / owner: Maintainer/resource owner supplies the existing access
  details; Codex performs the real runs, fixes observed defects, merges evidence,
  reviews B and then advances to R09. No acceptance criteria are waived.

### COMM-0005 — R09 local API is a standard-library WSGI surface, not FastAPI

- Date: 2026-10-04 (Asia/Taipei), after COMM-0003.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; proposed normative change awaiting review.
- Message / decision: R09 was implemented as a loopback-only WSGI application on
  `wsgiref` rather than the "optional FastAPI/ASGI" the plan described. Rationale
  is dependency restraint: the core carries five dependencies, and a framework plus
  an ASGI server would add several more, including compiled ones, to every install
  and to the supply chain already tracked as TM-016. The documented contract —
  versioned JSON, closed structured errors, same-origin sessions, bounded
  projections, resumable SSE with polling fallback — is unchanged. The framework
  would not have supplied the Host, Origin, CSRF or parser-budget controls; those
  are explicit code in either design.
- Branch / head / base / PR: `r09-local-api`, based on
  `docs/sequential-r08-r16-acceptance` at `021f18e`; open PR, deliberately not
  merged. Exact submitted head and CI outcome are recorded by that PR.
- Evidence / checks: [R09 candidate evidence](evidence/m3/acceptance-matrix.md#r09-candidate);
  `tests/test_web_api.py` 50 passed; `mypy src` clean over 241 files; ruff, schema
  `--check-all`, event catalog, project status and digest conformance passed.
- Gaps / required inputs: No browser has loaded the surface, so there is no E2E or
  accessibility evidence. A large-volume query baseline is unmeasured. `wsgiref` is
  a development server and is not hardened against a hostile network peer.
- Next action / owner: Reviewer decides whether to accept the stdlib transport or
  require a framework-backed implementation. Replacing the transport later does not
  change the protocol document, so this need not block R10 design work.

### COMM-0006 — Recorded conflict between "no merges yet" and "do not stack branches"

- Date: 2026-10-04 (Asia/Taipei), after COMM-0005.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; maintainer decision required. Not silently resolved.
- Message / decision: A later maintainer instruction asked for the remaining
  packages to be completed with no pull request merged. The canonical plan requires
  the opposite in two places: start each package from verified main only after its
  predecessor is merged and accepted, and do not stack package branches. Those cannot
  both hold while every merge is withheld. Rather than pick one silently, delivery
  continues as a linear stack of one package per branch and one reviewable PR per
  package, each based on the previous package's branch, with the base stated on every
  PR. Acceptance is still a separate review, a merge is still an integration fact
  rather than acceptance, R08 live evidence is still pending-live, and Checkpoint B is
  still open.
- Branch / head / base / PR: `r09-local-api` based on
  `docs/sequential-r08-r16-acceptance`; see the plan's "Recorded deviation" section.
- Evidence / checks: Plan section
  "Recorded deviation: delivery is currently a stacked, unmerged sequence".
- Gaps / required inputs: If the maintainer prefers unmerged work without stacking,
  the alternative is to pause at the first unmerged package. That is a maintainer
  decision, not an implementer one.
- Next action / owner: Maintainer confirms the stacking deviation or directs a pause.

### COMM-0007 — R10 locked React/TypeScript/Vite and deferred the graph library

- Date: 2026-10-04 (Asia/Taipei), after COMM-0006.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; proposed normative change awaiting review.
- Message / decision: R10 locked the concrete dependencies the plan deferred:
  React 19, TypeScript 5.9 and Vite 7, with no component library and no
  client-side state library. The plan's architecture paragraph named "read-only
  React Flow"; the execution graph is instead a read-only ordered list of run
  nodes, and no layout library is added. Node placement is presentation only and
  feeds no digest, so the acceptance requirement is unaffected, and rendering a
  guessed graph shape would be worse than an honest list. A layout library should
  be introduced only when a real multi-node DAG needs one.
- Branch / head / base / PR: `r10-workbench`, based on `r09-local-api` at
  `4cc2f82`; open PR, deliberately not merged.
- Evidence / checks: [R10 candidate evidence](evidence/m3/acceptance-matrix.md#r10-candidate);
  `npm run typecheck` clean under `strict` plus `exactOptionalPropertyTypes` and
  `noUncheckedIndexedAccess`; 2067 passed with coverage 85.76%; a real Chrome run
  over `example-minimal` with zero console errors.
- Gaps / required inputs: No automated browser E2E exists in CI, and the committed
  JavaScript bundle is not rebuilt or diffed there; only the Python-owned
  contract types are drift-checked. The decision/dissent/authorization lineage
  view is deferred to R12. The run index folds events rather than using the
  existing `run_projections` cache, so a store with many runs will be slow.
- Next action / owner: Reviewer decides whether to require React Flow now. This
  does not block R11 design work, because R11 reuses the same API contract.
### COMM-0008 — Maintainer assigns direct repair and sequential integration

- Date/time: 2026-10-04T21:59:47+08:00 (maintainer instruction).
- From: Codex, planning/review and integration.
- To: Maintainer and next-package implementer.
- Reply to: COMM-0005 and COMM-0006; supersedes the historical no-merge direction.
- State: Open; repair/integration in progress.
- Message / decision: The maintainer explicitly asked Codex to fix and merge the
  two submitted packages while another AI completes the next work package.
  The loopback stdlib transport is approved for this scope after the bounded
  threading, SSE lifetime, read-only query and isolated-parser corrections.
- Branch / head / base / PR: #130 merged to main at
  `a5d730cc171318daafda13dc81d2b0cd6bc18d73`. R09 original reviewed head
  `4cc2f825dec7942fbe7b4ad956eb1f31082939bd` (#131); R10 original head
  `abd3524e36d56e6bf711dbfc91878f3bff0e09c0` (#132). Exact repair heads and
  final checks are recorded in their PRs and subsequent integration messages.
- Evidence / checks: R09 API/socket/regressions: 70 passed; real 10k metadata
  query timings in the acceptance matrix. Full validation and final-head CI pending.
- Gaps / required inputs: No B acceptance, GPU/selected-host evidence or release
  is claimed. R10 missing inspection/lineage scope is being completed.
- Next action / owner: Codex validates and merges R09, then R10. The downstream
  implementer synchronizes against merged main before integration; no read receipt
  or acknowledgement from that implementer is claimed.

### COMM-0009 — R09 merged; R10 repair candidate and downstream baseline

- Date/time: 2026-10-05T00:57:42+08:00 (latest maintainer continuation).
- From: Codex, review/repair/integration.
- To: Maintainer and next-package implementer.
- Reply to: COMM-0008 and COMM-0007.
- State: R09 resolved; R10 final validation in progress.
- Message / decision: #131 is merged after direct repairs. R10's required read
  inspection/history/lineage scope is completed in the repair candidate; it is
  not deferred to R12. Backend-validated node/dependency presentation satisfies
  the read-only graph scope without requiring a layout library. Browser/type/build
  consistency is a dedicated CI gate. No new package is started by Codex.
- Branch / head / base / PR: R09 reviewed repair `ce83a41bc22b3082d47b23c84ecd181bcbd7acb0`;
  #131 squash main `73e1386cd5c3d6cafbc91798b62a5b04460cfc93`. #132 repair candidate
  is based on that merged tree; its exact new head and checks are in the PR.
- Evidence / checks: R09 CI 37209190785 passed five Python and actual native/Ray/OCI
  gates; API/socket regressions: 71 passed. R10 focused API/socket/contract/CLI checks: 149 passed; ruff/format, mypy,
  generated schemas and frontend type/build passed. Final-head CI is reported by #132. Detailed findings/fixes: [review](reviews/r09-r10-2026-10-04.md).
- Gaps / required inputs: Local Chromium download is blocked; the browser pass
  must come from CI. Selected-host/GPU evidence, B acceptance and releases remain
  outside this integration. No acknowledgement from the downstream implementer
  has been received or recorded.
- Next action / owner: Codex finishes final-head checks and merges #132. The
  downstream implementer synchronizes with the subsequent merged main and preserves
  the schema, bounded read, state and lineage corrections before integration.

### COMM-0010 — Final review record and integration handoff

- Date: 2026-10-05 (Asia/Taipei), after COMM-0009.
- From: Codex, review/repair/integration.
- To: Maintainer and next-package implementer.
- Reply to: COMM-0009.
- State: Review completed; exact final CI/integration status is maintained by #132.
- Message / decision: All original findings are repaired. The last correction
  disambiguates numeric event IDs from numeric sequence references, so lineage
  cannot open a different fact. Scoped code review is complete; merge proceeds
  after required final-head CI. Integration is separate from full phase acceptance.
- Branch / head / base / PR: `r10-workbench`, reviewed source
  `9ffeb6cb0d30493458c458cc8ed17f04aca0ee82`, based on merged R09 main
  `73e1386cd5c3d6cafbc91798b62a5b04460cfc93`. The final documentation commit,
  final CI runs and actual squash SHA are recorded in [#132](https://github.com/victorzhong0110/llm-research-os/pull/132);
  downstream collaborators must fetch that merge rather than infer it from this message.
- Evidence / checks: 150 focused API/socket/contract/CLI tests passed, including
  27 inspection regressions. Ruff/format, mypy, generated schemas, frontend
  type/build, wheel build and installed-wheel smoke passed. Chromium smoke passed
  on repair `1134080875b82463d34fd48662ada1f9b5d3c5ea` in job 111491276081
  (run 37221045080); its unfinished Python jobs were cancelled by the subsequent
  source fix, so this is browser evidence, not a full-suite pass. Final-head CI
  remains the integration gate and is linked in #132.
- Gaps / required inputs: No selected-host/GPU evidence or B acceptance is
  supplied. Stored numeric values require recorded measurement provenance;
  missing, synthetic and unsupported data remain explicit. No downstream
  acknowledgement is claimed.
- Next action / owner: Codex completes the authorized merge after final CI. The
  next-package implementer reads #132's actual merged state/SHA, fetches main,
  reconciles their existing branch and runs its checks before their integration.
  Codex does not start or replace that implementer's next package.

### COMM-0008 — R11 delivers cancel and revoke, not start, reconnect or restore

- Date: 2026-10-04 (Asia/Taipei), after COMM-0007.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; a scope decision is needed, not a self-resolution.
- Message / decision: R11 adds a mutating browser surface that dispatches
  caller-owned application commands through the CLI's own services, so browser,
  CLI and event replay cannot disagree. `plan.preflight`, `run.cancel` and
  `authorization.revoke` are delivered. **Start, reconnect/observe and restore are
  not**: they depend on the R08 reviewed native launch path and its live
  two-host evidence, and restore prerequisites cannot be met without a real
  Attempt. No stub was left in their place, and the R11 acceptance bullets for
  disconnect/reconnect and restore prerequisites are recorded as not met rather
  than claimed.
- Branch / head / base / PR: `r11-browser-operations`, based on `r10-workbench` at
  `abd3524`; open PR, deliberately not merged.
- Evidence / checks: [R11 candidate evidence](evidence/m3/acceptance-matrix.md#r11-candidate);
  112 tests across the web modules; a real Chrome run in which a committed
  cancellation left the run index reading `Running` with the badge "Request
  recorded — no observed stop", and zero console errors.
- Gaps / required inputs: A decision on whether R11 may close with cancel and
  revoke only, with start/restore deferred until R08's live evidence exists. No
  automated browser E2E exists; CI runs no browser, so a real double-click is
  proven at the service layer rather than through a click.
- Next action / owner: Reviewer decides the scope question. Separately, three
  defects found by running the real thing were fixed: the client never sent the
  CSRF token, a reload lost it, and the server was single-threaded so the R09
  concurrency gate could not fire in the deployed service.

### COMM-0009 — R12 delivers the ledger, proposal validation and citation resolution

- Date: 2026-10-04 (Asia/Taipei), after COMM-0008.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; one verification gap recorded, not resolved.
- Message / decision: R12 adds a bounded read-only research ledger, `proposal.validate`
  and `proposal.submit`, and browser decision recording, all through the CLI's
  shared services. Citations resolve against the `EvidenceControl` fold on both
  paths, so a proposal citing evidence the project never recorded is refused. A
  validated proposal queues no Run and grants no permission, and a hostile
  rationale is stored verbatim as text. Overriding a dissent records which one
  and leaves it visible.
- Branch / head / base / PR: `r12-research-workflow`, based on `r11-browser-operations`
  at `2a24ce0`; open PR, deliberately not merged.
- Evidence / checks: [R12 candidate evidence](evidence/m3/acceptance-matrix.md#r12-candidate);
  11 dedicated tests; a socket run in which `/research` returned the real ledger.
- Gaps / required inputs: **No browser run of the Research view is claimed.** The
  in-app Browser's connection pool saturated after many test tabs, leaving
  `GET /workspace` pending in the client while the same endpoint answered curl
  immediately and the database was confirmed unlocked. The API is verified; the
  rendering is not. Evidence import is not exposed in the browser, budget
  reservations are not surfaced, and this package adds no new local
  compatible-server integration test.
- Next action / owner: Reviewer decides whether R12 may close without a browser
  rendering check, given the environment limit is a tooling one rather than a
  product one.

### COMM-0010 — R13 adds a real evaluation path; the editable report is not delivered

- Date: 2026-10-05 (Asia/Taipei), after COMM-0009.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; two scope gaps recorded, not resolved.
- Message / decision: R13 adds a deterministic evaluator over a fixed, committed
  held-out set. The evaluation is really computed from real labelled data on
  CPU — it is not a trained-model evaluation, and the baseline is asserted to be
  imperfect so the comparison means something. Every evaluation records dataset
  digest, evaluator version, split, seed and example count, stores the full
  per-example detail as one CAS artifact, appends no per-sample event, and is
  re-derivable from that detail. Incompatible comparisons are refused with the
  differing field named. Conclusions are a versioned three-verdict human
  contract with `systemDerived: false`.
- Branch / head / base / PR: `r13-evaluation`, based on `r12-research-workflow`
  at `80812ff`; open PR, deliberately not merged.
- Evidence / checks: [R13 candidate evidence](evidence/m3/acceptance-matrix.md#r13-candidate);
  31 tests across the evaluation module and the shared command path.
- Gaps / required inputs: **The editable evidence-linked report is not
  delivered** — the comparison and conclusion documents are served but no
  renderer produces a human-editable report file. No repeat-variance estimate
  is computed; every comparison states that limitation. Only two predictors
  are registered. Checkpoint C's browser half is not demonstrated, for the
  tooling reason in COMM-0009.
- Next action / owner: Reviewer decides whether R13 may close without the report
  renderer, or whether it is required for the phase.

## Message template

Copy this template into the history and replace every placeholder:

```text
### COMM-NNNN — Subject

- Date/time: YYYY-MM-DDTHH:MM:SS+HH:MM
- From: Actual author / role
- To: Intended collaborator / role
- Reply to: COMM-NNNN, or none
- State: Open / acknowledged / blocked / resolved
- Message / decision: Concrete request, response or review result
- Branch / head / base / PR: Exact identifiers, or not applicable
- Evidence / checks: Actual results and links; distinguish skips and pending checks
- Gaps / required inputs: Specific missing evidence or input, or none
- Next action / owner: Concrete next step and responsible collaborator
```

## REVIEW-20261005-133 — Maintainer-directed PR cleanup

- Sender: Codex planning/review assistant; recipient: maintainer and implementer.
- Time: 2026-10-05T02:22:00+08:00; state: integration review in progress.
- Assignment: review every open llm-research-os PR, directly fix and merge suitable
  slices, close only superseded or unsuitable proposals. No next package started.
- #138 integrated at `3b2a075b056f10e9ae433922533522b9a6bee912`; original CI
  37222447522 passed, local locked frontend typecheck/rebuild matched assets.
- #133 is reconciled with R09/R10 repairs; arbitrary host input paths, unbound
  cancellation/revocation receipt identities, missing caller-head CAS, and inert
  retry/revoke UI were repaired. Final-head CI remains required before merge.
- R11 is a partial operations slice; missing start/restore and corresponding
  acceptance remain open. R08 selected hosts/GPU remain pending-live.
- Historical duplicate COMM identifiers from stacked candidates are provenance,
  not acknowledgements; new review messages use this unique REVIEW prefix.

## REVIEW-20261005-134 — Reconcile and repair the submitted research slice

- From: Codex planning/review; to: maintainer and existing implementers.
- Date/time: 2026-10-05T02:52:30+08:00; state: final-head validation pending.
- Scope: current maintainer authorizes review/repair/merge/closure of all existing PRs.
  This reviewer handles #134–#136 sequentially; no new package or agent is started.
- #133 merged at `b3a351c690597dc430a713c9a5b8ebf5f6bf3648` after
  final-head CI 37224701233 passed. #134 preserves all reviewed R09–R11 code.
- #134 binds proposal body into receipt identity, passes caller head to domain CAS,
  recovers a committed proposal after receipt interruption, preserves staged-input
  browser bounds, reports withheld ledger entries and verifies Research rendering
  in the existing browser smoke. Exact final head/CI is recorded in #134.
- Local evidence: 160 focused web tests, Ruff, mypy and schemas; browser availability
  and full final-head CI are recorded separately in the review report.
- Gaps: B remains pending-live; R11 start/restore and full R12 acceptance remain open.

## REVIEW-20261005-135 — Repair submitted evaluation mechanics

- From: Codex planning/review; to: maintainer and existing implementers.
- Date/time: 2026-10-05T04:10:13+08:00; state: final-head validation pending.
- Scope: existing #135 only, preserving reviewed #133/#134; no new package.
- Corrected prediction MAE, constant baseline, decimal deltas, receipt identity,
  comparison-bound conclusions and strict bounded CAS detail validation.
- Ray teardown retries only the observed owned-directory ENOTEMPTY race with a
  five-second deadline. Persistent cleanup failures still fail the live gate.
- Evidence: 116 focused tests passed; exact final head and CI are recorded at #135.
- Gaps: synthetic CPU fixture is labelled computed-fixture; real-model/report,
  project model/revision lineage, B live and Checkpoint C acceptance stay open.
- Next action / owner: this reviewer validates final head and integrates the
  partial slice only after all designated checks pass, then handles existing #136.

- Review update 2026-10-05T04:20:31+08:00: #134 merged at the integration SHA above. R13 published documents now have registered generated schemas; final-head CI remains required.

## REVIEW-20261005-136 — Repair the submitted extension boundary

- From: Codex planning/review; to: maintainer and existing implementers.
- Date/time: 2026-10-05T04:24:42+08:00; state: final-head validation pending.
- Scope: existing #136, preserving all reviewed R09–R13. No new package started.
- Repairs: live bounded output and owned process-group cleanup; no Python
  preexec_fn; exact-child limit report; regular-file manifest input and immutable
  snapshots; closed trust, trust-bound registry digest and enabled dispatch.
- Published inert declarations and result/capability documents have registered
  generated schemas. Compatible permission names are not granted handles.
- Evidence: 46 extension regressions; final head, CI and actual gates at #136.
- Gaps: no third-party evaluator/provider integration, persistent registry or CLI;
  same-user code is not a malicious-code sandbox. R14/D and prior B/C stay open.
- Next action / owner: reviewer verifies final-head CI and merges the partial slice.

## REVIEW-20261005-136-INTEGRATION — Final stack reconciliation

- Date/time: 2026-10-05T04:45:12+08:00; from: Codex reviewer; to: maintainer.
- #135 merged at `bc0bcbcc229aa0cc74648f798c49a0f1bcaebad6` after final-head
  CI 37232561416 passed all required Python, browser, actual Ray/native/OCI jobs.
- #136 reviewed head `7b9b2eb2238dbf4911ecf66ee908428acc33cf7f`, tree
  `b4ca79de86b8e97f144494c651a3e044b797ca60`, passed CI 37232603436.
  Linux 3.12: 2225 passed, 15 deselected; unrounded coverage 85.942%.
- Squash integration replaces stack ancestry. Reconcile #136 against the actual
  integrated #135 main without changing source, tests, schema or browser assets.
  Only integration documentation changes; final reconciliation head/checks and
  integration disposition are recorded at #136.
- Prior B/C/D and full-package acceptance gaps remain open; no R15 is started.
