# R16 independent trials: kit, record, and current state

Status: **prepared, not performed.** The trial kit below is complete and
committed. No trial has been run, no independent user has installed anything,
and no result is recorded here as observed.

This file is the R16 evidence surface. It exists so that a trial result has a
fixed place to land, and so that the absence of results is visible rather than
implied by silence. A row in [Pending trial work](#pending-trial-work) is not
evidence. See the [M3 plan](../../plans/m3-development-plan.md) R16 definition
and Checkpoint D.

## Why this is a separate record

R16 is the only package whose deliverable is *human* work by people who did not
implement the system. Its acceptance criteria cannot be met by code, a test, a
Mock, or a prose claim — the plan says so explicitly: "Unperformed live work
remains pending-live and prevents claiming the corresponding checkpoint
complete." Recording the kit and the empty result is the honest maximum this
package can contribute on its own.

## What is committed and ready to run

| Item | Where | State |
| --- | --- | --- |
| Fixed trial tasks T1–T5 | [Fixed trial tasks](#fixed-trial-tasks) below | Ready |
| Journey record contract | [`trial-record/v0alpha1.schema.json`](../../schemas/trial-record/v0alpha1.schema.json) | Ready |
| Kit aggregate contract | [`trial-kit/v0alpha1.schema.json`](../../schemas/trial-kit/v0alpha1.schema.json) | Ready |
| `researchos trial scaffold` / `validate` / `aggregate` | `src/llm_research_os/cli/trial_commands.py` | Ready |
| Journey record template | [Trial record template](#trial-record-template) below | Ready |
| Install and recovery guide the trials use | [`guides/r15-installation-and-recovery.md`](../../guides/r15-installation-and-recovery.md) | Candidate, R15 branch |
| Offline clean-install journey | [`scripts/wheel_smoke.py`](../../../scripts/wheel_smoke.py) | Candidate, R15 branch, CI-run; takes no arguments, so it cannot borrow checkout fixtures |
| One-command demonstration | `researchos workspace demo` | Candidate, R15 branch; referenced by T1 |
| One-command demonstration | `researchos workspace demo` | Candidate, R15 branch; referenced by T1 |

The maintainer handles invitations and authorization. This package does not
contact anyone and does not authorize access.

## Fixed trial tasks

Each task is a fixed, checkable instruction set. A trial participant should not
be given a choice of what to try; the point is to observe the same journey on
machines the implementers did not build.

Every task is offline, needs no model key, and needs no GPU.

### T1 — Install without a checkout

> Install `llm-research-os` from the wheel into a fresh virtual environment on
> your machine. Do not clone the source repository. Confirm `researchos
> --help` runs, then run `researchos workspace demo --root ./workspace`.

Observe: whether the install needed anything the task did not mention
(compiler, Node, network access to a private index, a second interpreter).
Record the exact commands that worked.

### T2 — Initialize and diagnose

> Create a workspace with `researchos app init`, then run
> `researchos workspace doctor --deep` and read the output.

Observe: whether the output is understandable without the implementer present.
Record every check the participant could not interpret, and every question they
had to ask.

### T3 — Work offline, then back up

> Import the example evidence, run the example checkpoint, then create and verify
> a backup with `researchos backup create` and `researchos backup verify`.

Observe: whether the participant understood what a backup contains and what it
does not contain. Record any assumption they made that turned out to be wrong.

### T4 — Restore and reconcile

> Restore the backup into a new directory with `researchos backup restore`. Read
> the restore report.

Observe: whether the participant noticed `relaunchPolicy` and the
`reconciledRuns` list. Record whether they expected the restore to restart
anything. This is the single most important confusion to catch: an operator who
believes a restore resumes work will trust a stale workspace.

### T5 — Read a shared diagnostic

> Run `researchos workspace doctor`, then paste the whole output into an issue
> or a message.

Observe: whether the participant found anything they would not want to share.
This validates the redaction claim with a human rather than only with a test.

### Remote journey — pending-live

The plan requires at least one authorized remote journey. That journey depends
on the two-host and selected-GPU access described in COMM-0004, which is still
missing. It cannot be prepared into a result here. It remains
[pending](#pending-trial-work) and Checkpoint D is not closable without it.

## Running the kit

```bash
researchos trial scaffold --root ./trial-kit --participant participant-a   # exits 1: nothing measured yet
researchos trial validate ./trial-kit/T1/trial-record.json                # refuses an unfilled slot
researchos trial aggregate --root ./trial-kit                              # reports checkpointD: false
```

An empty kit reports `records: 0`, `participants: []`, and all three blockers
unresolved. A kit with only unconfirmed records reports `records: n` with
`observedParticipants` populated, `participants: []`, and every id in
`pendingConfirmation` — so a half-finished programme cannot read as a finished
one.

`scaffold` writes deliberately invalid record slots so that an unrun trial reads
as unrun. A record becomes valid only when a participant's outcome is actually
recorded, and it stays invalid if no evidence is attached or if the implementer
wrote the measurement.

## Trial record template

One record per participant per task. Copy this block; do not summarize away a
failure.

```text
Trial ID:            T<n> / <participant alias> / <ISO date>
Build under test:    <exact wheel filename and version>
Platform:            <OS and version, CPU model, free disk>
Python:              <exact version>
Model key:           none / present-but-unused
GPU:                 none / present-but-unused
Node:                absent / present
Source checkout:     absent

Task text given:     <verbatim>

Completed:            yes / no / partial
Exit state:          <what the participant saw at the end>
Interventions:       <every hint, command repeat, or doc lookup the
                      implementer or documentation supplied>
Elapsed:             <wall clock from first command to exit state>
Confusion observed:  <what the participant expected that was not true>
Recovery observed:   <how they got unstuck, if they did>
Defects found:       <severity, reproduction, and whether it blocked T<n>>
Evidence attached:   <report paths, never a credential or host path>
Verdict:             core journey completed / blocked / abandoned
```

The implementer may not fill in "confusion observed" or "interventions" on the
participant's behalf. Those two fields are the measurement; a record where they
are empty did not observe a trial.

That rule is now enforced by the contract rather than by convention. A
`TrialRecord` with `recordedBy: implementer` is **refused** if either field is
non-empty, `evidenceAttached` must be non-empty so a record can be reviewed
later, and `task` is restricted to the agreed list so a report from outside this
kit cannot be aggregated with the rest of R16's evidence.
`researchos trial validate` is what a third party runs before believing a
record.

### Pending the participant's own confirmation

A record is **not evidence of a trial until the participant themself confirms
it.** An observer may write down faithfully what a person did, but that is
evidence that someone watched, not that the person took part — and the
difference is the whole measurement R16 exists to make.

- `participantConfirmed` defaults to `false`; `confirmedAt` is required when it
  is set and refused when it is not.
- An implementer may not set it. Only the participant, or an observer holding the
  participant's confirmation, may.
- `aggregate` counts **confirmed** records only. It reports `participants`
  (confirmed), `observedParticipants` (anyone with a record), and
  `pendingConfirmation` (record ids awaiting the person), so a kit full of
  unconfirmed records shows both numbers instead of reading as complete.
- A confirmed `REMOTE` record is the only thing that satisfies the
  authorized-remote requirement, because that requirement is about access a
  person was actually given.

## Aggregate requirements before Checkpoint D

| Requirement | Source | State |
| --- | --- | --- |
| Two participants who did not implement the system | Plan R16 | **Not performed** |
| Install and offline journey results | Plan R16 | **Not performed** |
| Interventions, confusion, and recovery recorded per task | Plan R16 | **Not performed** |
| At least one authorized remote journey | Plan R16 | **Not performed** — blocked on COMM-0004 |
| Main-path defects fixed and affected paths re-run | Plan R16 | Not applicable until a defect is found |
| Scoped closure record and remaining backlog | Plan R16 | [Draft closure record](m3-closure-record.md) — candidate, for review |

## Pending trial work

| ID | Work | Blocked on | Owner |
| --- | --- | --- | --- |
| TRIAL-01 | Invite and run T1–T5 with participant A | Maintainer invitation and authorization | Maintainer |
| TRIAL-02 | Invite and run T1–T5 with participant B | Maintainer invitation and authorization | Maintainer |
| TRIAL-03 | Authorized remote journey | Two-host connection configuration and selected-GPU access (COMM-0004) | Maintainer / resource owner |
| TRIAL-04 | Fix main-path defects found in TRIAL-01/02 and re-run affected tasks | TRIAL-01/02 findings | Assigned implementer, after findings exist |
| TRIAL-05 | Reconcile the draft closure record against trial outcomes | TRIAL-01/02/03 | Planning/review assistant |

TRIAL-01 and TRIAL-02 require people who did not build the system. Nothing in
this repository can substitute for that, and a rehearsal performed by an
implementer is not a trial.

## What this package does not claim

- That the product is usable by an independent user. That is TRIAL-01/02.
- That Checkpoint D is complete. It is not: two of its four requirements are
  unperformed, and one of those is blocked on missing access.
- That a release version, tag, or publication is ready. That is a separate
  maintainer decision and this package does not prepare one.
- That the R15 install, backup, and restore paths work on macOS or on a machine
  other than the development container. Local results are recorded at their
  platform and SHA; cross-platform CI results are not yet cited for the R15
  branch.
