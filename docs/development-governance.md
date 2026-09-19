# Development governance

Status: Maintainer-directed ownership, recorded for integration in R01 (#84).
Constraint record: [ADR-0064](adr/0064-planning-and-implementation-ownership.md).
The maintainer's explicit instructions take precedence over this workflow.
This document assigns review responsibilities; it does not change GitHub access
controls, branch protection, or any person's technical permissions.

## Roles

| Role | Responsibility |
| --- | --- |
| Maintainer | Product priorities, scope acceptance, merge decisions, release decisions, and authorization for external effects |
| Planning/review assistant (currently ChatGPT/Codex) | Author and maintain global plans, work-package boundaries, normative guidance, cross-cutting contract decisions, and acceptance criteria; review implementation and evidence |
| Assigned implementer (Cursor or another assigned coding agent) | Implement the assigned package, choose routine internal details, test and fix it, maintain package-local documentation, and submit inspectable evidence and PRs |

An implementer may receive the full backlog at once. It still executes packages
sequentially with the approved meanings and dependencies. Assignment of code work
does not transfer ownership of the global plan or authorize merging all packages.
The planning/review assistant may also implement when explicitly assigned; roles
are task assignments, not claims of permanent authority over the maintainer.

## File and decision ownership

| Surface | Default handling |
| --- | --- |
| `AGENTS.md`, this file, engineering standards, contributor process sections | Planning/review assistant authors normative changes; maintainer reviews |
| `docs/plans/m3-development-plan.md` | Planning/review assistant owns R identities, scope, dependencies, checkpoints, non-goals, and acceptance criteria |
| Charter, accepted ADRs, cross-cutting authorization/security/state contracts | Preserve accepted text; planning/review assistant prepares reviewed amendments or successor ADRs when needed |
| `docs/evidence/m3/acceptance-matrix.md` | Planning/review assistant owns row meanings and acceptance; implementers append their package's factual candidate evidence and gaps |
| Source, tests, examples, package protocols/guides, package threat-model entries, changelog | Implementer updates within the assigned scope; proposals changing global authority or guarantees require review |
| Generated schemas/status blocks, README translations | Update with their source using existing generators; factual changes must match evidence and accepted scope |

These are editing responsibilities, not blanket bans on useful documentation
work. An implementer should correct package instructions and add honest security
limitations alongside code. It may draft a proposed contract change for review,
but cannot present that proposal as accepted or use it to excuse a violated gate.
Historical failed/partial/live evidence remains attributable to its original SHA.

## Handling a necessary change

1. Identify the exact requirement and the concrete implementation conflict.
2. Submit the proposed difference, rationale, alternatives, impact on dependencies,
   and validation evidence in the PR's `Proposed normative changes` section.
3. Continue unaffected authorized work. Do not silently renumber tasks, reduce
   acceptance, weaken a security boundary, or substitute an easier deliverable.
4. The planning/review assistant incorporates the agreed decision in canonical
   guidance; the maintainer approves material scope/authority changes. Existing
   explicit authorization remains valid and does not need to be requested again.

Routine implementation choices, reversible local work, tests, and in-scope fixes
are autonomous. Do not introduce approval prompts for every file or command.
Only stop the affected work when a necessary decision or authorized resource is
actually missing; report the missing item and complete the independent work.

## PR and checkpoint workflow

- Start from the latest verified main after the preceding slice is integrated.
- One package or smaller coherent slice per independently reviewable PR; no
  parallel R branches and no long stack of unreviewed dependent work.
- Report exact head/base, changed behavior, matching acceptance bullets, actual
  commands/results, skipped or unperformed checks, and remaining gaps.
- Candidate evidence may be committed in the implementation PR. Record the actual
  merge SHA and post-merge CI only after they exist. Review acceptance separately
  from implementation and integration; do not self-label an open PR as merged.
- Checkpoints A (R02–R06), B (R07–R08), C (R09–R13), and D (R14–R16) each
  supply a runnable demo, evidence, and remaining limitations for review.
- Merges remain maintainer-controlled. Do not bypass checks/protection or infer
  authorization to publish, tag, rent machines, or spend from task assignment.
- Existing explicit host/credential/budget authorization may be used within its
  scope. Missing live evidence is pending-live, never a Mock result or prose pass.
- A required acceptance failure is not waived merely because a GitHub job is not
  a ruleset-required check. Distinguish a queued job, a failure, and a skip.

## Completion report

Use the following fields without inventing outcomes:

- Package and slice; branch, head SHA, base, PR.
- Implemented behavior and acceptance coverage.
- Validation commands, environments, outcomes, and evidence locations.
- Candidate / merged / accepted status, each supported separately.
- Known gaps and pending-live work.
- Proposed normative changes, or `none`.
- Next dependency and any specific missing input.

The planning/review assistant handles global reconciliation. The implementer is
not asked to recreate the master plan merely to report implementation progress.
