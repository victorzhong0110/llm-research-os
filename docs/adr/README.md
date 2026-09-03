# Architecture Decision Records

ADRs record why an architectural constraint exists, its consequences, and how it can be changed. An accepted decision is changed by a new ADR; its history is not silently rewritten.

| ADR | Decision | Decision status | Record status |
|---|---|---|---|
| [0001](0001-independent-research-ir.md) | Independent Research IR | Accepted | Written |
| 0002 | Pydantic/JSON Schema authority | Superseded by ADR-0013 | Historical shorthand |
| [0003](0003-minimal-trusted-kernel.md) | Minimal trusted kernel | Accepted | Written |
| [0004](0004-modular-monolith.md) | Modular monolith first | Accepted | Written |
| [0005](0005-researcher-final-decision.md) | Researcher final decision and preserved AI dissent | Accepted | Written |
| [0006](0006-capability-budget-approval-autonomy.md) | Capability-, budget-, and approval-based autonomy | Accepted | Written |
| [0007](0007-append-only-facts-rebuildable-projections.md) | Append-only facts and rebuildable projections | Accepted | Written |
| [0008](0008-native-process-and-oci-runtimes.md) | Native process and OCI runtimes | Accepted | Written; M0 milestone scope clarified by ADR-0034; non-executing native preflight implemented, native/OCI executors pending |
| [0009](0009-worker-semantics-independent-of-transport.md) | Worker semantics independent of transport | Accepted | Written |
| 0010 | ms-swift as provisional first real backend | Direction accepted | M2 validation pending |
| [0011](0011-apache-2-license.md) | Apache-2.0 project license | Accepted | Written; contribution mechanics follow up |
| [0012](0012-python-and-dependencies.md) | Python 3.12+, pyproject and uv | Accepted | Written |
| [0013](0013-schema-authority.md) | Versioned JSON Schema external contract | Accepted | Written |
| [0014](0014-cloudevents-compatible-research-event.md) | CloudEvents-compatible ResearchEvent envelope | Accepted | Written |
| [0015](0015-sqlite-event-source-projections-and-artifacts.md) | SQLite event source, projections and artifact addressing | Accepted | Event source, query/replay, in-memory folds and local file CAS implemented for review; SQLite artifact index and persistent projections pending |
| 0016 | Tiered plugin trust and isolation | Direction accepted | M1 implementation pending |
| 0017 | Minimal model interface and capability negotiation | Direction accepted | M1 implementation pending |
| [0018](0018-explicit-bounded-loops.md) | Explicit bounded research loops | Accepted | Written |
| [0019](0019-evidence-rights-by-use.md) | Evidence rights tracked by use | Accepted | Written |
| 0020 | Capability evaluation and progressive autonomy | Direction accepted | M1 implementation pending |
| 0021 | Remote Worker transport and connection bootstrap | Deferred | M2 experiment required |
| 0022 | First cloud-provider adapter | Provisional | M2 live verification required |
| [0023](0023-inert-manifests-and-pure-dry-run.md) | Inert manifests and pure deterministic dry-run | Accepted | Implemented |
| [0024](0024-run-attempt-state-machine.md) | Pure Run and Attempt state machine | Accepted | Implemented |
| [0025](0025-atomic-run-control-append-boundary.md) | Atomic RunControl append boundary | Accepted | Implemented |
| [0026](0026-deterministic-simulated-runtime.md) | Deterministic SimulatedRuntime | Accepted | Implemented |
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

M0 kernel proof closed 2026-09-03; see ADR-0037. ADR-0015 remainders (SQLite artifact index and persistent projections) are not part of that closure.
