# Architecture Decision Records

ADRs record why an architectural constraint exists, its consequences, and how it can be changed. An accepted decision is changed by a new ADR; its history is not silently rewritten.

| ADR | Decision | Decision status | Record status |
|---|---|---|---|
| [0001](0001-independent-research-ir.md) | Independent Research IR | Accepted | Written |
| 0002 | Pydantic/JSON Schema authority | Superseded by ADR-0013 | Historical shorthand |
| [0003](0003-minimal-trusted-kernel.md) | Minimal trusted kernel | Accepted | Written |
| [0004](0004-modular-monolith.md) | Modular monolith first | Accepted | Written |
| [0005](0005-researcher-final-decision.md) | Researcher final decision and preserved AI dissent | Accepted | Written; ADR-0039 D2 adds required decision rationale and overridden-dissent references |
| [0006](0006-capability-budget-approval-autonomy.md) | Capability-, budget-, and approval-based autonomy | Accepted | Written |
| [0007](0007-append-only-facts-rebuildable-projections.md) | Append-only facts and rebuildable projections | Accepted | Written |
| [0008](0008-native-process-and-oci-runtimes.md) | Native process and OCI runtimes | Accepted | Written; M0 milestone scope clarified by ADR-0034; non-executing native preflight implemented, native/OCI executors pending |
| [0009](0009-worker-semantics-independent-of-transport.md) | Worker semantics independent of transport | Accepted | Written |
| 0010 | ms-swift as provisional first real backend | Direction accepted | M2 validation pending |
| [0011](0011-apache-2-license.md) | Apache-2.0 project license | Accepted | Written; CONTRIBUTING, fork-PR DCO and templates added by ADR-0038 E11; English-primary CONTRIBUTING and engineering standards by ADR-0040 |
| [0012](0012-python-and-dependencies.md) | Python 3.12+, pyproject and uv | Accepted | Written |
| [0013](0013-schema-authority.md) | Versioned JSON Schema external contract | Accepted | Written |
| [0014](0014-cloudevents-compatible-research-event.md) | CloudEvents-compatible ResearchEvent envelope | Accepted | Written |
| [0015](0015-sqlite-event-source-projections-and-artifacts.md) | SQLite event source, projections and artifact addressing | Accepted | Event source, query/replay, in-memory folds, local file CAS, schema v2 query tables and verified high-water cache (ADR-0041) |
| 0016 | Tiered plugin trust and isolation | Direction accepted | M1 implementation pending; M1 built-in adapters scoped T0/T1 in-process by ADR-0038 E5 |
| [0017](0017-minimal-model-interface.md) | Minimal model interface and capability negotiation | Accepted | Implemented; M1-2 DeterministicMockProvider and `ai.call.*` digest facts; OpenAI-compatible adapter remains M1-4 |
| [0018](0018-explicit-bounded-loops.md) | Explicit bounded research loops | Accepted | Written |
| [0019](0019-evidence-rights-by-use.md) | Evidence rights tracked by use | Accepted | Implemented for local Markdown/PDF import (M1-3); Git/web connectors pending |
| 0020 | Capability evaluation and progressive autonomy | Direction accepted | M1 implementation pending |
| 0021 | Remote Worker transport and connection bootstrap | Deferred | M2 experiment required |
| 0022 | First cloud-provider adapter | Provisional | M2 live verification required |
| [0023](0023-inert-manifests-and-pure-dry-run.md) | Inert manifests and pure deterministic dry-run | Accepted | Implemented |
| [0024](0024-run-attempt-state-machine.md) | Pure Run and Attempt state machine | Accepted | Implemented |
| [0025](0025-atomic-run-control-append-boundary.md) | Atomic RunControl append boundary | Accepted | Implemented; write-cost model relaxed for schema v2 by ADR-0041 |
| [0026](0026-deterministic-simulated-runtime.md) | Deterministic SimulatedRuntime | Accepted | Implemented; M1-0 consumes cancellation requests and emits `attempt.cancelled` / `run.cancelled` |
| [0027](0027-explicit-simulated-run-cli.md) | Explicit Simulated Run CLI | Accepted | Implemented |
| [0028](0028-explicit-run-cancellation-request.md) | Explicit Run/Attempt cancellation request CLI | Accepted | Implemented |
| [0029](0029-explicit-local-artifact-object-cli.md) | Explicit local artifact object CLI | Accepted | Implemented |
| [0030](0030-deterministic-plan-authorization-gate.md) | Deterministic plan authorization gate | Accepted | Implemented |
| [0031](0031-explicit-plan-authorization-cli.md) | Explicit non-credential plan authorization CLI | Accepted | Implemented |
| [0032](0032-audit-only-plan-authorization-events.md) | Audit-only plan authorization evaluation events | Accepted | Implemented |
| [0033](0033-normative-jcs-semantic-digests.md) | Normative RFC 8785 JCS semantic digests | Accepted | Implemented |
| [0034](0034-m0-scope-clarification.md) | M0 native-process milestone is NativeProcessPreflight, not NativeProcessRuntime | Accepted | Written |
| [0035](0035-read-only-plan-authorization-lineage.md) | Read-only plan authorization lineage query | Accepted | Implemented |
| [0036](0036-in-process-run-decision-digest.md) | In-process plan-authorization decisionDigest on RunSnapshot | Accepted | Implemented |
| [0037](0037-m0-kernel-proof-closure.md) | M0 kernel-proof closure | Accepted | Written |
| [0038](0038-charter-errata-after-m0.md) | Charter v0.1 errata after M0; M0 debts, M1 order, checkpoint and budget; errata method and ADR granularity | Accepted | Written |
| [0039](0039-human-help-period-purpose.md) | The OS serves the period in which human help remains necessary; researcher modeled as teacher; sanctioned AI→researcher question channel; human-attention metric; gated persistence into parameters | Accepted | Written; M1-1 implements proposal/dissent/decision + ResearchLedger; question channel is Issue #42 |
| [0040](0040-english-primary-and-engineering-standards.md) | English is the working language; comments record invariants, not a ratio; coverage floor 85%; typed package; commit-msg hook; Dependabot | Accepted | Written; operational checklist in `docs/engineering-standards.md` |
| [0041](0041-verified-high-water-cache-and-query-tables.md) | Verified high-water cache and rebuildable SQLite query tables | Accepted | Implemented; schema v2 (`integrity_checkpoint`, `run_projections`, `spec_revisions`, `artifacts` / `artifact_links`) |

M0 kernel proof closed 2026-09-03; see ADR-0037. ADR-0015 remainders (SQLite artifact index and persistent projections) are delivered by ADR-0041 as M1-0.

From ADR-0038 E10 onward an ADR records a constraint or trade-off; a new command, report or CLI surface is documented by a protocol document and a guide instead of its own ADR.
