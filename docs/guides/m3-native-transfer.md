# M3 scoped native transfer (R08 candidate)

`researchos native transfer` copies files named by a grant-scoped manifest.
The manifest is the allow-list: path, digest, and size. The command never
lists a CAS and never follows a symlink. A completed journal for the same
lease is a replay of that transfer, not a second task start.

This does not accept a two-host run. No second machine is contacted.
`gpu-oci` and `macos-mps` remain `pending-live`. A local copy is not remote
evidence.

## Manifest

```json
{
  "grantId": "grant.1",
  "taskId": "task.1",
  "runId": "run.1",
  "attemptId": "attempt.1",
  "direction": "input",
  "files": [
    {"path": "inputs/corpus", "digest": "sha256:HEX", "sizeBytes": 4}
  ]
}
```

`direction` is `input` for `stage` and `output` for `export`. At most 32
files and 256 MiB are accepted. Paths stay inside the destination; `..`,
absolute paths, and symlinks are refused.

## Stage and export

```bash
researchos native transfer stage manifest.json cas/ stage/ \
  --journal journal.json --lease-id lease.1 --format json
researchos native transfer export manifest.json output/ cas/ \
  --journal journal.json --lease-id lease.1 --format json
```

Exit `0` means the named files were copied. The receipt `observation` stays
`unknown` until a separate process observation is recorded. Exit `1` means
the journal is still incomplete. Exit `2` is a local refusal: bad path,
digest mismatch, exhausted retries, or an unsupported checkpoint restore.

An interrupted copy resumes the remaining files under the same lease. Three
attempts is the bound. A changed file after a recorded digest is rejected.
`researchos native transfer classify disconnected-cancel` prints
`cancel-requested` and does not start work. The other classified faults
print `unknown`. None of them is success, failure, or stopped.

Checkpoint bytes are delivered only after the existing restore claim matches
the completed source Attempt and the new Attempt. Anything else is
`transfer-restore-unsupported`.
