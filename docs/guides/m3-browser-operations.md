# Operate a run from the browser

Requirements: [browser operations](../protocols/browser-operations-v0alpha1.md),
[local API](m3-local-api.md), [workbench](m3-workbench.md).
Status: **R11 candidate, not accepted.**

## Open Operations

Start the server, open the bootstrap URL, then choose **Operations**.

Every action here is a document you supply that the server dispatches through the
same shared services the CLI uses. The browser cannot create authority.

## Inspect a plan before you authorize it

Enter a `ResearchSpec` path and press **Preflight**. You get the plan identity and
spec digest, the target workflows, datasets and models, the policy flags, the
resources the spec declares with their cost and wall-time limits, and the limits
this build actually enforces.

Read two lines carefully:

- **Resource and budget requirements are declared, not enforced.** A preflight
  checks nothing about your GPU or your budget and reserves nothing.
- **`launchAllowed` is false.** A preflight is not a launch credential and carries
  no signature.

Nothing is appended. The receipt shows `Facts appended: None`.

## Request a cancellation

Enter a `RunCancellationRequest` path and press **Request cancellation**. See
[the request format](native-worker-cli.md) and the repository's
`examples/run-cancellation-requests/valid/run.json`.

The receipt will say:

- **Request recorded — no observed stop**

That is the whole truth. A cancellation is a *request* that you asked for
something to stop. It is not evidence that anything stopped. Go to **Runs** and
the run will still show whatever its facts say — usually still `Running`. It
becomes `Stopped (observed)` only when a later fact records the stop.

If the run is already terminal, the request is refused: a completed or failed run
cannot be reopened, and the receipt will say so. Nothing is appended.

## Revoke unused authority

Revocation is available through the shared service and recorded as a
control-plane `grant.revoked` fact. It needs no Worker credential, because this
surface must never hold one. It does not complete, stop or launch anything, and
an unknown grant is refused.

## Double-clicks, retries and lost responses

You do not need to be careful about clicking twice, and you should not try to be.

Each of your actions gets one command identity. If the response is lost, the UI
shows **Outcome not confirmed** and keeps that identity. Sending the same action
again either replays the original receipt or appends one fact — never two. The
UI says so explicitly rather than guessing which happened.

A refusal appends nothing.

## What this cannot do

- **It cannot start a run, or reconnect and observe one.** Those need the
  reviewed native launch path, whose live two-host evidence is still pending.
- **It cannot restore an Attempt.**
- **It cannot approve a proposal.** It dispatches a decision document you have
  already written; the proposal workflow arrives with R12.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `csrf-invalid` | The page was reloaded without re-reading the session, or the session expired. Reload and open the bootstrap URL again. |
| `command-refused` | The shared service refused it. The message is generic on purpose; the CLI will say more for the same document. |
| "Outcome not confirmed" | The request may or may not have committed. Resend it with the same identity. |
| A terminal run refuses cancellation | Correct. Terminal runs cannot be reopened. |

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


Operator-installed native start/observe/checkpoint and verified backup recovery
are documented in [browser native operations](browser-native-operations.md).
