# Use the research workbench

Requirements: [workbench protocol](../protocols/workbench-v0alpha1.md),
[local API](m3-local-api.md). Status: **R10 candidate, not accepted.**

## Open it

```bash
researchos web serve --root ./ws --port 8787
```

The command prints a one-time bootstrap URL. Open it in your own browser. The
secret is in the URL *fragment*, which browsers never send to a server, so it
does not appear in access logs. The page exchanges it for a session, spends it,
and clears the fragment from the address bar.

You need the server to keep running. Stopping it invalidates the session, and
starting it again prints a new secret.

## What you can see

| Tab | Shows |
| --- | --- |
| Project | Project id, event high-water mark, manifest-relative paths |
| Spec revisions | Immutable first-seen spec digests |
| Execution graph | One node per run with lifecycle facts |
| Runs | Fold-derived state, provenance badge, expandable run facts |
| Events and logs | Verified facts, paged by cursor |
| Artifacts | Content-addressed objects this project references |
| Environment | The limits the server actually enforces |
| How to read this | The state and provenance legend |

## Read the badges honestly

The two badges on a run are independent, and the second one matters as much as
the first.

- **State** comes from the authoritative Run fold. `Succeeded` is the only state
  styled as success, and it means a successful terminal outcome was observed.
- **Synthetic (not a measurement)** means the run cited an authorization recorded
  as audit-only or not-executed. The lifecycle completed, but nothing was
  trained or measured. Never quote a synthetic run as a result.

A run with no lifecycle facts reads **No lifecycle facts**. That is not the same
as failed: it means this page has no facts for it.

## States you will not confuse

| Badge | Means |
| --- | --- |
| Cancellation requested | A cancellation was recorded. It is **not** an observed stop. |
| Stopped (observed) | The process was observed to stop. It did not report success. |
| Unknown / Lost | The outcome was never observed. Compare it to nothing. |

## Paging

Every list pages with a server-issued cursor. **Older events** and **Older runs**
advance it. The run index is newest-first, so its cursor means "older than
this"; event and revision cursors mean "after this sequence". Reloading resumes
from the same cursor, so nothing is skipped silently.

Long lists are capped and the page says how many rows it withheld rather than
truncating quietly.

## Artifacts

Paste a `sha256:…` or `jcs-sha256:…` digest. An artifact is visible only when a
verified event of this project references it; another project's digest returns
"not found". Objects under 256 KiB are shown inline, larger ones are not.

## Rebuilding the frontend

The shipped bundle is committed, so you never need this to use the workbench.
Only after changing `web/`:

```bash
cd web
npm ci
npm run typecheck
npm run build          # writes ../src/llm_research_os/web/static
cd ..
uv run python scripts/generate_web_types.py   # after changing a contract
```

`scripts/generate_web_types.py` must be rerun after any change to
`llm_research_os/web/contracts.py`; `tests/test_web_assets.py` fails if you
forget.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| "Session required" | The secret was already spent, or the server restarted. Open the new bootstrap URL. |
| "Local API unreachable" | `researchos web serve` is not running. |
| An events tab is empty | The cursor is past the last fact, or the project id does not match the store. Project scoping is deliberate. |
| "No such workbench resource" | The bundle is missing from the installation. Rebuild it in `web/`. |
| Digests return "not found" | That object is not referenced by this project, or it is not in the CAS. |

## What this cannot do

It cannot start, cancel, approve, restore or record anything. Browser-driven
execution control is R11 and reuses the same shared services. A browser session
is not a Worker credential.
