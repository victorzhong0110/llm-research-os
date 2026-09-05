# Living Threat Model

> Status: Active M0 baseline; kernel-proof closed 2026-09-03 ([ADR-0037](../adr/0037-m0-kernel-proof-closure.md))
>
> Last reviewed: 2026-09-04
>
> Scope: protocol validation, deterministic planning and plan authorization, audit-only authorization events, read-only authorization lineage reconstruction, in-process RunSnapshot decisionDigest, non-executing native-process preflight, local event persistence, local artifact objects and their explicit CLI, Run/Attempt projection, RunControl, deterministic SimulatedRuntime, its strict local CLI, explicit Run/Attempt cancellation requests, research decision objects and ledger, the in-process deterministic ModelProvider mock with digest-only `ai.call.*` facts, local Markdown/PDF evidence import, the in-process OpenAI-compatible HTTP adapter, runtime CNY budget facts, seeded synthetic `training.step` / `evaluation.metric` facts, and static HTML/Markdown Run reports

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
generates JSON Schema, compares immutable revisions, compiles a deterministic dry-run report and
evaluates exact three-digest capability/permission/requirement authorization without side effects,
can recompute and record one four-digest-bound authorization evaluation as an unauthenticated,
audit-only project/revision fact in an existing verified event store,
can reconstruct the matching authorization facts for one exact plan identity as a read-only
candidate set that is not a Run citation or launch token,
can append complete events to a local SQLite fact store, can query, verify and replay those
facts through a read-only CLI, can import regular local files into a content-addressed
artifact directory through Python or an explicit put/verify CLI, and can append Run/Attempt
lifecycle events through RunControl, which
replays a frozen global head, preflights the pure reducer, and compare-and-sets the store.
SimulatedRuntime can then drive one ready `simulated.experiment@0.1.0` task through that
boundary. A strict `SimulationRequest` and `runs simulate` CLI expose that path without
minting identity or retrying conflict. A strict `RunCancellationRequest` can append one
cancellation-request fact to an existing store, but sends no signal and infers no outcome.
A strict `NativeProcessPreflightRequest` can freeze the requested launch shape for one exact
authorized Python task into a report that denies launch, declares isolation unenforced and records
zero entrypoint imports, processes, signals, network calls and writes.
It can import a regular local Markdown or PDF file into artifact CAS and append
one digest-only `evidence.imported` fact; extracted text and filesystem paths stay
off the event. It can POST to a loopback OpenAI-compatible `/v1/chat/completions`
endpoint and record CNY budget facts plus digest-only `ai.call.*` facts. Remote
HTTP requires a SecretRef, HTTPS, `read.external_api`, and a budget cap. It can
append seeded synthetic `training.step` / `evaluation.metric` facts on a success
simulation when the request supplies those identities, and it can rebuild a
static HTML/Markdown Run report from EventStore. It does
**not** import manifest entrypoints, evaluate `until` expressions,
run plugins, start containers, connect Workers, persist
projections, crawl GitHub/arXiv/the web for evidence, or upload artifacts. Simulated
`completed` is a controlled lifecycle finish, not training success. Local HTTP
generate is ¥0; remote spend is capped by `budget.*` facts.

| Zone | Trust assumption | Current status |
|---|---|---|
| Researcher and local CLI | Authorized caller, but input may contain mistakes | Implemented |
| ResearchSpec document | Untrusted structured input | Implemented validation boundary |
| Core protocol package | Trusted kernel code | Implemented subset |
| Generated JSON Schema | Published external contract | Implemented |
| BlockManifest and sealed registry | Untrusted declarations resolved as inert data | Implemented validation and digest boundary |
| Dry-run plan/report | Trusted-kernel output, not an execution result | Implemented pure planning boundary |
| Plan authorization gate | Trusted-kernel evaluator over one exact ready plan | Implemented; pure decision, no authenticated receipt |
| Plan authorization event recorder | Trusted-kernel audit append over one recomputed decision | Implemented; existing verified store and CAS, but actor is unauthenticated and event is not executable authority |
| Plan authorization lineage query | Trusted-kernel read-only fold over recorded evaluation facts | Implemented; exact plan-identity join, frozen verified prefix, but not a Run citation or executable authority |
| Native process preflight | Pure reviewer for one exact authorized Python task | Implemented; fixed non-shell/no-network profile, but no interpreter identity, enforced isolation, process launch or durable receipt |
| AI/model providers | Untrusted proposals and content | Deterministic mock and in-process OpenAI-compatible HTTP; loopback default; remote requires SecretRef + https + `read.external_api` + budget cap |
| Evidence connectors | Untrusted content and metadata | Local Markdown/PDF import only; no network connectors |
| Plugins/custom code | Arbitrary-code risk | Not executed in M0 |
| Local/remote Workers | Partially trusted execution nodes | Not connected in M0 |
| Local SQLite event store | Integrity and confidentiality target | Append/read/query/replay foundation implemented |
| RunControl append boundary | Trusted-kernel write gate over EventStore | Implemented; SimulatedRuntime is a caller and does not auto-retry |
| SimulatedRuntime | Deterministic single-task simulated lifecycle | Implemented; canonical builtin digest only; no GPU, network, entrypoint, spec.resources, or scientific conclusion; optional synthetic metrics are `kind: synthetic` |
| Static Run report | Rebuildable HTML/Markdown projection | Implemented; every stored-fact summary cites `eventId`; not a fact source; no React Flow |
| Simulated Run CLI | Local request-to-RunSnapshot adapter | Implemented; strict versioned request, explicit identity, no conflict retry, exact RunSnapshot JSON |
| Run Cancellation CLI | Local single-fact cancellation-request adapter | Implemented; existing store only, explicit identity, no signal, no inferred outcome or conflict retry |
| Artifact Object CLI | Local object import and full verification adapter | Implemented; existing root only, no byte output, SQLite row, event, delete or upload |
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
- AI output is a proposal until a plan-bound trusted-kernel policy evaluation authorizes an action.
- Secrets are referenced, never stored as ordinary protocol values.
- Facts are appended; corrections create new facts rather than rewriting history.
- Artifact content is addressed and verified by digest before use.
- Failure, disconnection and unknown are distinct terminal or recovery states.
- A cancellation request is distinct from an observed cancelled outcome.
- Every planned task resolves one exact block version and manifest digest.
- Dry-run cannot execute a block or claim an execution result.
- Native-process preflight cannot import an entrypoint, enforce isolation or authorize a launch.

ResearchSpec, exact block resolution, pure planning, exact plan authorization, append-only
event-store, local artifact object and RunControl preflight/CAS invariants have executable checks.
Authenticated/persistent approval, SQLite artifact indexing, secret, budget-consumption,
persistent projection and real-runtime invariants remain requirements for subsequent slices.

## 6. Threat register

| ID | Threat | Impact | Current mitigation | Required verification/status |
|---|---|---|---|---|
| TM-001 | Hidden or misspelled fields change intended behavior | Policy or experiment bypass | Strict Pydantic models with `extra=forbid`; declared `config`/`extensions` only | Tested in M0 |
| TM-002 | Arbitrary workflow cycles create infinite execution | Denial of service and uncontrolled cost | Each graph must be acyclic; explicit `LoopBlock` only | Tested in M0 |
| TM-003 | Paid/GPU loop omits termination limits | Budget loss | Iteration count plus cost and wall-time caps for risky capabilities | Tested in M0; runtime enforcement planned |
| TM-004 | Unknown-rights material enters training data | Legal, ethical and publication harm | Rights and allowed use are separate; unknown denies training/redistribution | Tested in M0; provenance propagation planned |
| TM-005 | Broken entity or edge reference resolves unpredictably | Wrong experiment or result attribution | Global entity IDs, scoped node IDs and references are validated | Tested in M0 |
| TM-006 | Prompt injection in papers, notes or repositories controls the assistant | Unauthorized tool use or exfiltration | Evidence is data, not instruction; `evidence.imported` stores digests not bodies; `DeterministicMockProvider` still refuses disallowed capabilities after an adversarial note is imported; the HTTP adapter's allowed set is `generate` only | Adversarial Markdown corpus in M1-3; HTTP adapter refuses `tools` before any request (M1-4) |
| TM-007 | Secret appears in spec, log, event, model prompt or artifact | Credential and private-data exposure | Typed `SecretRef`; redaction of secret-bearing keys and known values; `env` resolver never puts the value in errors. Remote HTTP generate requires SecretRef + https; loopback forbids SecretRef. Inline secrets in specs still forbidden. File/keyring backends pending | Type, redaction, and remote-gate tests; secret value must not appear on events or problem reports |
| TM-008 | Malicious plugin escapes or receives excess capability | Host or data compromise | Planned tiered process/container isolation and capability manifests | Blocker before community plugins |
| TM-009 | Worker spoofing, replay or stale lease executes a task twice | Cost, corruption or data exposure | Planned authenticated outbound connection, short leases, nonces and idempotency | M2 protocol tests required |
| TM-010 | Artifact is replaced after validation | Poisoned model/data or false reproducibility | Content-addressed local objects; root `st_dev`/`st_ino` identity; dirfd walk of `tmp`/`objects`/`sha256`/shard with `O_NOFOLLOW`; digest-derived basenames; atomic `link` plus directory fsync; existing mismatch fails closed and is not overwritten | File object layer tested, including intermediate symlink escape, root substitution and fsync-retry recovery; SHA-256 detects accidental corruption, not a host admin who rewrites files and recomputes the digest |
| TM-011 | Event history is edited or a projection is treated as fact | False audit and recovery state | SQLite facts reject UPDATE/DELETE/REPLACE; reads verify canonical JSON, digest and indexes; query/replay CLI and in-memory folds are rebuildable consumers; `run_projections` / spec and artifact indexes rebuild from `events` and are not used as fold starts; high-water checkpoint is revalidated against live sequence, last digest and schema before reuse; a missing checkpoint row is an invalid cache, not altered DDL | Event source, replay fold, RunControl, missing/tampered checkpoint tests and query-table rebuild tested |
| TM-012 | AI or user bypasses approval via a low-level adapter | Governance and budget bypass | Pure trusted-kernel gate revalidates ready reports, binds all three digests and evaluates exact capabilities, permissions and requirements; SimulatedRuntime invokes it before writes | Gate and T0 integration tested; authenticated persistent approval and every future runtime still required |
| TM-013 | Failure, timeout or disconnection is reported as success | Invalid scientific conclusion | Explicit unknown/lost states; RunControl rejects illegal lifecycle jumps before write; SimulatedRuntime stops on `attempt.unknown` and never degrades unknown to failure or success | Run/Attempt reducer, RunControl and SimulatedRuntime tested |
| TM-014 | Cross-project cache, retrieval or artifact lookup leaks data | Confidentiality loss | Planned project-scoped authorization and cache namespaces | Required before multi-project operation |
| TM-015 | Oversized documents, YAML alias amplification, configs, schemas or deeply nested loops exhaust resources | Local or service denial of service | Duplicate keys and YAML aliases are rejected; decoded documents, manifests, registries, configs and schemas have byte/depth/node/count limits; configSchema uses an allowlisted non-regex/non-combinatorial subset; planning counts iteratively and never expands iterations | Tested locally; stronger process isolation required before public service exposure |
| TM-016 | Dependency or GitHub Action compromise runs attacker code | Maintainer/CI compromise | Locked Python dependencies; CI actions pinned to commits; read-only CI token | Review lock changes; add release provenance later |
| TM-017 | Backend `config` is interpreted as a shell command without review | Arbitrary code execution | Config is validated against an offline manifest schema and represented only by digest; dry-run never executes it; native preflight requires `shell=false`, fixed trusted-runner argv semantics and a fixed JSON-stdio protocol | Enforceable isolation and trusted argv construction remain blockers before NativeProcessRuntime |
| TM-018 | Semantic diff hides meaningful list changes through reordering | Unreviewed experiment change | ID-aware diff reports object additions/removals/changes and ignores only pure reordering | Tested in M0; expand conformance corpus |
| TM-019 | Registry shadowing or version confusion changes a block silently | Wrong or malicious implementation | Exact id/version lookup, duplicate rejection, sealed registry and manifest digest binding; SimulatedRuntime additionally requires the canonical built-in `simulated.experiment@0.1.0` digest and empty permissions | Tested in M0, including substituted and permission-bearing same-coordinate manifests |
| TM-020 | Manifest loading or dry-run imports code, evaluates text or retrieves a remote schema | Host compromise or data exfiltration | Manifests are revalidated into private inert snapshots; remote refs, expensive Schema keywords and symlinks are rejected; process/import/network/eval tripwires | Tested in M0 |
| TM-021 | Non-deterministic planning corrupts comparison or cache identity | Irreproducible or misattributed experiment | Stable lexical stages and RFC 8785 JCS semantic digests (`jcs-sha256:`) without host/time data; Python and Node golden corpus committed | Adopted JCS with Python + Node golden conformance; residual risk is I-JSON profile (high-precision values MUST be strings) and that tags are part of identity |
| TM-022 | Plan or diagnostic output exposes config, prompt, expression or dynamic-key secrets | Credential/private-data disclosure | Values are represented by digests; config diagnostics expose only rule names; terminal text escapes controls; `redact_object` / `message_without_secrets` strip secret keys and known values | Partial mitigation; SecretRef type landed; sink policy for model prompts still required |
| TM-023 | A dry-run or simulated result is treated as real training success | Invalid scientific conclusion | Reports say only `ready`/`blocked`, `not-executed`, and four zero side-effect counters; SimulatedRuntime `completed` is a controlled lifecycle finish, not training success, valid metrics, or a supported hypothesis; synthetic `training.step` / `evaluation.metric` are `kind: synthetic` and the static report is a projection | Tested for dry-run, SimulatedRuntime, and `researchos report` |
| TM-024 | Concurrent appenders allocate duplicate or reordered sequence values | Ambiguous fact order and broken replay | One `BEGIN IMMEDIATE` transaction allocates global and per-stream versions; database uniqueness checks both identities; RunControl CAS uses the frozen global head and does not retry | Tested with concurrent local connections |
| TM-025 | Corrupt JSON or duplicated index columns are trusted during replay | Wrong projection or concealed event substitution | Every read revalidates canonical event JSON, content digest and extracted columns; full scans reject sequence gaps | Tested locally; no malicious-host guarantee |
| TM-026 | A caller mutates an event draft after reducer preflight and before SQLite write | An illegal lifecycle fact is persisted under a type that never passed preflight | RunControl copies exact JSON dict/list values into a new tree before preflight and `EventStore.append`; cyclic or non-JSON containers fail closed; malformed `type` is validated as ResearchEvent, not hashed | Isolated-snapshot and malformed-type tests |
| TM-027 | A caller mutates ResearchSpec or task config after dry-run / SimulatedRuntime freeze | Written outcome, digests or event path diverge from the reviewed plan | SimulatedRuntime isolates a JSON snapshot before dry-run and reads `outcome` only from that snapshot; nested caller containers are not retained | Freeze and nested-mutation tests |
| TM-028 | A multi-event simulation is treated as one SQLite transaction, or an interrupted prefix is guessed to a terminal outcome | Hidden partial execution or false completed/failed | Each fact is a separate RunControl CAS append; `run()` resumes from a legal EventStore prefix; `completed`/`failed` win over a retained cancellation request; unknown/lost are not collapsed to cancelled; a running Attempt with a Run-level cancel request emits `attempt.cancelled` then `run.cancelled` using caller-owned identities | Prefix-resume, idempotent terminal, Attempt/Run cancellation, unknown-not-collapsed and CAS tests |
| TM-029 | A convenience Run CLI silently mints identity, coerces hostile input, retries a conflict, or reports a negative simulated outcome as success | Irreproducible facts, duplicate execution, terminal injection, or false success | Closed alias-only SimulationRequest Schema; duplicate-key/alias/symlink rejection; caller supplies every id/time/stream; exact RunSnapshot JSON; completed=0, domain-negative=1, error/conflict=2; no retry | Schema/model corpus, CLI outcome, idempotence, invalid-input, non-echo, corrupt-store and replay tests |
| TM-030 | A stop command creates an empty store, sends an unreviewed signal, retries stale intent, or reports requested cancellation as an observed outcome | Unintended host action, lost concurrent facts, or false audit state | Closed RunCancellationRequest Schema; existing writable store required; exactly one RunControl CAS fact; lifecycle type derived from a closed target; exact RunSnapshot output; text says no signal and no observed outcome; no conflict retry | Schema/model, missing/corrupt-store, Run/Attempt target, terminal/binding, non-echo and concurrent same-head tests |
| TM-031 | An artifact convenience command follows a caller path into another object, treats a path as a digest, emits caller paths or object bytes as successful output, repairs corruption or claims unrecorded provenance | File disclosure or overwrite, false integrity, misleading lineage | CLI delegates to the dirfd-anchored LocalArtifactStore; digest grammar derives every object key; successful put/verify output is only a closed versioned report; no object-byte stdout, repair, SQLite row, event, delete, upload or provenance claim | Report Schema/semantics, import/verify, success-path omission, symlink/traversal, missing/corrupt object and terminal-escape tests |
| TM-032 | A stale, misspelled or over-broad policy is reused for another plan, or input ordering changes the authorization identity | Wrong-plan execution or excess capability | Policy binds spec/registry/plan digests; unused, unknown, duplicate and malformed grants fail closed; recursive declarations and requirement decisions normalize into a deterministic decision digest | Binding, nested-loop, tamper, ordering, non-echo and side-effect-tripwire tests; signatures, expiry and revocation pending |
| TM-033 | A review report is treated as a launch token, or a manifest expands native-process access after authorization | Host code execution, data exposure or false audit state | Preflight recomputes authorization, binds spec/registry/plan/decision digests, requires one exact sealed-registry Python task and a closed capability/permission/runtime profile; report literals say launch false, isolation unenforced, execution absent and all side effects zero | Schema/model/core/CLI binding, profile, tamper, non-echo and process/import/signal/network/persistence tripwires; actual executor remains blocked |
| TM-034 | An unauthenticated caller records a stale or negative decision, a corrupt history is extended, or a durable audit event is mistaken for launch authority | False approval lineage, concealed corruption or unauthorized execution | Closed event request binds project/revision/workflow and four digests; recorder recomputes the decision, verifies the full existing store and CAS-appends one fixed event; payload says unauthenticated, audit-only and not-executed; all dispositions remain explicit | Schema/model/core/CLI binding, corrupt-store, duplicate identity, negative decision, replay, non-echo and concurrent-append tests; authenticated runtime consumption remains blocked |
| TM-035 | A lineage reconstruction is treated as the authorization a Run used, a latest-authorized match is selected as a credential, or a corrupt authorization event is skipped | False execution authority or concealed invalid audit history | Closed query binds project/revision/workflow and plan identity; optional decision digest is exact tagged identity; reconstruction is read-only over a frozen verified prefix; invalid authorization events fail closed; report lists every match in sequence order and does not choose one; literals say unauthenticated, audit-only, not-executed and not-consumed; the query does not write RunSnapshot | Schema/model/core/CLI match, miss, mixed-type skip, digest-tag mismatch, empty-store, corrupt-auth-event, non-echo and side-effect-tripwire tests; event citation and runtime consumption remain blocked |
| TM-036 | A RunSnapshot `decisionDigest` is treated as a recorded audit event, a launch token, or a silently omitted/nullable identity | False execution authority or broken replay | SimulatedRuntime writes the in-process gate digest on `run.queued`; the reducer copies it immutably; JSON null is rejected; omit remains legal on ungated traces; resume requires an exact match with the recomputed gate; no authorization event is read | Schema/model/reducer/runtime/CLI tests for omit, copy, replay equality, null reject, mismatch fail-closed and source tripwires; signatures, event refs and runtime consumption remain blocked |
| TM-037 | The AI→researcher question channel (ADR-0039 D3) is used to elicit secrets, private data or out-of-scope information, or to route information requests around it | Credential/private-data exposure; scope creep of what the system learns about the researcher | Planned (M1-1): `question.asked` is the only sanctioned request path; `whyNotObservable` is required; answers pass typed `SecretRef`/redaction (TM-007, TM-022) and carry `14-RB` rights with research-read default; questions are facts the dissent reviewer can object to | Not implemented. Corpus tests in Issue #42 required before any live model may ask a question |
| TM-038 | Leading, repeated or sycophantic questions steer the researcher's decision through the help channel; excessive questioning exhausts human attention | Governance capture; false consensus; north-star metric degraded | Every `decision.recorded` carries a non-empty rationale; overridden dissents stay in the ledger (ADR-0005 / ADR-0039 D2); the ledger counts decisions, rationale length, and (from #42) questions so attention cost is visible; mock-provider capability-refusal tests in M1-2; adversarial evidence corpus in M1-3 | Rationale and dissent-survival tests in M1-1. Question counters stay 0 until #42. Metric vs outcome is M1-5 |
| TM-039 | Human answers and rationales are used as training data without consent, or one user's biases are written into weights | Rights violation; single-user bias capture (Issue #26); irreversible drift | Planned: training eligibility requires rights allowing `training` and an explicit human decision approving that use; per-user adapters and content-addressed checkpoints as rollback; nothing enters weights by default (ADR-0039 D5) | Blocker before any parameter-update slice; that slice needs its own ADR and review |
| TM-040 | A model adapter silently simulates a missing capability (tools, JSON schema, vision) or stores prompt/output text in `ai.call.*` events | False scientific capability; prompt/secret leakage (TM-007, TM-022) | `ModelProvider` records declared/measured/allowed sets; a requested name absent from `allowed` fails closed with no events; `ai.call` payloads denylist prompt/output keys and store `jcs-sha256` digests (optional artifact refs); the mock has no network path; the HTTP adapter allows only `generate` and rejects redirects | Capability-refusal and digest-only tests in M1-2/M1-4 |
| TM-041 | A compressed or pathological PDF exhausts CPU or memory during evidence import | Local denial of service; importer hang | PDF extract runs in a subprocess with wall-clock, CPU, and best-effort address-space limits; page count and extracted-character caps abort incrementally; fail closed without echoing text or paths (TM-022) | FlateDecode text-bomb, page-limit, timeout, and non-echo tests in M1-3 |

## 7. M0 security gates

Before merging executable capability, the following gates apply:

- **Protocol gate:** valid/invalid examples and generated schema stay synchronized.
- **Revision gate:** a running revision cannot be mutated; revision transitions receive semantic diffs.
- **Authorization gate:** only an exact three-digest `authorized` decision may enter a supported execution path; `ready`, `pending` and `denied` are non-executable, and a native preflight report is review data rather than a supported execution path.
- **State gate:** success, failure, cancelled, lost and unknown have separate tested meanings.
- **Secret gate:** typed secret references and redaction tests exist before any API credential is used.
- **Execution gate:** no arbitrary process, plugin or expression execution is added without a new threat-model review.
- **Help-channel gate (ADR-0039, M1):** no AI component requests information from the researcher outside `question.asked`; no `decision.recorded` without a rationale; answers and rationales are data with rights, never instructions or default training input.
- **Supply-chain gate:** dependencies are locked; third-party CI actions are commit-pinned; CI token is read-only unless a job proves it needs more.

## 8. Explicitly accepted residual risk

- M0 kernel-proof executable and protocol gates in this document are closed
  (ADR-0037). Remaining planned mitigations, authenticated authorization, Workers,
  native execution and public-network defense are M1 or later. Closure does not
  retire the residual risks below.
- M0 is local pre-release software and does not yet defend a public network service.
- Plan authorization is not authenticated, signed, expiring or revocable. The optional event
  recorder makes a recomputed evaluation durable and replayable, but its actor remains
  caller-asserted and the event is audit-only rather than an approval receipt. The optional
  lineage query reconstructs a candidate set of those facts for one plan identity; it does
  not cite the fact a Run used and is not consumed by any runtime. SimulatedRuntime records
  the in-process gate `decisionDigest` on `run.queued` / `RunSnapshot`; that field identifies
  the evaluation the Run passed, not an audit-event citation or launch permission. Only the
  canonical zero-side-effect simulated runtime consumes the in-process gate for an executable
  path in M0; native preflight only produces a report that forbids launch.
- Native-process preflight does not bind an interpreter, enforce its requested workspace/network/
  environment/limit constraints, create or supervise a child, or persist a receipt. Its digest is
  neither a credential nor evidence that an operating-system control was applied.
- Cancellation-request `actor.id` is claimed metadata, not authentication; local OS access to
  the request and database is the current authority boundary.
- `config` and `extensions` are structurally declared but their future consumers must perform capability-specific validation.
- M1-0 has a typed `SecretRef` and redaction helper. Users must still not place
  credentials in ResearchSpec or manifests. Resolvers do not call remote APIs.
- Rights metadata can be wrong or incomplete; the validator enforces declared policy but is not a legal authority.
- Cost caps in this slice are protocol declarations, not runtime enforcement.
- JSON Schema consumers still need the normative semantic tests for cross-object references and acyclicity.
- Semantic JSON digests are RFC 8785 JCS SHA-256 tagged `jcs-sha256:`, with a
  committed Python + Node golden corpus. They are not signatures, authenticators
  or a defense against a malicious host. Input MUST satisfy the I-JSON profile;
  high-precision integers and amounts MUST be JSON strings. Legacy `sha256:`
  semantic identifiers may be parsed for compatibility but are not an algorithm
  upgrade and MUST fail closed against a recomputed `jcs-sha256:` digest.
  SQLite schema v1 event rows and raw artifact bytes remain separate `sha256:`
  preimages.
- A host administrator can disable SQLite triggers, rewrite the file and recompute unkeyed
  digests. M0 has no signature, external anchor or deletion-proof hash chain.
- Local artifact SHA-256 likewise detects accidental truncation or bit-rot, but cannot resist a
  host administrator who replaces object bytes and updates the digest in lockstep. Dirfd anchoring
  stops intermediate symlink escape and root-path substitution; it does not stop a privileged
  writer who can mutate the already-opened inode. Artifact rows, media types and deletion/GC remain
  unimplemented, so the CLI report is not durable metadata and there is still no GC or
  tombstone independent of the file tree. Event-cited digests are indexed in SQLite
  `artifacts` / `artifact_links` (ADR-0041); those rows are not the object bytes.
- ResearchEvent payload size/depth limits remain open; the local store does not yet add a
  separate operational byte/depth cap.
- YAML node and depth budgets are enforced after alias-free composition. The 8 MiB source
  cap bounds input size, but transient parser memory is still a residual risk until
  composer-phase budgets or process isolation are implemented for a public service.
- PDF extraction isolates pypdf in a subprocess with page, character, and wall-clock
  caps. `RLIMIT_AS` is best-effort and often unenforced on macOS; the wall-clock
  timeout is the portable bound. This is not a public-service parser sandbox.

These risks must not be described as solved until their corresponding executable gates pass.
