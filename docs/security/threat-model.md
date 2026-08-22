# Living Threat Model

> Status: Active M0 baseline  
> Last reviewed: 2026-08-22  
> Scope: ResearchSpec authoring, validation, schema generation and planned control-plane boundaries

This document is intentionally updated as executable capability is added. A mitigation marked “planned” is not a security property of the current code.

## 1. Security objectives

1. A model, plugin, Worker or evidence source cannot silently change an accepted research revision.
2. Unknown, failed, timed-out or disconnected execution is never reported as success.
3. Paid, destructive, privileged and data-releasing actions remain inside explicit policy and approval limits.
4. Secrets and private content are not embedded in ResearchSpec, events, logs, artifacts or images.
5. Evidence provenance, rights and allowed uses survive transformation.
6. Events and artifacts can be verified, correlated and reconstructed without trusting a dashboard projection.
7. Researcher dissent and AI dissent remain auditable; neither is rewritten into false consensus.

## 2. Current boundary

M0 parses local YAML/JSON, validates a ResearchSpec, generates JSON Schema and compares immutable revisions. It does **not** execute workflow blocks, evaluate `until` expressions, contact model APIs, run plugins, start containers, connect Workers, spend money or upload artifacts.

| Zone | Trust assumption | Current status |
|---|---|---|
| Researcher and local CLI | Authorized caller, but input may contain mistakes | Implemented |
| ResearchSpec document | Untrusted structured input | Implemented validation boundary |
| Core protocol package | Trusted kernel code | Implemented subset |
| Generated JSON Schema | Published external contract | Implemented |
| AI/model providers | Untrusted proposals and content | Not connected in M0 |
| Evidence connectors | Untrusted content and metadata | Not connected in M0 |
| Plugins/custom code | Arbitrary-code risk | Not executed in M0 |
| Local/remote Workers | Partially trusted execution nodes | Not connected in M0 |
| Event and artifact stores | Integrity and confidentiality targets | Planned in later M0 slices |

## 3. Protected assets

- research questions, unpublished hypotheses and negative results;
- dataset contents, rights records and provenance;
- model configurations, checkpoints and evaluation samples;
- API credentials, cloud credentials and Worker identities;
- budget, approval and autonomy policies;
- immutable revision, event and artifact histories;
- contributor machines and CI credentials;
- the public protocol and release supply chain.

## 4. Adversaries and failure sources

- a malicious or compromised plugin, dependency, Worker or model provider;
- poisoned papers, notes, repositories, datasets or retrieved web content;
- an authorized user or AI configuration granted excessive capability;
- an accidental malformed spec, unsafe cost limit or ambiguous state transition;
- a remote attacker targeting a future public control plane;
- supply-chain compromise in dependencies, CI actions or released packages.

## 5. Kernel security invariants

- Structural unknown fields fail closed; extensibility is explicit.
- A started Run refers to an immutable ResearchSpec revision.
- Arbitrary graph back-edges are invalid; research iteration is an explicit bounded block.
- Paid or accelerated loops declare both cost and wall-time caps.
- Unknown source rights cannot authorize training or redistribution.
- AI output is a proposal until an external policy engine authorizes an action.
- Secrets are referenced, never stored as ordinary protocol values.
- Facts are appended; corrections create new facts rather than rewriting history.
- Artifact content is addressed and verified by digest before use.
- Failure, disconnection and unknown are distinct terminal or recovery states.

Only the first five invariants have partial executable checks in the current M0 slice. The remaining invariants are implementation requirements for subsequent slices.

## 6. Threat register

| ID | Threat | Impact | Current mitigation | Required verification/status |
|---|---|---|---|---|
| TM-001 | Hidden or misspelled fields change intended behavior | Policy or experiment bypass | Strict Pydantic models with `extra=forbid`; declared `config`/`extensions` only | Tested in M0 |
| TM-002 | Arbitrary workflow cycles create infinite execution | Denial of service and uncontrolled cost | Each graph must be acyclic; explicit `LoopBlock` only | Tested in M0 |
| TM-003 | Paid/GPU loop omits termination limits | Budget loss | Iteration count plus cost and wall-time caps for risky capabilities | Tested in M0; runtime enforcement planned |
| TM-004 | Unknown-rights material enters training data | Legal, ethical and publication harm | Rights and allowed use are separate; unknown denies training/redistribution | Tested in M0; provenance propagation planned |
| TM-005 | Broken entity or edge reference resolves unpredictably | Wrong experiment or result attribution | Global entity IDs, scoped node IDs and references are validated | Tested in M0 |
| TM-006 | Prompt injection in papers, notes or repositories controls the assistant | Unauthorized tool use or exfiltration | Evidence is data, not instruction; model actions pass external policy | M1 adversarial tests required |
| TM-007 | Secret appears in spec, log, event, model prompt or artifact | Credential and private-data exposure | Planned typed secret references, redaction and sink policies | Blocker before external APIs/Workers |
| TM-008 | Malicious plugin escapes or receives excess capability | Host or data compromise | Planned tiered process/container isolation and capability manifests | Blocker before community plugins |
| TM-009 | Worker spoofing, replay or stale lease executes a task twice | Cost, corruption or data exposure | Planned authenticated outbound connection, short leases, nonces and idempotency | M2 protocol tests required |
| TM-010 | Artifact is replaced after validation | Poisoned model/data or false reproducibility | Planned content addressing and digest verification | Later M0 artifact slice |
| TM-011 | Event history is edited or a projection is treated as fact | False audit and recovery state | Planned append-only event source and rebuildable projections | Later M0 event slice |
| TM-012 | AI or user bypasses approval via a low-level adapter | Governance and budget bypass | Policy enforcement belongs to kernel, not UI or adapter | M1 capability tests required |
| TM-013 | Failure, timeout or disconnection is reported as success | Invalid scientific conclusion | Explicit unknown/lost states and verifier failure gates planned | Required before SimulatedRuntime acceptance |
| TM-014 | Cross-project cache, retrieval or artifact lookup leaks data | Confidentiality loss | Planned project-scoped authorization and cache namespaces | Required before multi-project operation |
| TM-015 | Oversized documents or deeply nested loops exhaust parser resources | Local or service denial of service | No public parser endpoint in M0 | Add size/depth limits before network exposure |
| TM-016 | Dependency or GitHub Action compromise runs attacker code | Maintainer/CI compromise | Locked Python dependencies; CI actions pinned to commits; read-only CI token | Review lock changes; add release provenance later |
| TM-017 | Backend `config` is interpreted as a shell command without review | Arbitrary code execution | M0 never executes configs; future BlockManifest declares runtime and permissions | Blocker before NativeProcessRuntime |
| TM-018 | Semantic diff hides meaningful list changes through reordering | Unreviewed experiment change | ID-aware diff reports object additions/removals/changes and ignores only pure reordering | Tested in M0; expand conformance corpus |

## 7. M0 security gates

Before merging executable capability, the following gates apply:

- **Protocol gate:** valid/invalid examples and generated schema stay synchronized.
- **Revision gate:** a running revision cannot be mutated; revision transitions receive semantic diffs.
- **State gate:** success, failure, cancelled, lost and unknown have separate tested meanings.
- **Secret gate:** typed secret references and redaction tests exist before any API credential is used.
- **Execution gate:** no arbitrary process, plugin or expression execution is added without a new threat-model review.
- **Supply-chain gate:** dependencies are locked; third-party CI actions are commit-pinned; CI token is read-only unless a job proves it needs more.

## 8. Explicitly accepted residual risk

- M0 is local pre-release software and does not yet defend a public network service.
- `config` and `extensions` are structurally declared but their future consumers must perform capability-specific validation.
- Rights metadata can be wrong or incomplete; the validator enforces declared policy but is not a legal authority.
- Cost caps in this slice are protocol declarations, not runtime enforcement.
- JSON Schema consumers still need the normative semantic tests for cross-object references and acyclicity.

These risks must not be described as solved until their corresponding executable gates pass.

