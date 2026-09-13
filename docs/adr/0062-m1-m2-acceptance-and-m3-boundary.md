# ADR-0062: M1/M2 acceptance and the M3 boundary

Status: Accepted by the maintainer's instruction to merge #77/#78 and complete
milestone closure, 2026-09-12. Closure is finalized after the integrated main
checks pass. This document records the accepted scope and does not publish a release.

## Decision and integration

M1's offline research-assistant checkpoint is accepted. M2's local compute and
two-host execution checkpoint is accepted within the platform/evidence scope
below. This is not blanket acceptance of every original charter aspiration or
the public MVP in charter §14.5.

| Integration | Main commit | Scope |
| --- | --- | --- |
| #73 | 229d1b0ced56689fabd1be2bcf715d29f0f12bed | M2 Worker/training stack; accepted evidence tip 57ffdae |
| #77 | 130ddbf10bc3a61f645fda96a35818056674f8c7 | Maintenance boundaries, exact coverage, wheel smoke, status and charter consolidation |
| #78 | 7e5fc33412c61177d0f1ae1623f6034af9c2a819 | Detached Ed25519 attestations; existing Worker grants remain distinct |

The combined code tree is `5f0e1f39e5fa98e1f382d6b8e39310c0517204ce`, identical
to the prior conflict-free integration rehearsal. Final CI records belong to
the actual main commit; individual PR results do not substitute for that check.

## M1 acceptance

ResearchSpec → Mock proposal with prediction/falsification → preserved dissent →
AI question and researcher answer → reasoned decision → local authorization
consumption → simulated Run → event-linked report with attention counters runs
offline at zero cost. A rejected decision queues no Run. Reopening the store
preserves the ledger. Simulated cancellation separates request and observation.

Evidence: [installed-wheel accept/reject receipts](../evidence/m1-m2-maintenance/wheel-smoke.json),
`tests/test_m1_checkpoint.py`, `tests/test_authorization_consume.py`,
`tests/test_simulated_runtime.py`, and the installed-wheel CI gate. Issues #39,
#40, #41 and #42 are resolved. Issue #38 is the M1 umbrella and is closed after
the final main verification. It must not be used as the name of a CUDA milestone.

The consolidated [charter v0.2 reading](../charter-v0.2.md) is accepted with its
incorporation-by-reference clause; the original charter and historical errata
remain available. ADR-0060 and ADR-0061 are accepted through #77 and #78.

## M2 accepted evidence scope

The [live matrix](../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md) retains the
full source records and limitations. Accepted execution platform: Windows/WSL2
+ Docker Engine, plus the independently documented macOS/MPS profile.

| Path | Evidence |
| --- | --- |
| CPU OCI across two hosts | grant.wsl.oci.1, seq 12–14 |
| Disconnect/reconnect | grant.wsl.reconnect.1, seq 41–43 |
| Observed cancellation | grant.wsl.cancel.1, seq 48–50 |
| CUDA first training | cuda.7, 20 steps, seq 116–118 |
| Checkpoint collection | Frozen inventory; 22 uploaded files, control-plane digest verification |
| Full-state minimal restore | cuda.11, checkpoint 10→12, optimizer/scheduler/RNG phase=loaded, seq 164–166 |

cuda.9 stays partial; cuda.10 stays consumed-failed. cuda.1–11 are not reusable.
No training-quality improvement is inferred from the short run. The maintenance
changes do not relabel old live evidence as execution on a newer runtime SHA.

## Explicit deferred or inapplicable scope

- **NativeProcessRuntime and its authorization consumption:** retained in #53
  and assigned to the M3 SSH/non-OCI execution package. The earlier M0 preflight
  remains non-launching. This is unfinished work, not a fulfilled M2 claim.
- **Paid cloud:** not exercised; spend was ¥0. The original charter's first-paid-
  task criterion is explicitly not applicable to this local acceptance. Before
  any future paid task, its provider and budget controls need separate approval
  and acceptance; local evidence cannot certify a cloud provider.
- **Dedicated two-host unknown experiment / extra GPU cancel shot:** not run.
  Existing unit/loopback unknown and two-host CPU cancellation evidence retain
  their narrower labels. Unknown never implies permission to rerun.
- **Public-service readiness:** usable SSH onboarding, restricted process
  profiles, Web UX, plugin isolation and external trial acceptance belong to M3.
  No multi-tenant/public-service claim is made by this milestone closure.
- **Publication:** no tag, package publication or public MVP release is produced
  by acceptance. The package version remains 0.0.0 until a separately authorized
  release. Dependency-update PRs remain independent of milestone acceptance.

This closes the agreed M1/M2 checkpoint work without silently deleting remaining
features, changing historical facts, or making new platform claims.
