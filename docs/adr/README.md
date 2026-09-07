# Architecture Decision Records

ADRs record why an architectural constraint exists, its consequences, and how it can be changed. An accepted decision is changed by a new ADR; its history is not silently rewritten.

| ADR | Decision | Decision status | Record status |
|---|---|---|---|
| [0001](0001-independent-research-ir.md) | Independent Research IR | Accepted | Written |
| 0002 | Pydantic/JSON Schema authority | Superseded by ADR-0013 | Historical shorthand |
| [0003](0003-minimal-trusted-kernel.md) | Minimal trusted kernel | Accepted | Written |
| [0004](0004-modular-monolith.md) | Modular monolith first | Accepted | Written |
| [0005](0005-researcher-final-decision.md) | Researcher final decision and preserved AI dissent | Accepted | Written; ADR-0039 D2 adds required decision rationale and overridden-dissent references |
| [0006](0006-capability-budget-approval-autonomy.md) | Capability-, budget-, and approval-based autonomy | Accepted | Written; M1-4 runtime-enforces CNY `budget.*` caps on the HTTP adapter |
| [0007](0007-append-only-facts-rebuildable-projections.md) | Append-only facts and rebuildable projections | Accepted | Written |
| [0008](0008-native-process-and-oci-runtimes.md) | Native process and OCI runtimes | Accepted | Written; M0 milestone scope clarified by ADR-0034; non-executing native preflight implemented; M2-0 CPU sandbox is not NativeProcessRuntime (ADR-0043); CPU OCIContainerRuntime is ADR-0045 |
| [0009](0009-worker-semantics-independent-of-transport.md) | Worker semantics independent of transport | Accepted | Written; M2-0 loopback long-poll binding (ADR-0043); isolated loopback HTTPS/JSON (ADR-0044); remote pack and TLS unicast bind (ADR-0021) are pending-live, not a two-host proof |
| 0010 | ms-swift as provisional first real backend | Direction accepted | M2 validation pending |
| [0011](0011-apache-2-license.md) | Apache-2.0 project license | Accepted | Written; CONTRIBUTING, fork-PR DCO and templates added by ADR-0038 E11; English-primary CONTRIBUTING and engineering standards by ADR-0040 |
| [0012](0012-python-and-dependencies.md) | Python 3.12+, pyproject and uv | Accepted | Written |
| [0013](0013-schema-authority.md) | Versioned JSON Schema external contract | Accepted | Written |
| [0014](0014-cloudevents-compatible-research-event.md) | CloudEvents-compatible ResearchEvent envelope | Accepted | Written |
| [0015](0015-sqlite-event-source-projections-and-artifacts.md) | SQLite event source, projections and artifact addressing | Accepted | Event source, query/replay, in-memory folds, local file CAS, schema v2 query tables and verified high-water cache (ADR-0041) |
| 0016 | Tiered plugin trust and isolation | Direction accepted | M1 implementation pending; M1 built-in adapters scoped T0/T1 in-process by ADR-0038 E5 |
| [0017](0017-minimal-model-interface.md) | Minimal model interface and capability negotiation | Accepted | Implemented; DeterministicMockProvider (M1-2) and in-process OpenAI-compatible HTTP adapter with budget facts (M1-4) |
| [0018](0018-explicit-bounded-loops.md) | Explicit bounded research loops | Accepted | Written |
| [0019](0019-evidence-rights-by-use.md) | Evidence rights tracked by use | Accepted | Implemented for local Markdown/PDF import (M1-3); Git/web connectors pending |
| 0020 | Capability evaluation and progressive autonomy | Direction accepted | M1 implementation pending |
| [0021](0021-remote-worker-transport.md) | Remote Worker transport and connection bootstrap | Accepted | Implemented pack + TLS SAN bind policy; live two-host verification is `pending-live`; loopback is not a cross-machine proof |
| 0022 | First cloud-provider adapter | Provisional | M2 live verification required |
| [0023](0023-inert-manifests-and-pure-dry-run.md) | Inert manifests and pure deterministic dry-run | Accepted | Implemented |
| [0024](0024-run-attempt-state-machine.md) | Pure Run and Attempt state machine | Accepted | Implemented |
| [0025](0025-atomic-run-control-append-boundary.md) | Atomic RunControl append boundary | Accepted | Implemented; write-cost model relaxed for schema v2 by ADR-0041 |
| [0026](0026-deterministic-simulated-runtime.md) | Deterministic SimulatedRuntime | Accepted | Implemented; M1-0 consumes cancellation requests and emits `attempt.cancelled` / `run.cancelled`; M1-5 optionally emits seeded synthetic `training.step` / `evaluation.metric` after `attempt.started`; M1-6 consumes a local `{eventId, sequence}` authorization citation before lifecycle writes (ADR-0042) |
| [0027](0027-explicit-simulated-run-cli.md) | Explicit Simulated Run CLI | Accepted | Implemented |
| [0028](0028-explicit-run-cancellation-request.md) | Explicit Run/Attempt cancellation request CLI | Accepted | Implemented |
| [0029](0029-explicit-local-artifact-object-cli.md) | Explicit local artifact object CLI | Accepted | Implemented |
| [0030](0030-deterministic-plan-authorization-gate.md) | Deterministic plan authorization gate | Accepted | Implemented |
| [0031](0031-explicit-plan-authorization-cli.md) | Explicit non-credential plan authorization CLI | Accepted | Implemented |
| [0032](0032-audit-only-plan-authorization-events.md) | Audit-only plan authorization evaluation events | Accepted | Implemented; M1-6 SimulatedRuntime cites `{eventId, sequence}` on this local store without treating the event as a launch JWT (ADR-0042) |
| [0033](0033-normative-jcs-semantic-digests.md) | Normative RFC 8785 JCS semantic digests | Accepted | Implemented |
| [0034](0034-m0-scope-clarification.md) | M0 native-process milestone is NativeProcessPreflight, not NativeProcessRuntime | Accepted | Written |
| [0035](0035-read-only-plan-authorization-lineage.md) | Read-only plan authorization lineage query | Accepted | Implemented; lineage remains `not-consumed`. The Run citation is SimulatedRuntime consume (ADR-0042), not this query |
| [0036](0036-in-process-run-decision-digest.md) | In-process plan-authorization decisionDigest on RunSnapshot | Accepted | Implemented; `decisionDigest` remains in-process identity. M1-6 additionally cites `{eventId, sequence}` (ADR-0042); the digest alone is no longer sufficient for SimulatedRuntime |
| [0037](0037-m0-kernel-proof-closure.md) | M0 kernel-proof closure | Accepted | Written |
| [0038](0038-charter-errata-after-m0.md) | Charter v0.1 errata after M0; M0 debts, M1 order, checkpoint and budget; errata method and ADR granularity | Accepted | Written |
| [0039](0039-human-help-period-purpose.md) | The OS serves the period in which human help remains necessary; researcher modeled as teacher; sanctioned AI→researcher question channel; human-attention metric; gated persistence into parameters | Accepted | Written; M1-1 implements proposal/dissent/decision + ResearchLedger; question channel (`question.asked` / `question.answered`) is implemented |
| [0040](0040-english-primary-and-engineering-standards.md) | English is the working language; comments record invariants, not a ratio; coverage floor 85%; typed package; commit-msg hook; Dependabot | Accepted | Written; operational checklist in `docs/engineering-standards.md` |
| [0041](0041-verified-high-water-cache-and-query-tables.md) | Verified high-water cache and rebuildable SQLite query tables | Accepted | Implemented; schema v2 (`integrity_checkpoint`, `run_projections`, `spec_revisions`, `artifacts` / `artifact_links`) |
| [0042](0042-m1-local-authorization-consume-and-closure.md) | M1 local authorization consume and numbered-slice status | Accepted | Implemented; SimulatedRuntime consumes `{eventId, sequence}` on this EventStore; #19 local consume delivered; signatures/expiry/revocation for Workers are ADR-0043 / Issue #53; #38 remains open |
| [0043](0043-m2-loopback-worker-and-hmac-grants.md) | M2-0 loopback Worker protocol and HMAC grants | Accepted | Implemented; `execute.local` execution-object grants + loopback long poll + host-python helper; not NativeProcessRuntime, not kernel isolation, not paid GPU, not #38 |
| [0044](0044-isolated-control-plane-and-loopback-https.md) | Isolated control plane and loopback HTTPS Worker | Accepted | Implemented; separate processes/CAS + pinned loopback TLS; not cross-machine, not ADR-0021 remote bootstrap |
| [0045](0045-cpu-oci-container-runtime.md) | CPU OCIContainerRuntime with digest-pinned images | Accepted | Implemented; docker adapter, `execute.oci`, host-python helper unchanged; live engine optional on ordinary hosts; designated Linux CI is ADR-0049; not GPU, not NativeProcessRuntime |
| [0046](0046-worker-stop-fault-recovery.md) | Worker stop, fault, and Run/Attempt recovery | Accepted | Implemented; cancel request ≠ stopped; reconcile completed work to Run; unknown cannot auto-succeed; CPU checkpoint inspectable |
| [0047](0047-eventstore-performance-and-metric-sampling.md) | EventStore 10k/100k baseline and CAS metric chunks | Accepted | Implemented; typed fold reads; no SQLite replacement; bench receipts are not SLA |
| [0048](0048-pinned-ms-swift-adapter.md) | Pinned ms-swift 4.5.2 parse/plan adapter | Accepted | Implemented; no core torch/ms-swift dep; no GPU execution; experiment sheet is not a run |
| [0049](0049-oci-nobody-bind-and-required-linux-ci.md) | Non-root OCI `/in` bind and designated Linux CI | Accepted | Implemented; 0755/0444 bind root for UID 65534; `Linux OCI integration` fails closed; ordinary pytest may skip |
| [0050](0050-observed-execution-identity.md) | Observed execution identity and cancel supervision | Accepted | Implemented; resume+cancel is not stop; pid/container identity; heartbeat supervise; container stop ≠ cloud instance stop |
| [0051](0051-live-cpu-fault-acceptance.md) | Live CPU fault acceptance | Accepted | Implemented; observed cancel/timeout/kill/restart/disconnect; `plane.fail` is not a stop; pending complete retries without rerun |
| [0052](0052-control-path-usage-evidence.md) | Worker/RunControl usage evidence | Accepted | Implemented; mixed research/budget/Worker control path; isolated Worker + cited report; OCI skip is labeled, not a pass in designated CI |
| [0053](0053-gpu-experiment-sheet.md) | GPU experiment sheet without a paid run | Accepted | Named AutoDL 4090 combo, ¥20 proposed cap, CUDA image method; `gpu: not-run`; not M2 acceptance |

M0 kernel proof closed 2026-09-03; see ADR-0037. ADR-0015 remainders (SQLite artifact index and persistent projections) are delivered by ADR-0041 as M1-0. E4 numbered M1 slices have an in-tree status record in ADR-0042; that is not the M1 checkpoint. The question channel is implemented independently of that checkpoint. M2-0 is free protocol verification (ADR-0043), not GPU completion. Isolated loopback HTTPS is ADR-0044, not a cross-machine proof. Remote Worker
transport (ADR-0021) is a pending-live pack: same HTTPS/JSON semantics, no
second-machine claim. CPU OCIContainerRuntime is ADR-0045 and is not a live GPU proof. Worker stop/fault recovery is ADR-0046. EventStore performance baseline and metric chunks are ADR-0047. The pinned ms-swift adapter is ADR-0048 and is not a real training run. Non-root `/in` bind modes and designated Linux OCI CI are ADR-0049. Observed execution identity and cancel supervision are ADR-0050. Live CPU
fault acceptance is ADR-0051. Worker/RunControl usage evidence is ADR-0052:
`m2 usage` is not `EventStore.append` fill; isolated Worker plus a cited
report; OCI skip is labeled. The GPU experiment sheet is ADR-0053: named
combo and image method, unpaid, not a CUDA result.

From ADR-0038 E10 onward an ADR records a constraint or trade-off; a new command, report or CLI surface is documented by a protocol document and a guide instead of its own ADR.
