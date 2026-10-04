# Research workbench (R10)

Status: **Implemented on branch `r10-workbench`; candidate evidence only. Not merged,
not accepted.** Checkpoint C is not accepted.
Requirements: [M3 plan R10](../plans/m3-development-plan.md#r10-read-only-research-workbench).
Authority boundary: [local API protocol](local-api-v0alpha1.md).

## What this is

A read-only browser surface over one project's verified EventStore folds and the
CAS. It presents real project, experiment, execution and evidence data. It
cannot launch, cancel, approve or record anything, and it holds no authority the
CLI does not already have.

## Transport decision

R10 locks the concrete dependencies the plan deferred: **React 19 + TypeScript +
Vite**, no component library and no client-side state library. The bundle is
committed to `src/llm_research_os/web/static/` and shipped in the wheel, so an
operator needs neither a source checkout nor Node.

| Concern | Choice | Reason |
| --- | --- | --- |
| Framework | React 19 | The plan named React/TypeScript/Vite |
| Language | TypeScript 5.9, `strict` plus `exactOptionalPropertyTypes` and `noUncheckedIndexedAccess` | A read surface that silently treats a missing field as present is exactly the failure this project must not have |
| Build | Vite 7 | Plan direction; one hashed bundle keeps the wheel small |
| Graph | Plain ordered list | The plan named read-only React Flow. A layout library is added only when a real DAG needs a layout; rendering a guessed graph shape would be worse than an honest list |
| Routing | Internal view state | One read-only surface; a router would add a dependency without a second route to serve |
| Tests | Python contract/asset gates plus a real-browser run | See *Verification* |

### Proposed normative change for review

The plan's R10 architecture paragraph named "read-only React Flow". This
implementation renders the execution graph as a read-only ordered list of run
nodes rather than a force-directed canvas. Node placement is presentation only
and is not part of any digest, so the acceptance requirement is unaffected;
a layout library is deferred until a real multi-node DAG needs one. **Review
decision:** accept the list, or require the graph library now.

## Types are generated, not hand-written

`src/llm_research_os/web/contracts.py` owns the wire contract as frozen,
alias-keyed Pydantic models. `scripts/generate_web_types.py` renders
`web/src/generated/local-api.ts` from them, and `tests/test_web_assets.py` fails
when the committed file drifts. A view that changes shape breaks `tsc --noEmit`
and the drift test instead of silently disagreeing with the server.

Regenerate with:

```bash
uv run python scripts/generate_web_types.py
```

## Views

| View | Source | Notes |
| --- | --- | --- |
| Project | `/workspace` | Manifest-relative paths only; no absolute host path |
| Spec revisions | `/revisions` | Immutable first-seen spec digests |
| Execution graph | `/runs` | One node per run, read-only, layout not a digest input |
| Runs | `/runs` | Fold-derived state plus a provenance badge |
| Events and logs | `/events` | Cursor paging against a frozen high-water mark |
| Artifacts | `/artifacts/{digest}` | Project-scoped; inlined only below 256 KiB |
| Environment | `/capabilities` | The limits the server actually enforces |
| How to read this | static | The state and provenance legend |

## Outcome honesty

This is the substance of R10, so it is enforced rather than described.

**Observation state is folded, not guessed.** `ReadProjections._observation`
runs the authoritative `RunControl` fold and maps `RunStatus` to a closed set.
`cancelled` maps to `observed-stop`, not to success. A run the fold refuses is
reported `absent`; inventing a status from raw event type names would be a lie.

**Provenance comes from a recorded fact.** A run's `origin` is read from the
authorization event its `run.queued` fact cites: `authority: audit-only` or
`execution: not-executed` means **synthetic**. Anything the workbench cannot
source is `absent`, never `real`. Claiming a measurement it cannot source is the
misleading direction, so that case is never taken.

**Only success is styled as success.** `isSuccessful()` is true for exactly one
state. `isReportableOutcome()` gates anything that compares results, so
`unknown` and `lost` cannot enter a comparison as if they were results.

Synthetic, absent and real therefore stay distinguishable in the UI, and
`unknown`, `lost`, `failed`, `cancel-requested` and `observed-stop` each get
their own label, tone and explanation rather than a boolean.

## Empty, error and offline states

Every view distinguishes four cases rather than showing a blank region: loading
(`role="status"`, polite live region), empty (explains what would appear and
what has not happened yet), refused (shows the server's closed error code), and
offline (says the local server is unreachable and offers retry). The bootstrap
path has its own state explaining that a session cannot be created any other way
and that a browser session is never a Worker credential.

## Bounded rendering

Lists cap at 100 rows (200 for event and run facts) and state how many rows were
withheld, because silently truncating would misreport the contents. Pages cap at
50. Graph nodes cap at 100. The API caps a page at 500 and a stream at 200.

## Keyboard and assistive access

Every control is a real `<button>`, `<input>` or `<a>`, so tab order and
activation work without custom key handling. Views are `<section>` elements with
`aria-labelledby`; errors use `role="alert"`, loading uses `aria-live="polite"`,
the nav has `aria-label`, the active tab carries `aria-current="page"`, the run
disclosure carries `aria-expanded`, and `:focus-visible` is never removed. The
page sets `referrer: no-referrer` and `robots: noindex, nofollow`.

## Static asset serving

`llm_research_os.web.assets` resolves each request by directory descriptor with
`O_NOFOLLOW`, so no path component can be a symlink and `..` cannot escape. A
symlink raises `ELOOP` and is mapped to a closed error rather than escaping as an
`OSError`. Content types come from a closed suffix table and responses carry
`X-Content-Type-Options: nosniff`.

The bundle loads **without a session**, because the operator must be able to load
the page in order to obtain one. Every `/api/v0alpha1` route remains behind the
session check, and `tests/test_web_assets.py` asserts that adding the bundle did
not open the API surface.

Hashed assets are `immutable`; `index.html` is `no-store` so a rebuilt bundle is
never hidden behind a cache. A matching `If-None-Match` returns `304`.

## Verification

- `npm run typecheck` — clean under `strict` + `exactOptionalPropertyTypes` +
  `noUncheckedIndexedAccess`.
- `npm run build` — one hashed JS bundle, one CSS bundle, `index.html`.
- `tests/test_web_assets.py` — contract drift, closed observation set, asset
  resolution, traversal, symlink refusal, directory refusal, content types,
  `304`, index immutability, bundle-without-session, API-still-gated, and a
  client/server path agreement check that reads the built bundle and asserts it
  calls only routed endpoints.
- **Real browser run** (Chrome, macOS): bootstrap exchange, all eight views
  navigated, 14 real events rendered from `example-minimal`, run index showing
  `Succeeded` + `Synthetic (not a measurement)`, empty state shown for a
  deliberately out-of-scope project, and zero console errors or warnings.

The contract/asset gates do not replace a browser. The browser run above is
recorded as manual evidence; it is not automated in CI, and no CI job drives a
browser. That is an explicit gap, not a claim of E2E coverage.

## Build inputs not in CI

`web/node_modules` is excluded from both build targets, so the toolchain never
enters the sdist or the wheel. CI installs Python only and does not run `npm`;
the committed bundle is what ships. Regenerating it needs Node 22 and
`npm ci && npm run build` in `web/`. A stale bundle is therefore possible and is
not detected by CI — only the Python-owned contract types are drift-checked.

## Out of scope for R10

Editable DAGs, browser-created authority, approval, cancellation, restore,
proposals and evaluation are R11–R13. This surface reads; it does not act.
