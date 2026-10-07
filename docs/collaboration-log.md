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

Snapshot date: **2026-10-07, maintainer-assigned engineering completion**. Current main:
`5a99c71e4ac61300e26c49fab8a9401c162d0585` (#141); final-head CI 37627514776
passed all five Python/platform and actual browser/Ray/native/OCI gates. Reviewed
R11 tree `f7c47ffbc0c64664935f7576d0a0cc9511c90ffb` exactly matches integrated main.
Historical sequential PR integration review: Verified reviewed integration:
`bc0bcbcc229aa0cc74648f798c49a0f1bcaebad6` (#135), final-head CI 37232561416
passed. #134 integrated at `89b9ab4f021ff8e3d1e53ef041989ab11605da57` after
final-head CI 37230774848 passed. Historical live execution baseline remains
`ed6fb30d6cb239ad37a34404814183764bce2a58` at its recorded platforms.
Historical verified documentation main: `0acb62bad5dd0a54cb305bf89b2bc9deebb0427b`
([main CI 37183362803](https://github.com/victorzhong0110/llm-research-os/actions/runs/37183362803)
passed). Documentation changes do not advance the execution baseline.

| Item | State and evidence |
| --- | --- |
| Current package | #141 R11 engineering continuation is integrated and verified. R12 continuation is in progress under REVIEW-20261007-R12 on a sequential branch based on that actual main. Full-package and B/C/D acceptance gaps remain open. |
| Native Worker CLI | [#127](https://github.com/victorzhong0110/llm-research-os/pull/127) merged; reviewed CPU execution and observation-only recovery. |
| Optional Ray CPU project jobs | [#128](https://github.com/victorzhong0110/llm-research-os/pull/128) merged at the baseline above; fixed installed driver, durable single submission and native recovery outside Ray. |
| Baseline verification | [Main CI 37144839460](https://github.com/victorzhong0110/llm-research-os/actions/runs/37144839460) passed all five Python and actual Ray project/resource, native and OCI gates. Linux 3.12: 1973 passed, zero failures/skips, coverage 26871/31324 = 85.784063%. Ray project gate: 3 real tests; native gate: 15 real tests. |
| Acceptance gaps | GPU/Kaggle runtime evidence and newly selected actual two-host native/fault evidence remain pending-live. CPU integration does not close these gaps or B. |
| Resource reporting | Controller/remote connectivity, CPU availability and GPU availability must be reported separately. |
| Responsibility | Maintainer explicitly assigned Codex on 2026-10-07 to complete independently executable engineering work while the maintainer handles Mac and human work. Complete R11–R14 sequentially from verified main, preserving earlier review repairs. |
| Downstream gate | Engineering continuation is assigned. Fetch current main before each slice; acceptance dependencies and pending-live inputs remain open, including COMM-0004. Human/Mac work is owned by the maintainer in parallel and must not be represented by synthetic fixtures. |

## Open handoffs

| Message | Recipient | State | Next action / owner |
| --- | --- | --- | --- |
| COMM-0004 | Maintainer / resource owner | Blocked on missing input | Supply existing private host connection configuration and GPU/Kaggle execution access so Codex can collect actual R07/R08 evidence. |
| COMM-0005 / COMM-0006 | Planning/review assistant and maintainer | Resolved for integration by COMM-0008 / COMM-0009 | Bounded local transport approved; explicit maintainer direction superseded withheld merges. No phase acceptance inferred. |
| COMM-0012 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0013 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0014 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0015 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0016 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0017 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0018 | Planning/review assistant and maintainer | Reviewed as partial slices; acceptance open | See REVIEW-20261006-R15/R16 and the final PR records; human trials and live evidence remain pending. |
| COMM-0007 | Planning/review assistant and maintainer | Reviewed in #132 | Reviewed locked workbench integration preserved; full R10 acceptance remains separate. |
| COMM-0008 | Planning/review assistant and maintainer | Reviewed as partial integration in #133 | Start/restore and B acceptance gaps remain in the matrix. |

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

### COMM-0011 — R14 adds a bounded extension surface; three scope gaps recorded

- Date: 2026-10-05 (Asia/Taipei), after COMM-0010.
- From: Codex, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; three scope gaps recorded, not resolved.
- Message / decision: R14 adds a versioned manifest contract with a closed
  permission set, a compatibility refusal, a bounded subprocess host for one
  reviewed same-user adapter, and enable/disable/uninstall. Loading a manifest
  is inert and is proven so by two tests that run the entry module and assert
  its marker file never appears. A declared permission is a request: an unknown
  name refuses the manifest rather than being narrowed, and `trust="untrusted"`
  is refused because no verified isolation profile exists here.
- Branch / head / base / PR: `r14-extension-boundary`, based on `r13-evaluation`
  at `3e67bb7`; open PR, deliberately not merged.
- Evidence / checks: [R14 candidate evidence](evidence/m3/acceptance-matrix.md#r14-candidate);
  27 tests.
- Gaps / required inputs: No evaluator or provider extension point is exercised
  with a real external extension; no `researchos extensions` CLI command;
  `BlockRegistry` is not merged into this registry, so blocks and extensions
  remain separate concepts; the "removing training adapters leaves core
  functional" acceptance bullet is not exercised because this package adds and
  removes no training adapter.
- Next action / owner: Reviewer decides whether R14 may close on a Python-only
  surface with one inline adapter, or requires a CLI and a real third-party
  extension.

### COMM-0012 — R15 delivers verified prefix backup, redacted diagnostics, and offline install

- Date: 2026-10-05 (Asia/Taipei), after COMM-0011.
- From: Assigned implementer, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0003.
- State: Open; scope gaps recorded, not resolved.
- Message / decision: R15 adds `researchos backup create | verify | restore`,
  `researchos workspace doctor | migrate | demo`, plus a protocol and guide. A backup is
  a verified high-water prefix of the EventStore plus the immutable CAS objects
  that prefix references. The SQLite copy uses the online backup API and is then
  collapsed to one standalone file; the image is re-verified from a copy before
  it is published. A restore verifies the image completely before writing
  anything, appends no event, starts no Worker, and returns every non-terminal
  Run as `unknown` with `reconcile-manually` (ADR-0054). Diagnostics carry
  counts, booleans and caller-supplied identifiers only, so a report is safe to
  paste into an issue. `workspace demo` builds a working workspace in one command
  from a minimal corpus packaged inside the wheel, so the clean-install journey
  no longer borrows a corpus from a source checkout.
- Branch / head / base / PR: `r15-installation-recovery`, based on
  `r14-extension-boundary` at `45456c4`; open PR, deliberately not merged, base
  stated on the PR. The push and PR creation are blocked in this environment by
  absent GitHub credentials; see "Required input" below.
- Evidence / checks: [R15 candidate evidence](evidence/m3/acceptance-matrix.md#r15-candidate-evidence);
  R15 tests across three files; clean install outside
  source reported `doctorHealthy: true`, `packagedBundle: true`, and a
  backup/verify/restore round trip with `ledgerMatches: true` and
  `appendedEvents: 0`. Whole selected suite 2,129 passed / 6 failed, every
  failure checked as pre-existing or environmental. Ruff, format, mypy, schema,
  catalog and status checks pass locally. **No CI run exists for this branch and
  the 85% coverage floor is not yet measured on it.**
- Gaps / required inputs: No replication, encryption, scheduling, retention, or
  artifact garbage collection; copying an image off the machine is an operator
  action. `workspace demo` is a bounded single-workspace demonstration, not a
  guided tutorial, and it does not exercise the browser surface. An independent
  adversarial review of this branch found two critical and several major
  defects before submission, all reproduced and all corrected; they are recorded
  in full in the R15 candidate section, and the protocol document's "verify
  trusts nothing in the manifest" claim was rewritten rather than restated. Downgrade is refused rather than supported. Worker identity is not part
  of an image, and no live two-host restore was exercised because that access is
  still missing (COMM-0004). An earlier change making `init_workspace` create the
  control store was **reverted**: `ApplicationService.open` reporting
  `store-missing` on a fresh workspace is the accepted R02 contract, so the
  doctor reports that state instead. The residual consequence — `evidence import`
  fails on a brand-new workspace until some other command creates the store — is
  recorded as BACKLOG-06 for a decision rather than changed unilaterally. This
  implementer has **no GitHub credentials in this environment** and could not
  push a branch or open a pull request; the commits are prepared locally and the
  PR still needs a maintainer push or a token.
- Next action / owner: Reviewer decides whether R15 may close on a local verified
  prefix backup with no replication or encryption, and whether BACKLOG-06 should
  change the R02 fresh-workspace contract. The two corrected criticals are worth
  a reviewer's own attention first: a manifest that dropped one object entry
  verified, and a `#` in the workspace path made the backup read a different
  database. Maintainer pushes the branches or
  supplies a token so the two open PRs exist.

### COMM-0013 — R16 prepares the trial kit; the trials themselves are unperformed

- Date: 2026-10-05 (Asia/Taipei), after COMM-0012.
- From: Assigned implementer, implementation.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0012.
- State: Open; blocked on maintainer action, not on further implementation.
- Message / decision: R16 is the one package whose deliverable is human work by
  people who did not implement the system, so this branch contributes the kit
  that makes such a trial measurable and the record that makes its absence
  visible. Five fixed offline tasks (T1–T5) need no key and no GPU; the record
  template's "interventions" and "confusion observed" fields are the measurement
  and an implementer may not fill them in on a participant's behalf. An
  aggregated closure record rolls up every R01–R15 row and lists BACKLOG-01..12.
  No trial was performed, rehearsed by an implementer, or inferred from local
  results, and none is simulated.
- Branch / head / base / PR: `r16-independent-trials`, based on
  `r15-installation-recovery`; open PR, deliberately not merged. Same credential
  blocker as COMM-0012.
- Evidence / checks: [R16 candidate evidence](evidence/m3/acceptance-matrix.md#r16-candidate-evidence);
  [trial kit](evidence/m3/r16-independent-trials.md);
  [closure record](evidence/m3/m3-closure-record.md).
- Gaps / required inputs: TRIAL-01 and TRIAL-02 need two participants who did
  not build the system; the maintainer handles invitations and authorization.
  TRIAL-03, the required authorized remote journey, is blocked on the same
  missing two-host and GPU access as COMM-0004. No main-path defect can be
  fixed or re-run until a trial finds one. The R10–R14 matrix rows link to
  `#r1x-candidate-evidence` anchors no section defines; the R15 anchor is defined
  here and the earlier ones are left alone as another package's record.
- Next action / owner: Maintainer performs TRIAL-01/02 invitations and supplies
  TRIAL-03 access. Planning/review assistant reconciles the draft closure record
  against real outcomes, then the maintainer reviews Checkpoint D. **Checkpoint D
  cannot be claimed complete from this branch.**

### COMM-0015 — R15 and R16 rebased onto merged R10–R14; the stacking deviation no longer applies

- Date: 2026-10-05 (Asia/Taipei), after COMM-0014.
- From: Assigned implementer.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0014, and the merge of #132–#136.
- State: Open; awaiting review of the rebased candidates.
- Message / decision: R10, R11, R12, R13 and R14 were merged into `main` while R15
  and R16 were being written (`bf8a45a`, with `b3a351c` through `bf8a45a` as the
  integration commits). The candidate stack those two packages were built on was
  deleted, and merged R14 is **not** the candidate R14 — the review repairs landed
  in between. R15 and R16 have been rebased onto merged `main` rather than
  submitted against a branch that no longer exists.

  Three consequences are worth stating plainly, because each is a case where the
  merge invalidated something I had already written:

  **The port-conflict fix was already delivered.** R15 fixed
  `web serve` raising an unhandled `OSError` on a taken port. Merged R14 already
  guards `make_server` and returns `listener-unavailable`. The R15 change is
  **dropped**, and the matrix, guide and changelog now credit merged R14 instead.
  The R15 acceptance case is met by the merged implementation, not by this branch.

  **My change to `web/serve.py` would have regressed R14.** It named the port and
  used the code `port-unavailable`, where the merged code says
  `listener-unavailable` and does not. The merged behaviour is accepted, so
  changing it here would be overriding a review decision for a cosmetic gain. The
  port-naming improvement is left as a review suggestion, not taken.

  **A wholesale file copy would have silently reverted reviewed work.** Files
  R15 and R16 both touch — `cli/contracts.py`, `cli/parser.py`,
  `application/workspace.py`, `projections/sqlite.py`, the CI workflow, and the
  documentation tables — were all changed by the merged packages. Copying R15's
  version of `cli/contracts.py` over main's removed the evaluation and extension
  schema registrations added by merged R13 and R14. The rebase was redone as a
  cherry-pick so those conflicts surfaced. The merged rows for R09–R14 in the
  acceptance matrix are authoritative; the stale pre-merge "candidate on this
  branch" rows are deleted rather than left to contradict them.

  The **stacking deviation recorded in COMM-0006 no longer applies to R15 and
  R16**: with R09–R14 merged, R15 is proposed against `main` and R16 against
  `r15-installation-recovery`, which is the sequential shape the maintainer has
  been using since #131. Both remain deliberately unmerged.

  The COMM-0014 decisions are unchanged: R15 closes as a scoped candidate with
  replication, encryption, scheduling, retention and downgrade named as
  limitations; the R10–R14 anchors get a routing table rather than retroactive
  edits; and a fresh workspace still does not materialize its EventStore at init.

  R16's trials remain unperformed and Checkpoint D remains open.
- Branch / head / base / PR: `r15-installation-recovery` against `main`;
  `r16-independent-trials` against `r15-installation-recovery`. Both open, both
  deliberately unmerged.
- Evidence / checks: [R15 candidate evidence](evidence/m3/acceptance-matrix.md#r15-candidate-evidence),
  [R16 candidate evidence](evidence/m3/acceptance-matrix.md#r16-candidate-evidence).
- Gaps / required inputs: No trial has been performed. TRIAL-01/02 need two
  people who did not build the system; TRIAL-03 needs the authorized remote
  journey that COMM-0004 still records as missing.
- Next action / owner: Maintainer reviews the rebased R15, then R16. Whether
  `listener-unavailable` should name the port is a maintainer call.

### COMM-0016 — Store errors surface codes; trial records need the person's own confirmation; four SSH failures explained

- Date: 2026-10-05 (Asia/Taipei), after COMM-0015.
- From: Assigned implementer.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0014, COMM-0015, and the R16 evidence proposal in the acceptance matrix.
- State: Open; awaiting review.
- Message / decision: Three items, all carried out on maintainer instruction. Local
  only: no merge, no deployment, no message sent outside this repository.

  **`ProblemReport.type` is a code, adopted.** The proposal recorded in the R16
  evidence is taken. `EventStoreSchemaError` joins the coded errors, so a missing
  control store reports `event-store-absent` rather than `EventStoreSchemaError`.
  The protocol now states the rule rather than leaving it to be inferred from the
  code: `type` is a stable machine identifier, a caller may branch on it, it is
  never a class name, and the class name survives only as the fallback for errors
  that define no codes. Three CLI tests that pinned the class name were updated
  rather than worked around, and `tests/test_problem_report_type_vocabulary.py`
  pins the vocabulary and the one-directional fallback.

  **Writing that test found four more host-path leaks.** `_validate_database_path`
  interpolated the path into its missing-parent, inspect-failure, symbolic-link
  and not-a-regular-file messages, and none of the four had a test. The first
  version of the new test passed without covering them, because the path it used
  had a missing *parent* and therefore reached a different branch than the
  missing-database case it was written for. All four messages are now path-free
  and the test is parameterised across the whole family. The control-store
  surface is now path-free end to end, which is the claim the project already made
  about these errors and had not earned.

  **A trial record is pending until the person confirms it.** The contract already
  refused an implementer-authored measurement, but nothing stopped an **observer**
  from filing every record on a participant's behalf. An observer-authored roll-up
  is evidence that someone watched, not that a person took part, and that is the
  distinction R16 exists to make. `participantConfirmed` now defaults to false,
  `confirmedAt` is required when it is set and refused when it is not, and an
  implementer may not set it at all. `confirmedParticipants`, `completedTasks` and
  `remoteJourneys` are confirmed-only, and `aggregate` reports `participants`,
  `observedParticipants` and `pendingConfirmation` as three separate numbers so a
  half-finished programme cannot read as a finished one. A confirmed `REMOTE`
  record is the only thing that satisfies the authorized-remote requirement,
  because that requirement is about access a person was actually given.

  **The four `test_native_ssh_live.py` failures were not a product defect.** They
  were the harness simulating a non-compliant host. The local transport runs the
  real remote command, which is `python3 -I -c ...`, so `python3` was resolved
  from `PATH` **inside this container**; that is Python 3.11.2, while the probe
  requires 3.12 or newer on a worker host. The probe was correct to refuse it, and
  four tests asserting `ready` were failing for a reason unrelated to what they
  test. `_setup` now pins `PATH` to the interpreter running the suite, so the
  simulated host meets the documented minimum whatever the ambient system python
  is, and a new guard test fails loudly if that pinning ever stops working. The
  old-host rejection is untouched and still tested directly by
  monkeypatching `version_info` to `(3, 11)`. All 39 tests in the file pass. CI
  runs 3.12/3.13, where these tests passed all along.
- Branch / head / base / PR: `r16-independent-trials`, based on
  `r15-installation-recovery`; open PR, deliberately unmerged. **Not pushed.**
- Evidence / checks: [R16 candidate evidence](evidence/m3/acceptance-matrix.md#r16-candidate-evidence),
  [`problem-report-v0alpha1.md`](protocols/problem-report-v0alpha1.md).
- Gaps / required inputs: Still no trial performed. TRIAL-01/02 need two people
  who did not build the system; each record now additionally needs **that person's
  own confirmation**, which no implementer or observer can supply on their behalf.
  TRIAL-03 remains blocked on the two-host and GPU access in COMM-0004. Checkpoint D
  cannot be claimed complete.
- Next action / owner: Maintainer reviews the three changes. Invitations for
  TRIAL-01/02 and the access for TRIAL-03 remain the only unblocking inputs.

### COMM-0017 — Implementer self-run of T1–T5; four main-path defects fixed; closure record corrected

- Date: 2026-10-05 (Asia/Taipei), after COMM-0016.
- From: Assigned implementer.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0016, and the R16 "fix main-path defects" deliverable.
- State: Open; awaiting review. Checkpoint D remains open.
- Message / decision: The plan's defect deliverable needs defects, and the only
  defects that count come from TRIAL-01/02, which have not run. So I ran T1–T5
  myself from a clean wheel outside any checkout, to find what a person who did
  not build this would hit first.

  **What this is not.** Not TRIAL-01, not TRIAL-02, no `TrialRecord`, no
  participant, and nothing that can be self-confirmed under the rule added in
  COMM-0016. It contributes implementation findings only. A rehearsal by the
  implementer is evidence about the product and never about its usability for
  someone else, and the acceptance language is unchanged.

  **Four defects, all fixed.** A freshly initialized workspace reported
  `healthy: false` with three `failed` checks, because "no control store yet" is
  the *expected* R02 state and was being reported as a fault — and T2 tells a
  user to init a workspace and read exactly that output. `app init` required four
  layout arguments with no defaults and no help text, and T1 forbids cloning the
  repository, so `--help` was the only documentation a participant would have.
  `backup restore` took `--root` where `backup create` took `--out`, so the flag
  meant source on one subcommand and destination on the other; the self-run
  copied the wrong one, which is how a participant would have found it. And
  `objects.referenced` reported `verified: false` on a shallow run that had
  re-hashed nothing, which reads as "these objects are not fine" on an `ok`
  check. Detail in the R16 evidence.

  **T3 was not executable and now is.** "Import the example evidence" pointed at
  a file that lived only in the repository T1 forbids cloning. The evidence
  request and its Markdown source are now packaged inside the wheel, and
  `workspace demo` prints the exact import command as its first next hint. That
  makes the journey runnable by copy-paste. It does not make it observed.

  **One limitation I am not going to smooth over.** The doctor cannot distinguish
  a workspace that never had a control store from one that had one removed:
  nothing survives deleting the store, and the receipt store is not created on
  this path. Rather than invent a signal, the `skipped` check names the question
  in its note. The trade is deliberate — a fresh workspace is no longer alarmed,
  and an operator who knows they had a store is told what to look at — but a
  removed store will read as `skipped`, not `failed`.

  **The closure record was wrong and is corrected.** Its R09–R14 rows still said
  "candidate, unmerged" for packages that were merged while I was working, and
  one row claimed `BlockRegistry` remained unmerged in R14 when the integration
  commit had merged it. Those rows now carry the real merge SHAs and the
  acceptance status the matrix records. A closure record that misstates what
  merged is worse than no record.

  Added a triage section separating what is blocked on code, on people, and on
  access. Everything still open is blocked on a person, an authorization, or
  hardware. Release naming, versioning, tagging and publication remain maintainer
  decisions and were not pre-taken; no new paid activity was required or
  attempted; nothing was deployed.
- Branch / head / base / PR: `r16-independent-trials` at `a2f00ee` plus this
  work; PR #140, deliberately unmerged. Pushed to the branch only. `main` and
  `r15-installation-recovery` untouched.
- Evidence / checks: [R16 candidate evidence](evidence/m3/acceptance-matrix.md#r16-candidate-evidence),
  [closure record and triage](evidence/m3/m3-closure-record.md).
- Gaps / required inputs: **待本人确认 — TRIAL-01 and TRIAL-02** need two people
  who did not build the system, invited by the maintainer, and each record now
  needs that person's own confirmation. **待本人确认 — COMM-0004**: TRIAL-03
  still needs two-host connection configuration and selected-GPU access. Neither
  can be manufactured locally. TRIAL-04 stays open until the trials produce
  findings. Checkpoint D cannot be claimed complete.
- Next action / owner: Maintainer performs the TRIAL-01/02 invitations and
  supplies the TRIAL-03 access. The planning/review assistant reconciles the
  closure record against real outcomes once trials exist.

### COMM-0018 — The doctor now distinguishes a fresh workspace from a gutted one; CLI coverage closed

- Date: 2026-10-06 (Asia/Taipei), after COMM-0017.
- From: Assigned implementer.
- To: Planning/review assistant and maintainer.
- Reply to: COMM-0017, which named this as a limitation.
- State: Open; awaiting review. Checkpoint D remains open.
- Message / decision: COMM-0017 recorded a weakness rather than hiding it, and
  this closes it.

  **A control store that existed and is now gone is data loss, and the report now
  says so.** The ambiguity was real: `init_workspace` does not create a control
  store, so "no store" is a normal state, and deleting a store produced identical
  evidence. Two signals, because either alone has a blind spot. A lifecycle
  marker, `.control-store.json`, is written beside the control database the first
  time a store is created, which catches a deleted database; and
  `init_workspace` always creates the control directory, so a missing directory
  catches a wholesale `rm -rf control`, which takes the marker with it.
  `restore_backup` writes the marker too, because the restore path bypasses
  `EventStore`'s create branch and would otherwise leave a restored workspace
  unable to tell that its store was later deleted — verified by deleting the
  store out of a restored workspace and confirming the report.

  The marker is a local lifecycle artifact on the same footing as
  `workspace.json`, not a published contract: a kind, a version and a timestamp,
  with no path and no project id, so there is nothing in it to redact. It is
  written best-effort on purpose. A store that cannot also write a sibling marker
  has already failed for a reason the caller will see, and refusing to open it
  would turn a diagnostic aid into a hard dependency.

  **An argument mistake is now a coded error rather than a bare exit.** Writing
  the CLI tests surfaced a defect in my own earlier change: a missing or
  duplicated `backup restore` destination raised `SystemExit` with a string, so
  the CLI printed a sentence and exited 1 where every other failure in the same
  command prints a closed code on stderr and exits 2. It now raises
  `backup-restore-ambiguous` and `backup-restore-destination-missing` through the
  existing path.

  **The CLI layer was the least covered code I had added.** `trial_commands` was
  at 35.5%, `recovery_commands` at 39.0%, and `application_commands` at 52.3% —
  the whole dispatch layer, because the other suites test the library functions
  underneath and never the commands. `tests/test_recovery_cli.py` now drives
  `main(argv)` directly: the same parser, the same handlers, the same exit codes,
  and measurable. Those three are now 93.4%, 90.0% and 81.8%. In-process rather
  than `subprocess` is deliberate — a child process reports coverage to a
  different file, so a suite that spawns the CLI cannot be measured at all. The
  two things it cannot show, a bad interpreter and an uncaught crash's exit
  status, are covered by the installed-wheel smoke, which does run the real
  entrypoint.
- Branch / head / base / PR: `r16-independent-trials`; PR #140, deliberately
  unmerged. `main` untouched.
- Evidence / checks: [R16 candidate evidence](evidence/m3/acceptance-matrix.md#r16-candidate-evidence).
- Gaps / required inputs: **待本人确认 — TRIAL-01 and TRIAL-02** need two people
  who did not build the system, invited by the maintainer, and each record needs
  that person's own confirmation. **待本人确认 — COMM-0004**: TRIAL-03 needs
  two-host connection configuration and selected-GPU access. None of it is
  fabricable, and none of it was simulated. TRIAL-04 stays open until the trials
  produce findings. Checkpoint D cannot be claimed complete.
- Next action / owner: Maintainer reviews the marker and the CLI suite;
  invitations and access remain the only unblocking inputs.

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


### REVIEW-20261006-R15 — Installation/recovery review and repair

- Date: 2026-10-06 UTC.
- From: Codex, planning/review assistant, under the maintainer's standing instruction to review, repair, merge or close all PRs.
- Reply to: COMM-0012 / COMM-0015; PR #139.
- Result: Keep the local prefix-backup slice. Replication, encryption, scheduling, retention and downgrade support remain explicit limitations; no release or live-host acceptance is inferred.
- Repairs: Bind the restored snapshot's bytes and size to the verified manifest before opening it; derive the source ledger from that private copy. Refuse restore layouts escaping the new workspace. Use unique staging directories so concurrent operations cannot delete each other's work. Bound manifest reads and reject non-regular backup inputs without blocking on FIFOs.
- Validation: Original-head CI passed all Python, workbench, Ray, native and OCI jobs. Added regressions cover snapshot replacement after verification, external layout refusal and FIFO rejection. Repair-head CI must pass before merge.
- Acceptance: Reviewed installation/recovery code may integrate; full M3 and Checkpoint D remain open. R16 human trials and selected-host/GPU evidence are still absent.


### REVIEW-20261006-R16 — Trial tooling review and repair

- Date: 2026-10-06 UTC.
- From: Codex, planning/review assistant, under the maintainer's standing PR-cleanup authorization.
- Reply to: COMM-0013 / COMM-0014 / COMM-0016 / COMM-0017 / COMM-0018; PR #140.
- Review result: Integrate the trial tooling and main-path repairs as a partial R16 slice; no human trial has happened, and full R16 / Checkpoint D is not accepted.
- Repairs: Trial completion must agree with its verdict; blank evidence references and duplicate trial IDs are refused; the published task vocabulary is closed. Fixed blocker coverage is derived from confirmed, completed T1–T5 journeys for two people and a completed REMOTE journey, never from trial-ID substrings or an omitted blocker list. Extra blockers remain open. The aggregate reports task coverage separately and always requires maintainer acceptance. Scaffold slots retain the supplied participant and author.
- Further repairs: SQLite initialization errors carry no host path; generated demonstration hints quote shell arguments. The R15 verified-copy, confined-layout and unique-staging repairs are preserved.
- Protocol review: Adopt the coded EventStoreSchemaError routing already proposed in the branch; retain the documented class-name fallback for uncoded errors. This is a pre-release error-surface change and the dedicated vocabulary tests pin it.
- Validation: Focused trial and error tests passed (48 tests before the additional leak/hint regressions); full combined focused checks and final-head CI are recorded with integration. Original #140 CI passed all supported Python and actual browser/Ray/native/OCI jobs; original evidence does not stand in for final repair checks.
- Remaining work: Independent participants and their confirmations, authorized remote evidence, trial defect resolution and full R14/M3 acceptance. No fabricated trial, release, new paid activity or deployment.

R15 integration confirmed on 2026-10-06: #139 merged at `76e16d2aae2cc748e0e9c944794dc574cbc66937` after final-head CI 37454556583 passed all five Python, actual browser, Ray, native and OCI gates. Linux Python 3.12: 2328 passed, 15 deselected; coverage 86.13%, unrounded floor check passed. The integrated tree is `23f3c89caad63a9055eb8ee66358c5ae90d82750`, identical to the reviewed repair tree. #140 preserves that tree's recovery fixes and records this actual main as a parent; its final-head CI remains the gate for its own integration.


### REVIEW-20261007-R11 — Assigned engineering continuation

- Date/time: 2026-10-07T20:57:46+08:00 (maintainer assignment).
- From: Codex recording and acknowledging the maintainer's direction.
- To: Maintainer and subsequent collaborators; reply to COMM-0008 and prior reviews.
- State: Implementation and candidate validation in progress; no merge or acceptance claimed.
- Scope: Complete independent R11–R14 engineering sequentially. The maintainer
  concurrently handles required Mac and personal/human work. This assignment
  allows engineering continuation with B/live/human acceptance still open.
- Branch/base: `work/20261007-r11-completion`, based on verified main
  `a32493efb800a3c573ad49aef7077b006d6569ca`. No other R package branch started.
- R11 behavior: Operator-installed profile dispatch uses the existing reviewed
  native executor and checkpoint gates. Material-bound inspection, durable Run
  reservation, conservative observation, reconnect, verified new-root backup
  restore and exact-body retry preserve existing authority and unknown semantics.
- Candidate evidence: Actual CPU and valid source/target checkpoint regression,
  shared-service/web regression, generated schemas, browser build/type checks
  and full final-head checks are recorded in the implementation PR.
- Acceptance: No selected-host/GPU evidence or participant journey is inferred.
  This is engineering completion under explicit assignment, not B/C/D acceptance.
- Next action/owner: Codex verifies this slice, integrates with standing merge
  authorization, then starts R12 from actual main. Maintainer owns parallel Mac,
  private environment/provider and human acceptance observations.


### REVIEW-20261007-R12 — Evidence-linked browser research continuation

- Date: 2026-10-07 UTC. From: Codex, planning/review and implementation under the maintainer's continuing assignment. Reply to REVIEW-20261007-R11.
- State: R11 #141 integrated at `5a99c71e4ac61300e26c49fab8a9401c162d0585` after final-head CI 37627514776 passed all applicable jobs. Linux Python 3.12: 2430 passed; unrounded coverage 30996/35885 = 86.375923%. Reviewed and integrated trees match.
- Branch/base: `work/20261007-r12-completion`, based on that verified main. No R13/R14 branch started.
- Scope: Complete shared-service/browser evidence import, Mock/compatible-provider generation, conservative model observation, explicit budget, artifact-bound semantic diff, validated/editable drafts and human decisions/questions/dissent. Reuse existing M1 objects and preserve reviewed R12 receipt/head repairs.
- Contract difference: Path-based application proposal operations now also require base/candidate CAS bindings; asserted diff hashes alone are refused. Historical M1 CLI/event contracts and accepted evidence remain unchanged. New contracts and exact behavior are documented in the research workflow protocol. No execution or acceptance authority is added.
- Candidate evidence: Actual loopback HTTP and injected remote-budget fault regression (no paid call), Mock generation, frozen inbox/symlink checks, forged diff/citation refusal, caller-head CAS, lost receipt recovery/observation and preserved rejection/questions/dissent. Frontend type/build and schema checks are recorded with this PR. Local Chromium executable is unavailable; committed-bundle browser CI remains required evidence.
- Local verification: 139 focused regressions passed; final application/CLI contract rerun: 49 passed. Ruff, formatting (626 files), mypy (269 source files), generated schemas, catalogs/status, digest vectors, frontend type/build, package build and a fresh installed wheel without training extras passed. Full local suite: 2412 passed, 12 failed, 21 skipped, 15 deselected. Failures are the same POSIX/process/socket cases observed on the R11 base; they remain failures, without test changes or waivers. Unrounded coverage: 31067/36360 = 85.442794%, passing the 85% gate. Actual final-head CI/browser results must be recorded before integration.
- Gaps: Actual private provider/environment use, selected GPU/two-host work, human research journeys and Checkpoint C remain pending. Synthetic test decisions do not represent a real person's acceptance.
- Next owner/action: Codex verifies final-head checks, integrates under standing merge authorization, then starts R13 from actual verified main. The maintainer owns concurrent Mac/private-environment/human evidence.
