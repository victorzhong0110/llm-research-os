# Research workflow (R12)

Status: **Implemented on branch `r12-research-workflow`; candidate evidence only.
Not merged, not accepted.** Checkpoint C is not accepted.
Requirements: [M3 plan R12](../plans/m3-development-plan.md#r12-ai-proposals-citations-and-researcher-decisions).
Boundaries: [local API](local-api-v0alpha1.md), [browser operations](browser-operations-v0alpha1.md).

## What this is

The research loop in the browser: read the ledger, submit a proposal bound to a
base revision, and record a decision — through the same shared services the CLI
uses, so the browser, the CLI and event replay cannot disagree.

## A citation is not a reference

A proposal may cite only evidence **this project has actually recorded**. A
citation is resolved against the `EvidenceControl` fold; an id the project has
never imported is not a citation, and the proposal is refused.

This is checked on both the read-only `proposal.validate` and the mutating
`proposal.submit` path, so a draft can be inspected and then submitted without
the answer changing underneath it.

## Generated text is a draft first

`proposal.validate` reads a proposal document and reports its bindings without
appending anything:

| Reported | Meaning |
| --- | --- |
| `experimentRevision` | The base revision the proposal was written against |
| `proposedSpecDigest` | The candidate spec artifact |
| `specDiffDigest` | The server-derived diff |
| `predictions`, `falsificationConditions` | What it claims and what would refute it |
| `riskAssessment` | Its own risk statement |
| `citations` / `unresolvedCitations` | Which references resolve |
| `runQueued` | Always `false` |
| `grantedPermissions` | Always `[]` |

A validated proposal is a draft. It queues no Run and grants no permission; a
human decision is still required before anything executes.

## Hostile evidence is text, not an instruction

Imported evidence is data. A rationale that reads like a tool request is stored
verbatim as rationale and grants nothing: `grantedPermissions` stays empty,
`runQueued` stays false, and no permission changes. A test submits exactly that
text and asserts all three.

## Stale proposals cannot overwrite a revision

`expectedRevision` is bound to the command. A proposal naming a revision the
caller did not read is refused, so a proposal written against an old revision
cannot land on top of a newer one.

## Preserved disagreement

The ledger keeps dissent. A decision that **overrides** a dissent records which
dissent it overrode, and the dissent stays in the ledger. Overriding is a fact,
not a deletion: the browser shows the decision next to the dissent it
overrode, and a refresh preserves both along with the rationale.

## Closed proposals cannot be re-decided

The ledger enforces this, and the tests rely on it rather than working around
it: rejecting a proposal that was already accepted is refused with
`proposal-not-open`. A rejection test therefore records a fresh proposal first
and then rejects that one.

## What the browser shows

`GET /api/v0alpha1/research` is read-only and bounded: at most 50 entries per
kind, with the withheld count reported rather than silently truncated. Rendering
it appends nothing.

## Not delivered

- **Evidence import from the browser.** The R12 deliverable about reading rights
  versus training rights is already enforced by the M1 evidence model and its
  policy flag; exposing the import *form* is not done, so a browser cannot yet
  import a document. Recorded as a gap.
- **Local compatible-server integration tests over the real HTTP contract.** The
  M1 adapter tests already exercise the HTTP contract against a local server
  without a paid model, but this package adds no new such test. Recorded as a
  gap rather than claimed.
- **Budget reservation release on uncertain dispatch.** The existing M1 budget
  facts cover reservation; the browser surfaces neither reservations nor their
  release. Recorded as a gap.
