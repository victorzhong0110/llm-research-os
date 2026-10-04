# M3 scoped closure record — candidate for review

Status: **candidate draft on the R16 branch; not merged, not accepted.** This
record aggregates the evidence each M3 package actually recorded. It closes
nothing. Acceptance remains a maintainer review against unchanged criteria, and
the plan is explicit that code merging, CI passing, and a package being present
are not acceptance.

Ownership note: the M3 plan assigns the scoped closure ADR and remaining backlog
to the planning/review assistant. This file is therefore a **proposed input** to
that review, not the closure decision itself, and it deliberately does not
create or modify any acceptance criterion.

## Phase scope supported by recorded evidence

| Package | Implementation | Verification recorded | Accepted? |
| --- | --- | --- | --- |
| R01 | Merged #84 at `7d1bcbe` | Plan, matrix, status agree | Maintainer-directed integration |
| R02 | Merged #105 at `9fb8f514` | [CI 35810232891](https://github.com/victorzhong0110/llm-research-os/actions/runs/35810232891); scoped application command and receipt contract | Scoped review accepted after P1 fixes |
| R03 | Merged #109 at `1a08bfed` | Reviewed validation-only contract | Accepted; **no live launch** |
| R04 | Merged #111 at `55b72268` | Verifiable code and environment binding | Corrected PR CI passed; main CI not cited in the row |
| R05 | Merged #114 at `7abe55c1` | Real reviewed CPU entrypoint, artifacts, completion/failure facts | PR CI passed; checkpoint A awaited R06 |
| R06 | Merged #115 at `62cfad00` | [CI 36695842170](https://github.com/victorzhong0110/llm-research-os/actions/runs/36695842170) | No blanket checkpoint acceptance |
| R07 | Merged #116 at `1f8b1422` | [CI 36696795007](https://github.com/victorzhong0110/llm-research-os/actions/runs/36696795007) | **Authorized-host acceptance pending-live** |
| R08 | Multiple merged slices through #128 | [CI 37141821193](https://github.com/victorzhong0110/llm-research-os/actions/runs/37141821193) and earlier | **Two-host and GPU evidence pending-live** |
| R09 | Candidate, PR #131 (unmerged) | Candidate tests on branch | Not accepted |
| R10 | Candidate, PR #132 (unmerged) | Candidate tests on branch | Not accepted; no CI browser E2E |
| R11 | Candidate, PR #133 (unmerged) | Candidate tests on branch | Not accepted |
| R12 | Candidate, PR #134 (unmerged) | Candidate tests on branch | Not accepted |
| R13 | Candidate, PR #135 (unmerged) | Candidate tests on branch | Not accepted |
| R14 | Candidate, PR #136 (unmerged) | 27 tests on branch | Not accepted; no CLI, `BlockRegistry` separate |
| R15 | Candidate, PR (R15 branch, unmerged) | 62 R15 tests; local static checks; clean-install smoke outside source | Not accepted; no CI run yet |
| R16 | Candidate, R16 branch (unmerged) | Trial kit committed; **no trial performed** | Not accepted; Checkpoint D open |

Full per-package rows and candidate detail are in the
[acceptance matrix](acceptance-matrix.md). This table is a roll-up, not a
substitute.

## Checkpoint status

| Checkpoint | Packages | State |
| --- | --- | --- |
| A | R02–R06 | Not claimed as blanket accepted; R05/R06 candidate evidence recorded |
| B | R07–R08 | **Open.** New selected-host and GPU evidence is missing; see COMM-0004 |
| C | R09–R13 | **Open.** Candidates exist for every package; none merged or accepted |
| D | R14–R16 | **Open.** Extension boundary and install/backup/restore are candidates; independent trials are unperformed |

No checkpoint is claimed complete by this record.

## Remaining backlog

Ordered by what blocks the next gate, not by effort.

| ID | Item | Blocked on | Owner |
| --- | --- | --- | --- |
| BACKLOG-01 | Supply existing private host connection configuration and selected-GPU/Kaggle access | Maintainer / resource owner | Maintainer |
| BACKLOG-02 | Collect the R07/R08 live two-host and GPU evidence, then review Checkpoint B | BACKLOG-01 | Assigned implementer |
| BACKLOG-03 | Review, merge, and accept the stacked R09–R16 candidates sequentially | Maintainer | Maintainer |
| BACKLOG-04 | Close the R10–R14 broken `#r1x-candidate-evidence` matrix anchors | Reviewer decision on whose record to edit | Planning/review assistant |
| BACKLOG-05 | Add a `researchos extensions` CLI or accept the R14 Python-only surface | Reviewer decision | Planning/review assistant |
| BACKLOG-06 | Decide whether a fresh workspace should materialize its EventStore at init | Reviewer decision; current R02 contract is `store-missing` | Planning/review assistant |
| BACKLOG-07 | Run the R16 independent trials (TRIAL-01/02) | Maintainer invitations | Maintainer |
| BACKLOG-08 | Run the authorized remote trial journey (TRIAL-03) | BACKLOG-01 | Maintainer / resource owner |
| BACKLOG-09 | Measure and hold the 85% coverage floor on the R15/R16 branches | A CI run for those branches | Assigned implementer |
| BACKLOG-10 | Decide release name, version, tag, and publication | Separate maintainer decision, not prepared here | Maintainer |
| BACKLOG-11 | Review Issue #53 against the scoped R03–R06 checklist | Maintainer review | Maintainer |
| BACKLOG-12 | Add artifact garbage collection or an explicit no-GC decision for backup images | Reviewer decision | Planning/review assistant |

## Evidence boundaries this record preserves

- Historical M1/M2 acceptance stays accepted **at its original platform and
  SHA**. It does not certify any M3 implementation.
- The M0/M1 baseline in the snapshot is real for the paths it names and says
  nothing about R09–R16.
- Synthetic metrics remain labeled synthetic. A real baseline/candidate result
  is required for a research conclusion; one improved score does not establish
  one, and a negative result is a valid result.
- `ready`, `authorized`, a passing preflight, and a simulated `completed` are
  not launch credentials and not scientific conclusions.
- A passing CI run is not scope acceptance.
- An open PR is not merged, and a merge is an integration fact rather than
  acceptance.

## What a reviewer should decide

1. Whether Checkpoint B can be reviewed at all before BACKLOG-01 is supplied, or
   must wait for live two-host evidence.
2. Whether the stacked, unmerged R09–R16 sequence is accepted as a delivery
   shape (COMM-0006 remains open) or replaced by a pause at the first unmerged
   package.
3. Whether R15 may close without replication, encryption, or downgrade support.
4. Whether R14 may close on a Python-only surface with one inline adapter.
5. Whether the draft closure direction above is acceptable as the planning
   assistant's starting point, given that this file was authored by an
   implementer and proposes no acceptance change.
