# Install, start, back up, and recover

Current state: **candidate on the R15 branch; not merged, not accepted.** The
commands described here are implemented with tests; Checkpoint D is not
accepted and the independent trials in R16 have not been performed.

The offline wire format is in
[backup and restore v0alpha1](../protocols/backup-restore-v0alpha1.md).

## Install

The wheel carries the built workbench bundle, so an operator needs neither a
source checkout nor Node.

```bash
uv venv .venv
uv pip install --python .venv/bin/python llm-research-os
.venv/bin/researchos --help
```

Python 3.12 or newer is required. Training extras are optional and are not
needed for anything in this guide; the core runs without a model key and
without a GPU.

## Run the offline demonstration

```bash
researchos workspace demo --root ./workspace
```

One command creates a workspace, records a complete offline research chain from
the corpus packaged **inside the wheel**, and diagnoses the result. It needs no
source checkout, no model key, no GPU, and no Node, and it prints the backup and
serve commands to run next. The demonstration copies the packaged corpus to a
temporary directory first, so running it cannot mutate the installed artifact.

A simulated `run.completed` here is a controlled lifecycle finish. It is not a
training result and not a scientific conclusion.

## Initialize a workspace

```bash
researchos app init \
  --root ./workspace \
  --project my-project \
  --control-db control/events.sqlite \
  --cas-root cas \
  --worker-root worker
```

This writes `workspace.json` and creates the three roots. `control`, `cas`, and
`worker` must not overlap: an overlapping Worker root would put Worker material
next to the control database, and both `app init` and `workspace doctor` refuse
it.

The control store is not created by `init`. That is the accepted R02 contract —
a fresh workspace has no EventStore until the first append, and
`ApplicationService.open` reports `store-missing` until then. The first command
that appends a fact creates it.

## Diagnose before you start

```bash
researchos workspace doctor --root ./workspace --deep
```

The report is designed to be shared. Every value is a count, a boolean, or an
identifier you supplied; nothing is a host path, a document body, or a
credential. `--deep` re-verifies every referenced object's bytes instead of
checking only that it is present.

| Check | Reports |
| --- | --- |
| `workspace.manifest` | The workspace could be opened |
| `workspace.roots` | Control/CAS/Worker isolation and Worker root presence |
| `control.store` | The control store opens, and the verified high-water |
| `control.migration` | The on-disk schema header against the supported version |
| `objects.referenced` | Referenced-object count, missing count, corrupt count |
| `web.assets` | The packaged workbench bundle is present |
| `platform.runtime` | Supported Python and sufficient free space |

Exit status is `0` when healthy, `1` when a check failed, `2` when the workspace
itself could not be read. A missing workspace is a *report*, not a crash.

### Migration and downgrade limits

```bash
researchos workspace migrate --root ./workspace
```

Reports the on-disk header, the supported versions, and whether an upgrade is
available. **Downgrade is not supported and is not emulated.** A store written
by a newer build may contain facts this build cannot represent, and rewriting
historical rows to make it openable would break digest history. A store whose
header is newer than this build reports `control.migration: failed`; point the
older build at a newer workspace, or restore an image taken at the newer
version.

## Start the local workbench

```bash
researchos web serve --root ./workspace --port 8787
```

Loopback only. The bootstrap secret is printed once and is spent on first use.
If the port is taken, the server exits `2` with
`{"code":"listener-unavailable", ...}` instead of raising a traceback. This is
merged R14 behaviour and is unchanged here. `workspace doctor` and `researchos.web.serve.port_is_free` can check
first.

A missing asset bundle is a startup failure, not an empty project; the
`web.assets` check catches it before you open a browser.

## Back up

```bash
researchos backup create --root ./workspace --out ./backup-2026-10-05
researchos backup verify --image ./backup-2026-10-05
```

A backup is a **verified high-water prefix** of the EventStore plus the
immutable CAS objects that prefix references. The SQLite copy is taken with the
online backup API and collapsed to a single standalone file, so the image is one
file plus the manifest plus its objects. Referenced objects are copied by digest
and re-hashed. A referenced object missing from the workspace aborts the backup.

The image is assembled in a sibling `.partial` directory and renamed into place,
so an interrupted backup leaves no directory that verifies as far as it got.

Back up *before* large migrations and before any host maintenance. Backups are
not replicated, encrypted, or garbage-collected by this tool; copying an image
off the machine is an operator action.

## Restore

```bash
researchos backup restore --image ./backup-2026-10-05 --root ./restored
```

The image is verified completely before anything is written. Then the store and
its referenced objects are materialized, the restored store is compared to the
image by recomputed event digests and a recomputed research-ledger digest, and
the result is reported as a `RestoreReport`.

The restore destination must be empty or absent. `--project` renames the
restored workspace, and it is **refused** when the image contains no event for
that project: a rename that leaves the manifest disagreeing with every event in
the store would back up and restore inconsistently.

Restoring is verified twice, in the sense that matters: `backup verify` re-derives
the image (including the object set, which is re-read from the events rather than
from the manifest) before anything is written, and the materialization then
compares the restored store to the image by recomputed event and research-ledger
digests. A workspace is assembled in a sibling `.partial` directory and renamed
into place, so a failed restore is retryable instead of leaving a half-workspace
that the next attempt refuses as already existing.

### What a restore does not do

A restore copies facts. It **does not relaunch historical tasks.** It appends no
events, starts no Worker, dispatches no Run, and resumes no Attempt. A Run that
was not terminal when the image was taken cannot be observed from the new
machine, so it is reported as `unknown`:

```json
{
  "relaunchPolicy": "not-relaunched",
  "appendedEvents": 0,
  "reconciledRuns": [
    {"runId": "run.example.1", "lastState": "running", "observation": "unknown",
     "nextAction": "reconcile-manually"}
  ]
}
```

This is the ADR-0054 tri-state rule: a probe that cannot reach the process
yields `unknown`, and `unknown` is never collapsed into success, failure, or
stop. Reconcile those Runs explicitly against the live system before trusting
the restored workspace.

## Credential treatment

- Model provider keys, Worker HMAC secrets, and SSH private keys are **never**
  written to a backup image, an event, a manifest, or a diagnostic report.
- The backup image contains the control store, the manifest, and referenced
  content objects. Treat the control store as sensitive: it holds the research
  history, including imported evidence text.
- A diagnostic report is safe to paste into an issue. An event dump is not.
- The browser bootstrap secret is printed once by `web serve` and is not
  persisted by this tool.

## Worker identity after a restore

Worker identity is **not** part of a backup image. A Worker registers against a
controller at runtime; a restored controller has no live Worker registrations,
and a restored Worker root is created empty. Re-onboard the Worker on the new
host through the existing R07 SSH onboarding flow rather than copying
registration material between machines. The R07 boundary still holds: no control
SQLite, no CAS, and no private TLS key belongs in a Worker root.

## Offline demonstration

The installed wheel carries a complete no-key, no-GPU journey. CI runs it
outside the source checkout in
[`scripts/wheel_smoke.py`](../../scripts/wheel_smoke.py), and
`tests/test_recovery_contracts.py`, `tests/test_recovery_backup.py` and
`tests/test_recovery_doctor.py` cover the same paths in-process. The journey is:
create a workspace from the packaged corpus, diagnose, back up, verify, restore,
and confirm the restored event digests and research ledger match.

## Known limitations

- No replication, encryption, scheduling, or retention policy for images.
- No artifact garbage collection. Restoring an image restores only the objects
  that prefix referenced.
- Downgrade is refused rather than supported.
- The control store is absent until the first append, so
  `workspace migrate` on a brand-new workspace reports `control-store-missing`.
- `wsgiref` is a development server and is not hardened against a hostile
  network peer. The surface is loopback-only.
