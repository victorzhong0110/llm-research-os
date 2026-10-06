# M3 scoped closure record — candidate for review

Status: **reviewed integration record; no phase acceptance.** This
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
| R09 | Merged #131 at `73e1386` | Final-head CI 37209190785; merged local API and browser authority boundaries | Merged by maintainer-directed integration; Checkpoint B still open on R08 live evidence |
| R10 | Merged #132 at `bf7fdf0` | Browser/type/build and full-suite integration checks at the PR | Reviewed workbench slice; full-package acceptance remains separate |
| R11 | Merged #133 at `b3a351c` | Final-head CI recorded in the acceptance matrix | Merged as a partial operations slice; start/reconnect/restore not delivered |
| R12 | Merged #134 at `89b9ab4` | Final-head CI recorded in the acceptance matrix | Merged as a partial ledger/proposal slice; browser evidence-import form not delivered |
| R13 | Merged #135 at `bc0bcbc` | Final-head CI recorded in the acceptance matrix | Merged as a partial computed-fixture slice; no editable report renderer |
| R14 | Merged #136 at `bf8a45a` | Reviewed bounded Python boundary; review repairs in the integration commit | Merged as a partial boundary; typed third-party integration, extensions CLI, and full R14/D remain open |
| R15 | Reviewed and repaired #139; exact integration at the PR | Final repair-head CI 37454556583; 101 local recovery tests passed, two root-only permission skips | Local recovery slice; full phase/live acceptance remains separate |
| R16 | Reviewed and repaired trial-tooling slice, #140; exact integration at the PR | Focused tests, generated contracts and final-head CI linked in the PR | Full R16 not accepted; **no human trial performed**, D open |

Full per-package rows and candidate detail are in the
[acceptance matrix](acceptance-matrix.md). This table is a roll-up, not a
substitute.

## Checkpoint status

| Checkpoint | Packages | State |
| --- | --- | --- |
| A | R02–R06 | Not claimed as blanket accepted; R05/R06 candidate evidence recorded |
| B | R07–R08 | **Open.** New selected-host and GPU evidence is missing; see COMM-0004 |
| C | R09–R13 | **Open.** Reviewed slices are merged; full package acceptance gaps remain |
| D | R14–R16 | **Open.** Extension boundary and install/backup/restore are candidates; independent trials are unperformed |

No checkpoint is claimed complete by this record.

## Remaining backlog

Ordered by what blocks the next gate, not by effort.

| ID | Item | Blocked on | Owner |
| --- | --- | --- | --- |
| BACKLOG-01 | Supply existing private host connection configuration and selected-GPU/Kaggle access | Maintainer / resource owner | Maintainer |
| BACKLOG-02 | Collect the R07/R08 live two-host and GPU evidence, then review Checkpoint B | BACKLOG-01 | Assigned implementer |
| BACKLOG-03 | Review remaining full-package acceptance gaps separately from integration | Recorded acceptance matrix and evidence | Planning/review assistant / maintainer |
| BACKLOG-04 | Close the R10–R14 broken `#r1x-candidate-evidence` matrix anchors | Reviewer decision on whose record to edit | Planning/review assistant |
| BACKLOG-05 | Add a `researchos extensions` CLI or accept the R14 Python-only surface | Reviewer decision | Planning/review assistant |
| BACKLOG-06 | Decide whether a fresh workspace should materialize its EventStore at init | Reviewer decision; current R02 contract is `store-missing` | Planning/review assistant |
| BACKLOG-07 | Run the R16 independent trials (TRIAL-01/02) | Maintainer invitations | Maintainer |
| BACKLOG-08 | Run the authorized remote trial journey (TRIAL-03) | BACKLOG-01 | Maintainer / resource owner |
| BACKLOG-09 | Preserve the unrounded 85% floor on repair heads | Final-head CI | Reviewer |
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
2. Whether the remaining full-package gaps in the integrated R09–R16 slices
   satisfy their original acceptance criteria once the missing evidence exists.
3. Whether R15 may close without replication, encryption, or downgrade support.
4. Whether R14 may close on a Python-only surface with one inline adapter.
5. Whether the draft closure direction above is acceptable as the planning
   assistant's starting point, given that this file was authored by an
   implementer and proposes no acceptance change.

## Triage of what remains

Sorted by whether the blocker is code, a person, or access. No completion of a
"code" row alone can close Checkpoint D. Full R14 acceptance, human trials,
remote evidence and the maintainer decision remain separate requirements.

| Remaining item | Blocked on | Owner | Can it be done locally? |
| --- | --- | --- | --- |
| TRIAL-01: T1–T5 with participant A, each record confirmed by that participant | Maintainer invitation; two people who did not build the system | Maintainer | **No** — needs people |
| TRIAL-02: T1–T5 with participant B, same confirmation rule | Same | Maintainer | **No** — needs people |
| TRIAL-03: at least one authorized remote journey | Two-host connection configuration and selected-GPU access (COMM-0004) | Maintainer / resource owner | **No** — needs access |
| TRIAL-04: fix main-path defects found in TRIAL-01/02 and re-run affected tasks | The findings do not exist yet | Implementer, after the trials | **No** — needs the trials first |
| TRIAL-05: reconcile this record against real trial outcomes | TRIAL-01/02/03 | Planning/review assistant | **No** — needs the trials |
| Checkpoint D review and acceptance decision | All of the above | Maintainer | **No** |
| Release name, version, tag, publication | A maintainer decision, deliberately not pre-taken | Maintainer | **No** — and not pre-empted here either |
| Any new paid activity | A maintainer decision | Maintainer | **No** — none was spent, and none is proposed |
| R15/R16 review and repairs | Maintainer-directed cleanup in #139 then #140; exact final heads and integration at the PRs | Reviewer | Yes |
| Main-path defects on the T1–T5 path | Found by implementer self-run; four fixed, recorded in the R16 evidence | Implementer | Yes — complete |
| Closure record kept honest | Stale pre-merge R09–R14 rows corrected in this pass | Implementer | Yes — complete |

The last three rows are the whole of what was available locally. Everything above
them needs a person, an authorization, or hardware, and none of it can be
manufactured by working harder on the repository.

### Decisions deliberately not taken here

Release naming, versioning, tagging, and publication are **maintainer decisions**
under the plan, and no new paid activity was required or attempted to produce any
of this. Nothing was deployed: there is no hosted instance, no public URL, and no
service behind these packages. The evidence in this repository is the deliverable;
shipping it is not part of it.
