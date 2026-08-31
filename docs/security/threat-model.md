# Living Threat Model

> Status: Active M0 baseline
>
> Last reviewed: 2026-08-31
>
> Scope: protocol validation, deterministic planning, local event persistence, local artifact objects and their explicit CLI, Run/Attempt projection, RunControl, deterministic SimulatedRuntime, its strict local CLI, and explicit Run/Attempt cancellation requests

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

M0 parses local YAML/JSON, validates ResearchSpec, ResearchEvent and BlockManifest documents,
generates JSON Schema, compares immutable revisions, compiles a deterministic dry-run report,
can append complete events to a local SQLite fact store, can query, verify and replay those
facts through a read-only CLI, can import regular local files into a content-addressed
artifact directory through Python or an explicit put/verify CLI, and can append Run/Attempt
lifecycle events through RunControl, which
replays a frozen global head, preflights the pure reducer, and compare-and-sets the store.
SimulatedRuntime can then drive one ready `simulated.experiment@0.1.0` task through that
boundary. A strict `SimulationRequest` and `runs simulate` CLI expose that path without
minting identity or retrying conflict. A strict `RunCancellationRequest` can append one
cancellation-request fact to an existing store, but sends no signal and infers no outcome.
It does **not** import manifest entrypoints, evaluate `until` expressions,
contact model APIs, run plugins, start containers, connect Workers, spend money, persist
projections, index artifacts in SQLite or upload artifacts. Simulated `completed` is a
controlled lifecycle finish, not training success.

| Zone | Trust assumption | Current status |
|---|---|---|
| Researcher and local CLI | Authorized caller, but input may contain mistakes | Implemented |
| ResearchSpec document | Untrusted structured input | Implemented validation boundary |
| Core protocol package | Trusted kernel code | Implemented subset |
| Generated JSON Schema | Published external contract | Implemented |
| BlockManifest and sealed registry | Untrusted declarations resolved as inert data | Implemented validation and digest boundary |
| Dry-run plan/report | Trusted-kernel output, not an execution result | Implemented pure planning boundary |
| AI/model providers | Untrusted proposals and content | Not connected in M0 |
| Evidence connectors | Untrusted content and metadata | Not connected in M0 |
| Plugins/custom code | Arbitrary-code risk | Not executed in M0 |
| Local/remote Workers | Partially trusted execution nodes | Not connected in M0 |
| Local SQLite event store | Integrity and confidentiality target | Append/read/query/replay foundation implemented for review |
| RunControl append boundary | Trusted-kernel write gate over EventStore | Implemented for review; SimulatedRuntime is a caller and does not auto-retry |
| SimulatedRuntime | Deterministic single-task simulated lifecycle | Implemented for review; canonical builtin digest only; no GPU, network, entrypoint, spec.resources, or scientific conclusion |
| Simulated Run CLI | Local request-to-RunSnapshot adapter | Implemented for review; strict versioned request, explicit identity, no conflict retry, exact RunSnapshot JSON |
| Run Cancellation CLI | Local single-fact cancellation-request adapter | Implemented for review; existing store only, explicit identity, no signal, no inferred outcome or conflict retry |
| Artifact Object CLI | Local object import and full verification adapter | Implemented for review; existing root only, no byte output, SQLite row, event, delete or upload |
| Artifact store and query projections | Integrity and confidentiality targets | Local file CAS and CLI implemented; SQLite artifact index and persistent projections planned |

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
- A cancellation request is distinct from an observed cancelled outcome.
- Every planned task resolves one exact block version and manifest digest.
- Dry-run cannot execute a block or claim an execution result.

ResearchSpec, exact block resolution, pure planning, append-only event-store, local artifact
object and RunControl preflight/CAS invariants have executable checks. SQLite artifact indexing,
secret, policy-execution, persistent projection and runtime-state invariants remain requirements
for subsequent slices.

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
| TM-010 | Artifact is replaced after validation | Poisoned model/data or false reproducibility | Content-addressed local objects; root `st_dev`/`st_ino` identity; dirfd walk of `tmp`/`objects`/`sha256`/shard with `O_NOFOLLOW`; digest-derived basenames; atomic `link` plus directory fsync; existing mismatch fails closed and is not overwritten | File object layer tested, including intermediate symlink escape, root substitution and fsync-retry recovery; SHA-256 detects accidental corruption, not a host admin who rewrites files and recomputes the digest |
| TM-011 | Event history is edited or a projection is treated as fact | False audit and recovery state | SQLite facts reject UPDATE/DELETE/REPLACE; reads verify canonical JSON, digest and indexes; query/replay CLI and in-memory folds are rebuildable consumers; RunControl does not persist snapshots | Event source, replay fold and RunControl tested; persistent projections pending |
| TM-012 | AI or user bypasses approval via a low-level adapter | Governance and budget bypass | Policy enforcement belongs to kernel, not UI or adapter | M1 capability tests required |
| TM-013 | Failure, timeout or disconnection is reported as success | Invalid scientific conclusion | Explicit unknown/lost states; RunControl rejects illegal lifecycle jumps before write; SimulatedRuntime stops on `attempt.unknown` and never degrades unknown to failure or success | Run/Attempt reducer, RunControl and SimulatedRuntime tested |
| TM-014 | Cross-project cache, retrieval or artifact lookup leaks data | Confidentiality loss | Planned project-scoped authorization and cache namespaces | Required before multi-project operation |
| TM-015 | Oversized documents, YAML alias amplification, configs, schemas or deeply nested loops exhaust resources | Local or service denial of service | Duplicate keys and YAML aliases are rejected; decoded documents, manifests, registries, configs and schemas have byte/depth/node/count limits; configSchema uses an allowlisted non-regex/non-combinatorial subset; planning counts iteratively and never expands iterations | Tested locally; stronger process isolation required before public service exposure |
| TM-016 | Dependency or GitHub Action compromise runs attacker code | Maintainer/CI compromise | Locked Python dependencies; CI actions pinned to commits; read-only CI token | Review lock changes; add release provenance later |
| TM-017 | Backend `config` is interpreted as a shell command without review | Arbitrary code execution | Config is validated against an offline manifest schema and represented only by digest; dry-run never executes it | Runtime isolation remains a blocker before NativeProcessRuntime |
| TM-018 | Semantic diff hides meaningful list changes through reordering | Unreviewed experiment change | ID-aware diff reports object additions/removals/changes and ignores only pure reordering | Tested in M0; expand conformance corpus |
| TM-019 | Registry shadowing or version confusion changes a block silently | Wrong or malicious implementation | Exact id/version lookup, duplicate rejection, sealed registry and manifest digest binding; SimulatedRuntime additionally requires the canonical built-in `simulated.experiment@0.1.0` digest and empty permissions | Tested in M0, including substituted and permission-bearing same-coordinate manifests |
| TM-020 | Manifest loading or dry-run imports code, evaluates text or retrieves a remote schema | Host compromise or data exfiltration | Manifests are revalidated into private inert snapshots; remote refs, expensive Schema keywords and symlinks are rejected; process/import/network/eval tripwires | Tested in M0 |
| TM-021 | Non-deterministic planning corrupts comparison or cache identity | Irreproducible or misattributed experiment | Stable lexical stages and Python-reference content digests without host/time data; golden vectors committed | Tested inside reference implementation; cross-language canonicalization remains open |
| TM-022 | Plan or diagnostic output exposes config, prompt, expression or dynamic-key secrets | Credential/private-data disclosure | Values are represented by digests; config diagnostics expose only rule names; terminal text escapes controls | Partial mitigation; typed SecretRef and general redaction still required |
| TM-023 | A dry-run or simulated result is treated as real training success | Invalid scientific conclusion | Reports say only `ready`/`blocked`, `not-executed`, and four zero side-effect counters; SimulatedRuntime `completed` is a controlled lifecycle finish, not training success, valid metrics, or a supported hypothesis | Tested for dry-run and SimulatedRuntime |
| TM-024 | Concurrent appenders allocate duplicate or reordered sequence values | Ambiguous fact order and broken replay | One `BEGIN IMMEDIATE` transaction allocates global and per-stream versions; database uniqueness checks both identities; RunControl CAS uses the frozen global head and does not retry | Tested with concurrent local connections |
| TM-025 | Corrupt JSON or duplicated index columns are trusted during replay | Wrong projection or concealed event substitution | Every read revalidates canonical event JSON, content digest and extracted columns; full scans reject sequence gaps | Tested locally; no malicious-host guarantee |
| TM-026 | A caller mutates an event draft after reducer preflight and before SQLite write | An illegal lifecycle fact is persisted under a type that never passed preflight | RunControl copies exact JSON dict/list values into a new tree before preflight and `EventStore.append`; cyclic or non-JSON containers fail closed; malformed `type` is validated as ResearchEvent, not hashed | Isolated-snapshot and malformed-type tests |
| TM-027 | A caller mutates ResearchSpec or task config after dry-run / SimulatedRuntime freeze | Written outcome, digests or event path diverge from the reviewed plan | SimulatedRuntime isolates a JSON snapshot before dry-run and reads `outcome` only from that snapshot; nested caller containers are not retained | Freeze and nested-mutation tests |
| TM-028 | A multi-event simulation is treated as one SQLite transaction, or an interrupted prefix is guessed to a terminal outcome | Hidden partial execution or false completed/failed | Each fact is a separate RunControl CAS append; `run()` resumes from a legal EventStore prefix; `completed`/`failed` win over a retained cancellation request; unknown/lost/cancelled, nonterminal Run or active Attempt `cancellationRequested`, and a latest cancelled Attempt return unresolved with zero new facts | Prefix-resume, idempotent terminal, Attempt/Run cancellation and CAS tests |
| TM-029 | A convenience Run CLI silently mints identity, coerces hostile input, retries a conflict, or reports a negative simulated outcome as success | Irreproducible facts, duplicate execution, terminal injection, or false success | Closed alias-only SimulationRequest Schema; duplicate-key/alias/symlink rejection; caller supplies every id/time/stream; exact RunSnapshot JSON; completed=0, domain-negative=1, error/conflict=2; no retry | Schema/model corpus, CLI outcome, idempotence, invalid-input, non-echo, corrupt-store and replay tests |
| TM-030 | A stop command creates an empty store, sends an unreviewed signal, retries stale intent, or reports requested cancellation as an observed outcome | Unintended host action, lost concurrent facts, or false audit state | Closed RunCancellationRequest Schema; existing writable store required; exactly one RunControl CAS fact; lifecycle type derived from a closed target; exact RunSnapshot output; text says no signal and no observed outcome; no conflict retry | Schema/model, missing/corrupt-store, Run/Attempt target, terminal/binding, non-echo and concurrent same-head tests |
| TM-031 | An artifact convenience command follows a caller path into another object, treats a path as a digest, emits caller paths or object bytes as successful output, repairs corruption or claims unrecorded provenance | File disclosure or overwrite, false integrity, misleading lineage | CLI delegates to the dirfd-anchored LocalArtifactStore; digest grammar derives every object key; successful put/verify output is only a closed versioned report; no object-byte stdout, repair, SQLite row, event, delete, upload or provenance claim | Report Schema/semantics, import/verify, success-path omission, symlink/traversal, missing/corrupt object and terminal-escape tests |

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
- Cancellation-request `actor.id` is claimed metadata, not authentication; local OS access to
  the request and database is the current authority boundary.
- `config` and `extensions` are structurally declared but their future consumers must perform capability-specific validation.
- M0 has no typed `SecretRef`; users must not place credentials in ResearchSpec or manifests. Dry-run avoids echoing arbitrary values but is not a complete secret-scanning system.
- Rights metadata can be wrong or incomplete; the validator enforces declared policy but is not a legal authority.
- Cost caps in this slice are protocol declarations, not runtime enforcement.
- JSON Schema consumers still need the normative semantic tests for cross-object references and acyclicity.
- v0alpha1 digests are opaque Python-reference identifiers, not independently verifiable
  cross-language canonical hashes; stable protocol work must adopt a normative encoding.
- A host administrator can disable SQLite triggers, rewrite the file and recompute unkeyed
  digests. M0 has no signature, external anchor or deletion-proof hash chain.
- Local artifact SHA-256 likewise detects accidental truncation or bit-rot, but cannot resist a
  host administrator who replaces object bytes and updates the digest in lockstep. Dirfd anchoring
  stops intermediate symlink escape and root-path substitution; it does not stop a privileged
  writer who can mutate the already-opened inode. Artifact rows, media types and deletion/GC remain
  unimplemented, so the CLI report is not durable metadata and there is still no index or
  tombstone independent of the file tree.
- ResearchEvent payload size/depth limits remain open; the local store does not yet add a
  separate operational byte/depth cap.
- YAML node and depth budgets are enforced after alias-free composition. The 8 MiB source
  cap bounds input size, but transient parser memory is still a residual risk until
  composer-phase budgets or process isolation are implemented for a public service.

These risks must not be described as solved until their corresponding executable gates pass.
