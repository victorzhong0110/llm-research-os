# Architecture Decision Records

ADRs record why an architectural constraint exists, its consequences, and how it can be changed. An accepted decision is changed by a new ADR; its history is not silently rewritten.

| ADR | Decision | Decision status | Record status |
|---|---|---|---|
| [0001](0001-independent-research-ir.md) | Independent Research IR | Accepted | Written |
| 0002 | Pydantic/JSON Schema authority | Superseded by ADR-0013 | Historical shorthand |
| [0003](0003-minimal-trusted-kernel.md) | Minimal trusted kernel | Accepted | Written |
| [0004](0004-modular-monolith.md) | Modular monolith first | Accepted | Written |
| 0005 | Researcher final decision and preserved AI dissent | Accepted | Record pending |
| 0006 | Capability-, budget-, and approval-based autonomy | Accepted | Record pending |
| 0007 | Append-only facts and rebuildable projections | Accepted | Record pending |
| 0008 | Native process and OCI runtimes | Accepted | Record pending |
| 0009 | Worker semantics independent of transport | Accepted | Record pending |
| 0010 | ms-swift as provisional first real backend | Direction accepted | M2 validation pending |
| [0011](0011-apache-2-license.md) | Apache-2.0 project license | Accepted | Written; contribution mechanics follow up |
| [0012](0012-python-and-dependencies.md) | Python 3.12+, pyproject and uv | Accepted | Written |
| [0013](0013-schema-authority.md) | Versioned JSON Schema external contract | Accepted | Written |
| 0014 | CloudEvents-compatible ResearchEvent envelope | Accepted | Record pending |
| 0015 | SQLite event source, projections and artifact addressing | Accepted | Record pending |
| 0016 | Tiered plugin trust and isolation | Direction accepted | M1 implementation pending |
| 0017 | Minimal model interface and capability negotiation | Direction accepted | M1 implementation pending |
| [0018](0018-explicit-bounded-loops.md) | Explicit bounded research loops | Accepted | Written |
| [0019](0019-evidence-rights-by-use.md) | Evidence rights tracked by use | Accepted | Written |
| 0020 | Capability evaluation and progressive autonomy | Direction accepted | M1 implementation pending |
| 0021 | Remote Worker transport and connection bootstrap | Deferred | M2 experiment required |
| 0022 | First cloud-provider adapter | Provisional | M2 live verification required |
| [0023](0023-inert-manifests-and-pure-dry-run.md) | Inert manifests and pure deterministic dry-run | Proposed | Implemented for review |

“Record pending” means the decision is already accepted in the project charter but its standalone rationale has not yet been transcribed. It does not reopen the decision.
