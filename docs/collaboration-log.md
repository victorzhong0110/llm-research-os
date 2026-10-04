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

Snapshot date: **2026-10-04, after 18:41:11 Asia/Taipei**. Verified execution baseline:
`ed6fb30d6cb239ad37a34404814183764bce2a58`.
Verified documentation main: `0acb62bad5dd0a54cb305bf89b2bc9deebb0427b`
([main CI 37183362803](https://github.com/victorzhong0110/llm-research-os/actions/runs/37183362803)
passed). Documentation changes do not advance the execution baseline.

| Item | State and evidence |
| --- | --- |
| Current package | R08; Checkpoint B remains open. R09 has not started. The maintainer authorized sequential completion through R16 on 2026-10-04, merging each predecessor first; the previous B freeze is superseded. Existing acceptance dependencies remain. |
| Native Worker CLI | [#127](https://github.com/victorzhong0110/llm-research-os/pull/127) merged; reviewed CPU execution and observation-only recovery. |
| Optional Ray CPU project jobs | [#128](https://github.com/victorzhong0110/llm-research-os/pull/128) merged at the baseline above; fixed installed driver, durable single submission and native recovery outside Ray. |
| Baseline verification | [Main CI 37144839460](https://github.com/victorzhong0110/llm-research-os/actions/runs/37144839460) passed all five Python and actual Ray project/resource, native and OCI gates. Linux 3.12: 1973 passed, zero failures/skips, coverage 26871/31324 = 85.784063%. Ray project gate: 3 real tests; native gate: 15 real tests. |
| Acceptance gaps | GPU/Kaggle runtime evidence and newly selected actual two-host native/fault evidence remain pending-live. CPU integration does not close these gaps or B. |
| Resource reporting | Controller/remote connectivity, CPU availability and GPU availability must be reported separately. |
| Responsibility | Codex is assigned the remaining implementation, review and sequential integration. COMM-0003 acknowledges the assignment and COMM-0002 handoff. No additional agent was assigned or started. |
| Next gate | Follow the [live acceptance runbook](guides/r08-live-acceptance.md) and [evidence checklist](evidence/m3/r08-live-acceptance.md). Connection configuration and candidate GPU execution access are still missing; see COMM-0004. |

## Open handoffs

| Message | Recipient | State | Next action / owner |
| --- | --- | --- | --- |
| COMM-0004 | Maintainer / resource owner | Blocked on missing input | Supply existing private host connection configuration and GPU/Kaggle execution access so Codex can collect actual R07/R08 evidence. |

COMM-0002 was acknowledged by Codex in COMM-0003. Its evidence gaps remain open;
the acknowledgement does not establish acceptance.

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
