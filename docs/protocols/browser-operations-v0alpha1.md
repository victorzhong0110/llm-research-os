# Browser operations (R11)

Status: **Implemented on branch `r11-browser-operations`; candidate evidence only.
Not merged, not accepted.** Checkpoint C is not accepted.
Requirements: [M3 plan R11](../plans/m3-development-plan.md#r11-browser-approval-execution-cancellation-and-restore).
Boundaries: [local API](local-api-v0alpha1.md), [workbench](workbench-v0alpha1.md).

## What this is

The first mutating browser surface. It dispatches **caller-owned application
commands** through the same shared services the CLI uses, so an event replay, a
CLI run and the browser all see the same facts. It does not create authority, and
it does not reimplement execution.

## The one rule

**An accepted request is not an observed outcome.** A cancellation receipt says a
request was committed. It never says a process stopped, and the run index keeps
showing whatever the run's facts actually support until an observed stop arrives.

This is enforced in three places so it cannot rot: the receipt carries
`observedStop: false`, the client renders "Request recorded — no observed stop",
and a regression test asserts the receipt body.

## Operations

| Operation | Effect | Authority |
| --- | --- | --- |
| `plan.preflight` | Reads the spec and reports plan identity, target, policy, declared resources, enforced limits | None. Reads only; always `launchAllowed: false` |
| `run.cancel` | Appends exactly one cancellation-request fact through `RunControl` CAS | Existing Run, not new authority |
| `authorization.revoke` | Appends one `grant.revoked` fact | Revokes; never grants or launches |

### Preflight is not a launch credential

The preflight reports the limits **this build** enforces, the resources the spec
declares, and the policy flags. It says explicitly that resource and budget
requirements are declared, not enforced, and that it makes no reservation. A
preflight is not a preflight report in the R03 sense and carries no signature.

### Revocation is a control-plane fact

`authorization.revoke` uses `WorkerControl`, not `WorkerPlane`. `WorkerPlane`
requires an HMAC key, and a browser must never hold a Worker credential — so
revoking authority as a "Worker action" would have put a Worker credential in
the browser's path. Revocation records that an authority is no longer valid; it
does not complete, stop or launch work. An unknown grant is refused.

## Idempotency: durable identities, not debounce

The browser never debounces a click. It mints a **command identity once per
operator intent** and reuses it on retry, so the shared service's receipt log
decides what happens:

| Situation | Result |
| --- | --- |
| Same command id, same content | Prior receipt replayed; no second fact |
| Same command id, different content | `409 command-refused`; nothing appended |
| A second window sending the same command | Replays the same receipt |
| HTTP 5xx or transport loss | Identity retained; retry replays if it committed, appends nothing otherwise |
| Any refusal | Nothing appended |

`expectedHead` is supplied for head-bound operations, so a stale tab is refused
visibly rather than racing. `expectedRevision` is supplied for preflight, so a
changed plan cannot be inspected against the wrong revision.

## Honest uncertainty

A 5xx or transport failure is **not** reported as success or as failure. The
client shows "Outcome not confirmed", displays the retained command identity, and
tells the operator that resending it is safe. Resending either replays the prior
receipt or appends one fact — never two.

## Authority boundary, unchanged from R09

Commands require the session cookie, an `Origin` equal to the server's own, and
a matching double-submit CSRF token. The CSRF value is learned from the session
body because the cookie is `HttpOnly`; it is re-read on every load, since a
reload keeps the cookie but loses same-origin script state. Without it, writes are
refused — which is the intended failure, and was a real bug found by running the
browser rather than by any test.

## Not delivered

- **Start, reconnect/observe, and restore** are not exposed. They need the R08
  reviewed native launch path and its live two-host evidence, and the R11
  acceptance for restore prerequisites cannot be met without a real Attempt to
  restore. They are recorded as gaps, not stubs.
- **Double-submit click** is not simulated in a real browser. The receipt
  semantics are proven by pytest for both same-content replay and
  different-content conflict; the browser's own double-submit path is not
  automated, and CI drives no browser.
- Approval of a proposal is R12; this surface dispatches a decision document a
  human has already authored, it does not offer an approve button.

## Integration review correction (2026-10-05)

This is an R11 preflight/cancellation/revocation slice, not completed R11 acceptance.
Start and restore remain missing product work; the live R08 gap does not itself
prevent implementing local browser operations. No acceptance rule is waived.
CI now includes the inherited real Playwright browser job. The repaired browser
retains and retries the exact serialized command, refuses a new intent while an
outcome is uncertain, and exposes unused-grant revocation. Preflight shows the
result rather than only its receipt metadata. Operator inputs must be absolute
regular files staged within the workspace, without symlink ancestors. This is a
same-user file boundary, not isolation from another process owned by that user.
Browser results redact structured secret fields and host paths; resultDigest
identifies the served redacted result. CLI receipts retain their original result.
