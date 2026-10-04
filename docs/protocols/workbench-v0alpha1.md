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
| Graph | Validated immutable spec/plan nodes plus dependency table | Layout changes no semantic identity; nested or over-limit graphs remain explicitly unsupported |
| Routing | Internal view state | One read-only surface; a router would add a dependency without a second route to serve |
| Tests | Python contract/asset gates plus a real-browser run | See *Verification* |

### Review disposition

The planning/review assistant accepts the locked React/TypeScript/Vite choice.
The initial ordered Run list did not fulfill workflow topology. Review repairs
replace it with backend-validated stored ResearchSpec / ExecutionPlan inspection,
including nodes and edges. A graph layout dependency is not required for this
bounded read-only representation. Decision/dissent/authorization history belongs
in R10's read scope; only mutation remains in later packages.

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
| Execution graph | `/inspect/artifacts/{digest}` | Validated stored spec/plan nodes and dependency edges |
| Runs | `/runs` | Fold-derived state plus a provenance badge |
| Events and logs | `/events` and `/inspect/events/{id-or-sequence}` | Run-scoped paging and immutable payload / evidence inspection |
| Decisions and authority | Type-filtered `/events` | Recorded decision, dissent, proposal and authorization history |
| Logs / Metrics | Recorded event and artifact references | Inspect actual stored contents; measurements require recorded provenance |
| Artifacts | `/artifacts/{digest}` | Project-scoped; inlined only below 256 KiB |
| Environment | Worker / Attempt facts and linked inventory objects, plus `/capabilities` | Execution facts remain separate from API limits |
| How to read this | static | The state and provenance legend |

## Outcome honesty

This is the substance of R10, so it is enforced rather than described.

**Observation state is folded, not guessed.** `ReadProjections._observation`
applies the authoritative `RunStateProjection` reducer to verified Run-scoped facts and maps `RunStatus` to a closed set.
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

## Automated verification added during review

The `Workbench contract and bundle` CI job installs locked Node/Python test
inputs, checks TypeScript, rebuilds and diffs the committed assets, and drives
Chromium against the actual local API, SQLite and CAS. The browser fixture is
explicitly synthetic and launches no training. It covers bootstrap fragment
removal, a Run after 251 foreign events, cancellation-request presentation,
workflow dependencies, nested result/config lineage, all eleven tabs, keyboard
activation, offline state, refresh and restart against the same persisted store.
Local browser download is blocked in the managed review environment, so final
CI evidence must establish this gate; no local browser pass is claimed.

The published `local-api-response` schema is registered in `researchos schema
--check-all`. Tests validate actual wire responses (including nested session
capabilities) and fail on generated TypeScript drift. Node/Playwright are test
inputs only; the installed wheel needs neither.

## Out of scope for R10

Editable DAGs, browser-created authority, approval, cancellation, restore,
proposals and evaluation are R11–R13. This surface reads; it does not act.
