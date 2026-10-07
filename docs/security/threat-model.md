# Living Threat Model

> Status: Active M0 baseline; kernel-proof closed 2026-09-03 ([ADR-0037](../adr/0037-m0-kernel-proof-closure.md))
>
> Last reviewed: 2026-09-23
>
> Scope: protocol validation, deterministic planning and plan authorization, audit-only authorization events, read-only authorization lineage reconstruction, in-process RunSnapshot decisionDigest, SimulatedRuntime consume of one local `{eventId, sequence}` citation of `plan.authorization.evaluated` (not a signed launch JWT), non-executing native-process preflight, local event persistence, local artifact objects and their explicit CLI, Run/Attempt projection, RunControl, deterministic SimulatedRuntime, its strict local CLI, explicit Run/Attempt cancellation requests, research decision objects and ledger including `question.asked` / `question.answered`, the in-process deterministic ModelProvider mock with digest-only `ai.call.*` facts, local Markdown/PDF evidence import, the in-process OpenAI-compatible HTTP adapter, runtime CNY budget facts, seeded synthetic `training.step` / `evaluation.metric` facts, and static HTML/Markdown Run reports. M2-0 adds a loopback Worker long-poll
binding, HMAC grants bound to an authorized `execute.local` execution object, and a
host-python CAS helper that is not NativeProcessRuntime and not a kernel sandbox.
Isolated processes use pinned loopback HTTPS (ADR-0044). CPU OCIContainerRuntime
is a digest-pinned docker adapter for `execute.oci` (ADR-0045) and is not a GPU
or Darwin kernel-namespace proof. Worker stop/fault recovery (ADR-0046) keeps
cancel requests distinct from observed stop, refuses success without
`work.completed`, and does not auto-rerun unknown work. EventStore 10k/100k
folds and CAS metric chunks (ADR-0047) keep heartbeats and per-step series
off the fact log; bench receipts are not SLA. The pinned ms-swift adapter
(ADR-0048) parses one SFT plan to argv and does not execute GPU work.
Non-root `/in` bind modes and designated Linux OCI CI are ADR-0049.
Observed execution identity and cancel supervision are ADR-0050: a cancel
request is still not a stop; `cancel-observed` requires a confirmed
process or container exit; container stop is not cloud-instance stop.
Live CPU fault acceptance is ADR-0051.
Remote Worker transport (ADR-0021) is a pending-live pack: loopback is not
a two-host proof; the Worker directory must not contain `tls-key.pem`. M3
slice 1 adds a local restricted native helper over a sealed preflight with
this-store authorization consume (ADR-0063, TM-064): fixed noop argv only,
process-group supervision, bounded capture, no entrypoint import, no
lifecycle append, and SSH transport refused without a socket. Native SSH
onboarding is a pending-live checklist pack only (TM-065). R03 adds a
non-launching reviewed-native contract for `execute.native` (ADR-0065, TM-066):
validation reports keep `launchAllowed` false, and no executor honors that
capability. R04 materializes reviewed bytes into a private workspace and
diagnoses it (TM-067). Preparation still does not import an entrypoint,
install a package, consume a grant, or start user code.

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
HTTP requires a SecretRef, HTTPS, `read.external_api`, and a positive CNY cap
and reserve. It can append seeded synthetic `training.step` / `evaluation.metric`
facts on a success simulation when the request supplies those identities, and it
can rebuild a static HTML/Markdown Run report from EventStore. It does
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
| NativeProcessRuntime slice 1 | Local restricted helper over a sealed preflight | Implemented (ADR-0063, TM-064); recomputed preflight plus this-store human `{eventId, sequence}` consume before spawn; fixed noop argv, empty env allowlist, isolated temp cwd, bounded capture, process-group reap; entrypoint never imported; SSH refused without a socket; no lifecycle/grant/artifact writes |
| Native SSH onboarding | Pending-live pack plus explicit doctor candidate | Pack writer remains offline; doctor uses pinned OpenSSH host key, dedicated private identity, fixed remote code and bounded stdin, offline user-owned install, authenticated HTTPS Worker identity (TM-065); no authorized cross-host proof yet |
| Reviewed native execution contract | Validation-only `native-reviewed-python/v0alpha1` | Implemented as a non-launching validator (ADR-0065, TM-066). `execute.native` is registered and is not an alias for `execute.local` or `process.native`. No executor honors it. `launchAllowed` is false. Network, filesystem, and memory isolation are not enforced. No grant is consumed and no entrypoint is imported |
| Reviewed native preparation | Digest-bound workspace for one reviewed Python task | Implemented as prepare/doctor only (ADR-0065, TM-067). Rebuilds the authorization fact, HMAC grant, and CAS bytes. Refuses a mismatched, incomplete, or damaged workspace without repairing it. Does not install packages, import entrypoints, spawn, consume grants, or append lifecycle facts. `launchAllowed` is false |
| AI/model providers | Untrusted proposals and content | Deterministic mock and in-process OpenAI-compatible HTTP; loopback default; remote requires SecretRef + https + `read.external_api` + recorded CNY limit; DNS pin before socket (TM-042) |
| Evidence connectors | Untrusted content and metadata | Local Markdown/PDF import only; no network connectors |
| Plugins/custom code | Arbitrary-code risk | Not executed in M0 |
| Local/remote Workers | Partially trusted execution nodes | M2-0 loopback long poll + HMAC grants bound to `execute.local` + CPU helper without kernel isolation (ADR-0043, TM-043); isolated processes use pinned loopback HTTPS and a private CAS (ADR-0044, TM-044) and are not a cross-machine proof; CPU OCIContainerRuntime is docker + digest pin + `execute.oci` (ADR-0045, TM-045) and is not a live GPU or Darwin-namespace proof; cancel request ≠ stop, unknown cannot auto-succeed, CAS without `work.completed` is not success (ADR-0046, TM-046); EventStore claim/report folds skip heartbeat volume and metric series live in CAS (ADR-0047, TM-047); non-loopback remains ADR-0021 |
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
- NativeProcessRuntime slice 1 cannot execute the manifest entrypoint, enforce network denial, pin the interpreter, append lifecycle facts, or dial SSH; SSH transport is refused after authorization checks.

ResearchSpec, exact block resolution, pure planning, exact plan authorization, append-only
event-store, local artifact object and RunControl preflight/CAS invariants have executable checks.
Authenticated/persistent approval, SQLite artifact indexing, secret, budget-consumption,
persistent projection and real-runtime invariants remain requirements for subsequent slices.

## 6. Threat register

| ID | Threat | Impact | Current mitigation | Required verification/status |
|---|---|---|---|---|
| TM-001 | Hidden or misspelled fields change intended behavior | Policy or experiment bypass | Strict Pydantic models with `extra=forbid`; declared `config`/`extensions` only | Tested in M0 |
| TM-002 | Arbitrary workflow cycles create infinite execution | Denial of service and uncontrolled cost | Each graph must be acyclic; explicit `LoopBlock` only | Tested in M0 |
| TM-003 | Paid/GPU loop omits termination limits | Budget loss | Iteration count plus cost and wall-time caps for risky capabilities; HTTP generate enforces CNY via a human `budget.limit.recorded` fact plus atomic `budget.reserved` / `budget.exceeded` on one frozen head; request `budgetCap` cannot raise that limit; uncertain transport after dispatch keeps the reservation | Spec caps tested in M0; HTTP generate cap and limit tests in M1-4; GPU-loop runtime still planned |
| TM-004 | Unknown-rights material enters training data | Legal, ethical and publication harm | Rights and allowed use are separate; unknown denies training/redistribution | Tested in M0; provenance propagation planned |
| TM-005 | Broken entity or edge reference resolves unpredictably | Wrong experiment or result attribution | Global entity IDs, scoped node IDs and references are validated | Tested in M0 |
| TM-006 | Prompt injection in papers, notes or repositories controls the assistant | Unauthorized tool use or exfiltration | Evidence is data, not instruction; `evidence.imported` stores digests not bodies; `DeterministicMockProvider` still refuses disallowed capabilities after an adversarial note is imported; the HTTP adapter's allowed set is `generate` only | Adversarial Markdown corpus in M1-3; HTTP adapter refuses `tools` before any request (M1-4) |
| TM-007 | Secret appears in spec, log, event, model prompt or artifact | Credential and private-data exposure | Typed `SecretRef`; redaction of secret-bearing keys and known values; `env` resolver never puts the value in errors. Remote HTTP generate requires SecretRef + https; loopback forbids SecretRef. Inline secrets in specs still forbidden. File/keyring backends pending | Type, redaction, and remote-gate tests; secret value must not appear on events or problem reports |
| TM-008 | Malicious plugin escapes or receives excess capability | Host or data compromise | Planned tiered process/container isolation and capability manifests | Blocker before community plugins |
| TM-009 | Worker spoofing, replay or stale lease executes a task twice | Cost, corruption or data exposure | Loopback long-poll with HMAC worker session and `rg1` grant token bound to project, worker, grant, task, run, attempt, nonce, image, config, and expiry; short leases; nonce consume; idempotent claim/complete; `resumed` poll does not spawn; expired/revoked new results fail-closed; matching terminal results stay idempotent; unspecified bind refused; HTTP remains loopback-only | Tested in M2-0 (`tests/test_worker_protocol.py`, `tests/test_worker_faults.py`). TLS unicast bind + pending-live pack is ADR-0021 |
| TM-010 | Artifact is replaced after validation | Poisoned model/data or false reproducibility | Content-addressed local objects; root `st_dev`/`st_ino` identity; dirfd walk of `tmp`/`objects`/`sha256`/shard with `O_NOFOLLOW`; digest-derived basenames; atomic `link` plus directory fsync; existing mismatch fails closed and is not overwritten | File object layer tested, including intermediate symlink escape, root substitution and fsync-retry recovery; SHA-256 detects accidental corruption, not a host admin who rewrites files and recomputes the digest |
| TM-011 | Event history is edited or a projection is treated as fact | False audit and recovery state | SQLite facts reject UPDATE/DELETE/REPLACE; reads verify canonical JSON, digest and indexes; query/replay CLI and in-memory folds are rebuildable consumers; `run_projections` / spec and artifact indexes rebuild from `events` and are not used as fold starts; high-water checkpoint is revalidated against live sequence, last digest and schema before reuse; a missing checkpoint row is an invalid cache, not altered DDL | Event source, replay fold, RunControl, missing/tampered checkpoint tests and query-table rebuild tested |
| TM-012 | AI or user bypasses approval via a low-level adapter | Governance and budget bypass | Pure trusted-kernel gate revalidates ready reports, binds all three digests and evaluates exact capabilities, permissions and requirements; SimulatedRuntime invokes it before writes and then consumes the cited local `{eventId, sequence}` fact; Worker grants MUST cite an authorized evaluation and the plan's execution object (`execute.local` or `execute.oci`); a `simulate` authorization cannot launch a brick | Gate, T0 integration, local consume, and Worker grant/revoke/binding tests; JWT launch credentials remain out of scope |
| TM-013 | Failure, timeout or disconnection is reported as success | Invalid scientific conclusion | Explicit unknown/lost states; RunControl rejects illegal lifecycle jumps before write; SimulatedRuntime stops on `attempt.unknown` and never degrades unknown to failure or success; Worker sandbox wall-clock timeout or signal-killed process is `UNKNOWN`, not `failed`; disconnect before complete leaves the lease open; complete-fact write interrupt retries complete and does not re-run or invent success | Run/Attempt reducer, RunControl, SimulatedRuntime, and M2-0 sandbox timeout / kill / disconnect / resume tests |
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
| TM-034 | An unauthenticated caller records a stale or negative decision, a corrupt history is extended, or a durable audit event is mistaken for launch authority | False approval lineage, concealed corruption or unauthorized execution | Closed event request binds project/revision/workflow and four digests; recorder recomputes the decision, verifies the full existing store and CAS-appends one fixed event; payload says unauthenticated, audit-only and not-executed; SimulatedRuntime consume requires this-store sequence match, human actor, authorized=true and four-digest binding | Schema/model/core/CLI binding, corrupt-store, duplicate identity, negative decision, replay, non-echo, concurrent-append and consume fail-closed tests; signatures, expiry and revocation remain blocked |
| TM-035 | A lineage reconstruction is treated as the authorization a Run used, a latest-authorized match is selected as a credential, or a corrupt authorization event is skipped | False execution authority or concealed invalid audit history | Closed query binds project/revision/workflow and plan identity; optional decision digest is exact tagged identity; reconstruction is read-only over a frozen verified prefix; invalid authorization events fail closed; report lists every match in sequence order and does not choose one; literals say unauthenticated, audit-only, not-executed and not-consumed; the query does not write RunSnapshot | Schema/model/core/CLI match, miss, mixed-type skip, digest-tag mismatch, empty-store, corrupt-auth-event, non-echo and side-effect-tripwire tests; lineage stays not-consumed; the Run citation is SimulatedRuntime `{eventId, sequence}` consume (ADR-0042), not this query |
| TM-036 | A RunSnapshot `decisionDigest` is treated as a recorded audit event, a launch token, or a silently omitted/nullable identity | False execution authority or broken replay | SimulatedRuntime writes the in-process gate digest on `run.queued`; the reducer copies it immutably; JSON null is rejected; omit remains legal on ungated traces; resume requires an exact match with the recomputed gate; SimulatedRuntime also requires a matching local `{eventId, sequence}` citation (ADR-0042). The digest is not that citation | Schema/model/reducer/runtime/CLI tests for omit, copy, replay equality, null reject, mismatch fail-closed and source tripwires; signatures remain blocked |
| TM-037 | The AI→researcher question channel (ADR-0039 D3) is used to elicit secrets, private data or out-of-scope information, or to route information requests around it | Credential/private-data exposure; scope creep of what the system learns about the researcher | `question.asked` is the only sanctioned request path; `whyNotObservable` is required; answers carry `14-RB` rights with research-read default; `unknown` cannot list `training` / `redistribution`; error output does not echo question or answer text (TM-022); actor kinds fail closed | Implemented. Corpus in `examples/research-decisions/` and tests in `tests/test_research_ledger.py` / `tests/test_research_decision_requests.py`. No live model may ask until those tests pass |
| TM-038 | Leading, repeated or sycophantic questions steer the researcher's decision through the help channel; excessive questioning exhausts human attention | Governance capture; false consensus; north-star metric degraded | Every `decision.recorded` carries a non-empty rationale; overridden dissents stay in the ledger (ADR-0005 / ADR-0039 D2); the ledger counts decisions, rationale length, open and answered questions so attention cost is visible on `researchos report`; mock-provider capability-refusal tests in M1-2; adversarial evidence corpus in M1-3 | Rationale and dissent-survival tests in M1-1. Question counters and report attention line land with #42. Metric vs outcome is M1-5 |
| TM-039 | Human answers and rationales are used as training data without consent, or one user's biases are written into weights | Rights violation; single-user bias capture (Issue #26); irreversible drift | Planned: training eligibility requires rights allowing `training` and an explicit human decision approving that use; per-user adapters and content-addressed checkpoints as rollback; nothing enters weights by default (ADR-0039 D5) | Blocker before any parameter-update slice; that slice needs its own ADR and review |
| TM-040 | A model adapter silently simulates a missing capability (tools, JSON schema, vision) or stores prompt/output text in `ai.call.*` events | False scientific capability; prompt/secret leakage (TM-007, TM-022) | `ModelProvider` records declared/measured/allowed sets; a requested name absent from `allowed` fails closed with no events; `ai.call` payloads denylist prompt/output keys and store `jcs-sha256` digests (optional artifact refs); the mock has no network path; the HTTP adapter allows only `generate` and rejects redirects | Capability-refusal and digest-only tests in M1-2/M1-4 |
| TM-041 | A compressed or pathological PDF exhausts CPU or memory during evidence import, or the parser subprocess inherits host secrets | Local denial of service; importer hang; credential exposure (TM-007) | PDF extract runs in a subprocess with wall-clock, CPU, and best-effort address-space limits; page count and extracted-character caps abort incrementally; worker environment is a minimal allowlist (no `PYTHONPATH`, proxy, or inherited API keys); fail closed without echoing text or paths (TM-022) | FlateDecode text-bomb, page-limit, timeout, non-echo, and worker-env sentinel tests in M1-3 |
| TM-042 | A model endpoint hostname is used for SSRF, DNS rebinding, or a private/metadata address, or a zero remote reservation is treated as a free call | Host/network compromise; unmetered paid API use | Literal classification plus one-shot DNS pin; query/fragment/userinfo forbidden; loopback, private, link-local, multicast, reserved, CGNAT, and cloud-metadata addresses fail closed; mixed loopback/public answers are `dns-rebinding`; remote `costKnown=false` requires `budgetCap > 0` and `reserveAmount > 0`; that cap MUST match a recorded `budget.limit.recorded` fact; outstanding remote reservations stay visible on the report, including after uncertain transport | Endpoint, pin, remote-zero-budget, recorded-limit, uncertain-transport, and concurrent reserve tests in M1-4 |
| TM-043 | A swapped brick, config, inputs or runtime runs under an old authorization, or host Python is treated as a kernel sandbox | Unreviewed code execution; false isolation claims | Grant recording rebuilds the cited plan from spec+registry and binds project/revision/workflow/planned task/execution object; `simulate` cannot grant; Worker re-checks before spawn; swapped object fails closed without `Popen`; stdout/stderr limits apply during pipe reads; POSIX process groups are reaped. No seccomp, landlock, or network/filesystem jail is claimed | Binding, script-A-not-B, swapped-brick, cross-task token, output-cap, and child-reap tests in M2-0. Kernel isolation remains out of scope |
| TM-045 | An OCI task runs a tag, extra host mount, open network, or host-python grant, or a missing runtime is reported as a successful container | Unreviewed code execution; false isolation claims | Image identity is `sha256:` only (`--pull=never`); launch shape is network-denied with closed mounts and resource ceilings; `execute.oci` is distinct from `execute.local`; python-sandbox Workers cannot lease OCI work; missing docker engine fails `oci-runtime-missing`; tests do not mock a successful container (ADR-0045) | Policy, binding, runtime-mismatch, and fail-closed prove/CLI tests. Ordinary live docker is skip-if-missing |
| TM-046 | A cancel request is treated as stopped, unknown work is marked success or auto-rerun, or a CAS object without `work.completed` completes the Attempt | False stop/success; duplicate execution | Poll does not open a new lease after a request; resumed poll does not spawn; heartbeat returns `cancelRequested` without appending facts; observed stop is `cancel-observed` then cancelled outcomes; reconcile requires `work.completed` to succeed; unknown stays unknown; CPU checkpoint JSON is inspectable (ADR-0046) | Cancel-request-vs-stop, unknown-not-success, complete-reconcile, restart, and checkpoint tests in `tests/test_worker_recovery.py` |
| TM-047 | Per-step metrics or transport heartbeats fill EventStore, or a static report/claim fold materializes the whole log, or bench timings are treated as a contract | Log blow-up; false SLA; OOM on report | Heartbeats stay off the log; `read_events(event_types=)` is a post-high-water fold filter, not a substitute for contiguous replay; reports keep lineage on the matching Run; series use CAS `MetricChunk` with 1024/32 caps; `m2 bench` receipts are measurements not golden files (ADR-0047) | 10k/100k bench, typed Worker rebuild, metric-chunk cap, and report lineage tests in `tests/test_m2_perf.py` / `tests/test_metric_chunk.py` |
| TM-048 | A training-backend plan is treated as a GPU run, or ms-swift/torch enter the core environment, or deleting the adapter breaks the CPU loop | False training success; core/CUDA coupling | Closed `TrainingBackendPlan` for `ms-swift==4.5.2` only; `training plan` prints argv with `executed: false` / `gpu: not-run` and MUST NOT subprocess; core `project.dependencies` stay free of ms-swift/torch; CPU prove/sandbox must not import `llm_research_os.training` (ADR-0048) | Pinned-plan, reject-unpinned, and core-isolation tests in `tests/test_training_backend.py` |
| TM-049 | An OCI bind uses 0700 `/in` so nobody cannot read the brick, or the container is run as root / 0777 to bypass that, or a skip on designated Linux CI is treated as live OCI acceptance | Unreadable inputs; privilege escalation; false Linux OCI proof | Bind root is 0755 and brick 0444; `--user 65534:65534`; not world-writable; `RESEARCHOS_OCI_REQUIRED=1` converts skip to fail (ADR-0049) | Mode tests, argv user assertion, designated `Linux OCI integration` job |
| TM-050 | A resumed cancel request is reported as observed stop, PID reuse stops another task, `--rm` prevents container inspect, or container stop is treated as cloud VM stop | False cancelled outcome; wrong process killed; GPU billing stop | Resume+cancel without a matching identity stays `execution-unobserved`; Linux starttime rejects PID reuse; host stop waits for exit; OCI uses `--cidfile` without `--rm` then inspect; cloud instance stop is forbidden (ADR-0050) | Identity, pid-reuse, heartbeat-cancel, argv, and cloud-stop tests in `tests/test_worker_supervise.py` |
| TM-051 | `plane.fail("cancel-observed")` is treated as a live stop, unknown work is auto-rerun, a second client spawns while the original executor is alive, or disconnect-after-upload re-executes | False cancelled/success; duplicate execution | Live faults spawn a long-running CPU brick and assert pid/container state; timeout/kill drop a reaped identity; pending complete retries `work.completed`; recovery must not spawn; expire/revoke is not observed stop (ADR-0051) | `tests/test_worker_live_faults.py` |
| TM-052 | A loopback HTTPS test is called a cross-machine Worker, the pack includes `tls-key.pem`, or `0.0.0.0` is bound | False remote proof; private-key exposure; unsolicited bind | Pack STATUS is `pending-live`; loopback URL is `loopback-not-cross-machine`; worker dir copies CA only; unspecified bind fails (ADR-0021) | `tests/test_worker_remote_pack.py`; ADR-0044 isolate tests remain loopback |
| TM-053 | `m2 bench` EventStore fill is treated as Worker/RunControl usage, an isolated Worker shares the control CAS, an OCI skip is treated as a live engine, or ordinary Ubuntu docker without the pinned image fails `m2 usage` | False performance/usage proof; shared state; false OCI acceptance; false unit-test failure | `m2 usage` forbids heartbeat fill; isolated Worker uses a private CAS; report cites spec/runtime/image/config/output; missing engine is `skipped-no-runtime`; missing local digest is `skipped-no-image`; designated Linux CI fails closed (ADR-0052) | `tests/test_m2_usage.py` |
| TM-055 | A failed `/proc` or `ps` probe is treated as process exit, or stop is confirmed from the group leader while a child still runs, or an unverified start token is signaled | False `cancel-observed`; leftover executors; wrong pid killed | Observation is `running` / `exited` / `unknown`; failed probes stay unknown; `observed-stop` requires group `exited`; live pid with unread start token is not signaled (ADR-0054) | Restricted-probe, unverified-token, and orphaned-child tests in `tests/test_worker_supervise.py` |
| TM-056 | Designated OCI CI treats a skip as a live pass, or OCI cancel/timeout/kill is accepted from `plane.fail` / stub inspect without a real container, or inspect failure is reported as `cancel-observed` | False OCI acceptance; leftover containers billed as stopped | `pytest -m oci_live` with `RESEARCHOS_OCI_REQUIRED=1` fails on skip; live faults assert inspect/residual containers/events; inspect failure is `execution-unobserved` (ADR-0055) | `tests/test_worker_oci.py` live brick; `tests/test_worker_oci_live_faults.py` |
| TM-057 | GPU training reuses the CPU OCI profile with lifted ceilings, or an unauthorized device/mount/privileged flag is launched, or `training bind` is treated as a CUDA run | Unreviewed GPU/host escape; false training success | Independent `gpu-oci-container` / `execute.gpu`; closed device `nvidia.com/gpu=0` and mounts; CPU OCI allow-list unchanged; receipts stay `gpu-not-run` (ADR-0056) | `tests/test_worker_gpu.py` |
| TM-058 | Hub ids float without a revision, `/work/output` is tmpfs, `--adapters` is treated as a full resume, or an interrupted CAS put is called a checkpoint success | Silent snapshot retarget; lost weights; false resume; false GPU result | `GpuDataCheckpointBinding` pins the HF model SHA; dataset git SHA is `pending-live` until recorded; overlay declares loads; collect is bounded, symlink-closed, and resumable; receipts stay `gpu-not-run` (ADR-0057) | `tests/test_training_checkpoint.py` |
| TM-059 | A host `swift sft` or `executed: false` plan is called a Worker MPS result, MPS inherits OCI isolation, CPU fallback is labeled `mps`, adapter-only is treated as full resume, or the 1 MiB CAS bound blocks a real LoRA checkpoint | False training success; false isolation; false restore; lost weights | Independent `macos-mps-process` / `execute.mps`; process-group isolation only; probe fail-closed `mps-unavailable`; live environment binds `sitecustomizeDigest`; overlay loads declared and file digests observed; MPS collect 256 MiB / 64 files (ADR-0058) | `tests/test_worker_mps.py` |
| TM-060 | AutoDL 16–24 GiB memory is used on a 6 GiB WSL laptop, `--gpus all` is treated as the authorized launch, a jammy rootfs or image tag is used as grant identity, `execute_gpu_training` is called a CUDA result, ping or Windows-host reachability is called a WSL Worker proof, or this slice is filed as M2 close | Host OOM; extra GPU attach; false image identity; false two-host/CUDA acceptance | Closed `wsl2-cuda-laptop-8g` (3 GiB default); docker `--gpus device=0`; grant identity is local `docker image inspect .Id`; bind stays `gpu-not-run`; live start is `run_gpu_training`; two-host/CUDA rows stay pending-live until recorded from Ubuntu on Windows/WSL2 + Docker Engine (ADR-0059) | Profile/bind/run-split tests in `tests/test_worker_gpu.py`; live evidence is scoped to [cuda.11 and the two-host pack](../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md) |
| TM-061 | Output preparation implicitly elevates authority or follows a symlink/hardlink during host mutation | Host file overwrite or unexpected privileged command | No sudo/setfacl fallback; descriptor-based no-follow traversal, regular-file link-count check before truncate; operator-provisioned ownership for non-root (ADR-0060) | `tests/test_gpu_output_boundary.py`; no new GPU live claim |
| TM-062 | A rounded coverage total passes the floor, or an unknown capability acquires launch authority | Undetected untested paths or capability drift | Integer-count coverage gate; central known capability set; payload catalog drift check | `tests/test_coverage_gate.py`, `tests/test_plan_authorization.py`, `tests/test_event_catalog.py` |
| TM-064 | A stale or foreign authorization launches a native process, an SSH request spawns locally, or the helper is treated as entrypoint execution with network/OCI isolation | Unreviewed code execution; false isolation claims | Sealed preflight recompute plus this-store human `{eventId, sequence}` consume before spawn; `ssh` validated past authorization then refused without a socket; fixed noop argv, empty env allowlist, isolated temp cwd, bounded capture, process-group reap; entrypoint never imported; no lifecycle/grant/artifact writes; receipt says `entrypointExecuted: false`, `not-enforced` network (ADR-0063) | `tests/test_native_process_runtime.py` |
| TM-065 | SSH bootstrap accepts a changed host key, leaks credentials through command lines/events, executes untrusted remote shell input, overwrites unrelated resources, or mistakes a TLS listener for Worker registration | Credential exposure, remote command injection, false two-host proof | Pack writer remains offline; doctor revalidates exact host key and user-owned private identity, disables SSH config/agent and forwarding by default, uses a fixed quoted program and bounded stdin/output/time, verifies wheel digests before an offline private runtime install, and checks authenticated Worker identity with CA pin and hostname validation. An explicit reviewed reverse tunnel binds only one remote loopback port to the local Worker TLS origin; server forwarding policy needs separate review. Pack stays `pending-live`; no second-host proof is claimed (ADR-0063, R07) | `tests/test_native_ssh_onboard.py`, `tests/test_native_ssh_live.py`; authorized-host verification pending-live |
| TM-066 | An R03 validation report, application receipt, audit signature, `execute.local` or `process.native` grant, or the `restricted-v0alpha1` noop is used to import a reviewed entrypoint | Premature or substituted code execution; false isolation | `execute.native` is a distinct registered capability with no executor; the validator is pure and returns `launchAllowed=false`; required network, filesystem, or memory isolation that this profile cannot enforce is refused; negative tests assert no entrypoint import, subprocess, or lifecycle append (ADR-0065) | `tests/test_native_reviewed_execution.py` |
| TM-067 | Reviewed code, config, inputs, or interpreter identity are replaced between approval and launch, a path is accepted as the interpreter, or a mismatched workspace is reused | Unreviewed bytes would run if a later package launched; false environment identity | R04 rebuilds the EventStore fact, HMAC grant, and CAS bytes; materializes a private no-follow workspace; rehashes before return; refuses incomplete, damaged, or mismatched trees without overwrite; interpreter identity is a byte document matched to the host ABI and platform; `check_before_user_code` does not import or spawn; `launchAllowed` stays false and no package is installed (ADR-0065) | `tests/test_native_reviewed_preparation.py` |


### TM-068: Local scoped transfer publication

The R08 local helper must not follow a replaced directory or temporary-file
symlink, publish a short write as complete, or let concurrent journal claims
replace the winning lease. Held no-follow directory descriptors, private
exclusive temporary files, complete-write loops, no-overwrite atomic file
publication, locked journal transactions and file/directory fsync enforce
these boundaries. Bounded regular-file reads refuse FIFOs and oversized
manifests/journals. Regression evidence is in
`tests/test_native_transfer_security.py`.

This helper does not authenticate grants or contact another host. Manifest
grant/task identifiers are trusted local correlation data. Its fault classifier
does not exercise real network/process faults. Journal parents and their stable
lock files are controller-owned; no untrusted actor may delete them. Private
staging crash leftovers require owner cleanup. Remote transport, grant-bound
endpoint enforcement and two-host fault evidence remain R08 implementation
and acceptance gaps for this local helper, not its current security properties.

### TM-069: Grant-scoped native input transport

The additive pinned HTTPS native input endpoint must not expose arbitrary CAS
bytes, accept a different Worker's session, or convert download replay into
execution. It rechecks the signed and recorded grant and planned native object
on every request, denies revocation/cancellation and expired or terminal claimed
leases, and allows only planned bundle/lock/inventory/input digests. Requests,
response reads, sizes and retry counts are bounded. The client verifies the
digest before returning bytes, closes connections, and never retries integrity
or authorization failures. See `tests/test_native_input_transport.py` and
[the protocol](../protocols/native-input-transfer-v0alpha1.md).

This is a trusted controller/Worker transport, not a public multi-tenant service.
Per-request bounds do not add aggregate rate limits or admission control.
Revocation is checked when a request is authorized; bytes already sent cannot
be recalled. Output completion is a separate protocol (TM-070). Remote launch/recovery and
actual two-host fault acceptance remain separate R08 gaps. Legacy artifact APIs
are not the native input protocol.

### TM-070: Native output publication and receipt replay

A native Worker must not upload arbitrary bytes through the legacy endpoint,
complete a foreign/unconsumed lease, publish noncanonical or mismatched results,
or turn a lost acknowledgment into another task start. The pinned HTTPS output
endpoint requires the exact signed/recorded grant, session and queued native
execution binding; it bounds the body before reading, validates the closed
output envelope and byte digest, and verifies CAS before committing a single
Worker completion. A stable controller publication lock serializes output;
post-I/O reauthorization and expected EventStore head prevent a concurrent
revocation or cancellation from bypassing the final append. Changed results
refuse; exact completed replay returns the original fact only if the original
CAS object still verifies, with no repair or new authority. Native HTTP callers
cannot bypass this through generic upload/completion. See
[the output protocol](../protocols/native-output-transfer-v0alpha1.md),
`tests/test_native_output_transport.py`, and `tests/test_native_output_documents.py`.

Residual limits: this trusted Worker report is not proof of process termination,
scientific validity, or a successful Run. The full request digest is rebuilt from the exact source authorization, grant
and queued execution; this remains distinct from actual process/result proof.
A revocation/crash after CAS publication may leave an unreferenced object and
must not be called a completion. Per-request limits are not aggregate admission
control or a public parser sandbox. Directory/lock ownership relies on the
trusted controller host. Remote launch, durable staging/recovery integration,
and actual authorized two-host acceptance remain open.

### TM-071: Bound native request context

A remote Worker must not receive substituted project/Run/Attempt/actor/digest
metadata or treat a downloadable audit request as a launch permit. The additive
pinned HTTPS context endpoint requires a live signed and recorded grant with
exact queued native execution scope. The complete request is reconstructed from
the cited human authorization at its recorded sequence, the grant and immutable
queue, without changing existing configuration digests or creating a second
authority ledger. The client checks the published closed request schema,
canonical bytes, Worker identity and full JCS digest with bounded reads/retries.
Native output compares its citation against this reconstructed full request
before publication/replay. See `tests/test_native_request_transport.py` and
[the context protocol](../protocols/native-request-transfer-v0alpha1.md).

The descriptor is not execution or host feasibility evidence. The source remains
audit-only; live Worker authority is checked separately. No controller database
or HMAC key is copied, no entrypoint imported, no process spawned, no lease
consumed and no lifecycle fact appended by the fetch. Actual material preparation,
closed spec/registry execution verification, remote start/recovery and new
two-host acceptance remain separate integration/evidence obligations.

### TM-072: Remote native material and durable private preparation

A Worker must not turn a metadata index into arbitrary CAS access, a substituted
code/environment workspace, a repaired corrupted artifact or a duplicate task
start after disconnect. The pinned material endpoint reconstructs the recorded
live request/grant and publishes bounded closed metadata. Additional downloads
are limited to the immutable bundle members, bound interpreter/review documents
and canonical execution configuration; host executable bytes and unplanned
objects remain unavailable. Controller reads check size before allocation.

The Worker checks raw and semantic identities, stages only indexed objects in
its own anchored CAS/private roots, reuses persistent bounded transfer journals
and refuses corruption or symlink paths without repair. Opaque staging paths
retain the legacy path grammar. Actual host executable/ABI/platform and installed
dependency bytes are verified using R04; the code-member set must exactly match
the downloaded bundle. Required unsupported isolation and remote checkpoint
restores refuse. A second live metadata fetch after staging/host checks prevents
cached materials from bypassing intervening revocation or changed scope.

Per-workspace locks and private candidate publication prevent partially written
workspaces from appearing ready. Existing mismatched workspaces are not replaced.
Interrupted journals/candidates are preparation state, never launch or success.
Tests: `tests/test_native_material_preparation.py` and shared metadata transport
refusal/retry tests in `tests/test_native_request_transport.py`. Protocol:
[remote material preparation](../protocols/native-material-preparation-v0alpha1.md).

Residual scope: private parent ownership is required; same-UID malicious code
is not sandboxed. Owner-managed orphan candidates may consume disk after crashes.
Preparation receipts keep launchAllowed false, zero imports/spawns/facts/grant
consumption/installations, and no controller database/HMAC/private TLS key copy.
Authority may be revoked after preparation, so launch must separately validate
and consume it. Remote executor/recovery, source spec/registry verification and
new authorized two-host/GPU acceptance remain open.

### TM-073: Controller-bound remote native claims

A Worker must not consume a native grant from a citation-only dispatch, inject a
spec/registry through HTTP, take over an existing Run, or treat a persisted
partial lease/lost response as fresh launch permission. Native polling requires
TLS and trusted controller-owned spec/registry inputs. The actual kernel plan
and execution object are rebuilt before any lifecycle/consumption facts.
Strict bounded poll bodies refuse extra scope, encodings and ambiguous headers.
The loopback/SSH-forwarded TLS boundary is unchanged.

The existing private output publication lock serializes native claims across
controllers. RunControl appends one bound Run and queued Attempt with CAS;
matching partial prefixes replay without duplicate facts, and recorded data is
checked rather than trusting event IDs. Live scope is rechecked after journal
I/O. Existing leases always return resumed, including partially claimed leases;
unknown Attempts without a lease and terminal Runs refuse fresh dispatch.
Tests: `tests/test_native_remote_claim.py` (real TLS, plan/registry drift,
missing context, partial Run/Worker facts, lost claim responses, restart,
revocation/cancellation, lock contention and closed-wire refusals).

Residual scope: this is a claim boundary, not a remote launcher or process
observer. Run.started means dispatch lifecycle, while Attempt stays queued.
Worker completion receipts do not independently establish Run success or an
observed stop. Future launch must persist Worker-local intent/identity and reject
resumed claims; process recovery and new two-host/GPU evidence remain open.
Trusted controller inputs/host, same-UID filesystem access and private lock
parents retain their existing trust limits. No controller key/database copying.

### TM-074: Finite optional Ray Jobs resource bridge

Ray exposes powerful code execution, and an idempotent-looking submission ID
alone cannot survive cluster history loss safely. The finite adapter accepts only
literal loopback endpoints with an explicit Ray token and pinned Ray/API version.
It emits only repository-fixed CPU/CUDA diagnostics with no arbitrary task,
package installation or runtime environment. Bounded single-attempt HTTP and
exact command/metadata/environment/result binding reject substituted observations.
The token is not saved or printed. It is not the controller HMAC or a native grant.

A private held directory descriptor, owner-only no-follow regular single-link
state, nonblocking lock, exclusive intent and file/directory synchronization
precede submission. Reconnect queries only the persisted ID; missing history,
refused/ambiguous POSTs and damaged state never start another probe. Stop is an
asynchronous vendor request, not an observed process-group stop or Run transition.
No PID is copied into the controller identity store. Test:
`tests/test_ray_probe.py`; actual CPU gate: `Linux Ray Jobs resource integration`.

Residual scope: trusted compute host/Ray service and same-UID access remain trust
boundaries. Ray scheduling is not network/filesystem/memory isolation. The owned
example bootstrap has a parent startup deadline and never stops unrelated Ray
clusters. Diagnostics append zero project facts and consume no native grants.
CUDA/Kaggle compatibility and full task/grant/identity/result/recovery integration
remain open. Fixtures and vendor success cannot close R08 or Checkpoint B.

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
  not cite the fact a Run used and stays `not-consumed`. SimulatedRuntime records
  the in-process gate `decisionDigest` on `run.queued` / `RunSnapshot` and, from M1-6,
  consumes one local `{eventId, sequence}` citation of the audit fact on *this* EventStore
  (human actor, sequence match, four-digest binding). That consume is not a signed remote
  credential or launch JWT. Only the canonical zero-side-effect simulated runtime consumes
  the in-process gate plus that local citation for an executable path; native preflight only
  produces a report that forbids launch.
- Native-process preflight does not bind an interpreter, enforce its requested workspace/network/
  environment/limit constraints, create or supervise a child, or persist a receipt. Its digest is
  neither a credential nor evidence that an operating-system control was applied.
- M3 slice 1 native execution runs only a fixed noop helper after sealed
  preflight plus this-store consume. It does not import the manifest
  entrypoint, enforce network denial, pin the interpreter, append lifecycle
  facts, or dial SSH. The receipt is digest-only and `entrypointExecuted` is
  always false. SSH onboarding writes a `pending-live` checklist pack and
  never opens a socket; `ssh-transport-not-implemented` is not a live run.
- Cancellation-request `actor.id` is claimed metadata, not authentication; local OS access to
  the request and database is the current authority boundary.
- `config` and `extensions` are structurally declared but their future consumers must perform capability-specific validation.
- M1-0 has a typed `SecretRef` and redaction helper. Users must still not place
  credentials in ResearchSpec or manifests. Resolvers do not call remote APIs.
- Rights metadata can be wrong or incomplete; the validator enforces declared policy but is not a legal authority.
- Cost caps in ResearchSpec remain protocol declarations for GPU/paid loops.
  HTTP generate enforces CNY via `budget.*` facts; remote cost is still unknown,
  so outstanding reservations continue to hold the cap.
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
- M2-0 host-python execution is a local helper with pipe byte limits and process-group
  reaping. It does not enforce kernel network or filesystem isolation and is not a
  general-purpose sandbox for arbitrary code (TM-043).
- CPU OCIContainerRuntime (ADR-0045) uses docker `--pull=never` and a closed
  launch shape. Docker Desktop on macOS is a Linux VM, not a Darwin namespace
  jail. A missing engine is fail-closed, not a simulated success. This is not
  paid GPU isolation.
- WSL2 CUDA (ADR-0059) may start docker only via `run_gpu_training` after
  grant. Plan/bind stay `gpu-not-run`. Unit tests without that host are not
  a CUDA or two-host proof. Image identity is the local docker Id, not a
  tag and not a Canonical jammy rootfs digest.
- Worker stop/fault recovery (ADR-0046) does not send a process signal from
  `runs cancel`. Observed stop is a later Worker fail or complete. A control
  plane that records `work.completed` still needs reconcile (or `m2 prove`)
  to append Run/Attempt outcomes when event identities are caller-owned.
- EventStore 10k/100k measurements (ADR-0047) are host timings, not
  availability or latency contracts. Metric chunks are CAS JSON, not a
  second fact source. Typed `read_events` filters may skip sequences and
  must not replace contiguous replay.
- The ms-swift adapter (ADR-0048) is parse/plan only. `backendInstalled`
  is not execution. The GPU experiment sheet is not a paid-run approval.
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
  A minimal worker environment is not a seccomp or container boundary.

These risks must not be described as solved until their corresponding executable gates pass.

## TM-063: Detached authorization attestation boundary

A portable signature must not turn an old audit fact into a launch permit, trust
an embedded public key, or be replayed in another project/audience. ADR-0061 binds
all claims using domain-separated Ed25519 over RFC 8785 bytes. A verified source
fact, caller-pinned key/scope, bounded validity and explicit revocation snapshot
are required. CLI key I/O is bounded, no-follow, exclusive on create, and owner-only
for private keys. Tests: `tests/test_authorization_signatures.py`.

Residual limits: operator-supplied revocations have no online freshness guarantee;
a malicious host or compromised signing key remains trusted-host risk. A signature
attests bytes and key possession, not the original human actor's authentication.
Historical audit flags and Worker HMAC lifecycle are unchanged. Native execution
remains a separate reviewed boundary.

### TM-075: Remote native start recording is not process observation

A remote Worker could swap preparation/identity or replay a start response as a
fresh launch permit. Closed documents bind the claimed consumed lease, complete
preparation and Worker-local identity digest. The controller rechecks actual
kernel plan binding, all preparation material citations, exact remote Run prefix,
live lease/grant and cancellation before recording and before acknowledgement.
No remote PID or host path is accepted as controller-local identity.

A held directory and nonblocking cross-controller lock anchor owner-only,
no-follow regular single-link bounded immutable journals; file/directory fsync
precede the single exact `attempt.started` fact. Interrupted prefixes complete
only the same recording. Missing/corrupt journals, changed identities, unknown
or terminal attempts refuse. Pinned TLS and bounded identical-body replay cannot
invoke another claim or process. Test: `tests/test_native_remote_start.py`.

Residual trust: an authenticated Worker's identity digest/preparation report does
not prove remote OS observation. A future executor still needs its reviewed
workspace, durable local identity, fixed pre-import child barrier, no-redispatch
rule and observed stop. This endpoint starts zero processes; its receipt has
literal `launchAllowed: false`. It cannot establish Ray task execution, GPU
usability, process cancellation or two-host/Checkpoint B acceptance.

### TM-076: Bound remote native executor and outcome replay

An authenticated Worker could swap its task/environment/identity, repeat a lost
claim, publish unverified completion, or confuse cancellation with signal/HTTP
acknowledgement. The fixed runner uses private independently verified material,
durable immutable launch intent before a single fresh poll, local start-token
identity, reviewed interpreter bytes and a pre-import stdin barrier. Only the
same created child is released after the bound controller start acknowledgement
and material/live-authority rechecks. Required unsupported isolation refuses.
Wall/stream limits remain active independently of stalled heartbeat I/O.

Recovery never prepares, polls or launches; it verifies original bound state,
observes the saved group, and replays only durable results. Missing or unsafe
state, PID reuse, unavailable observation and transport ambiguity cannot grant
rerun or terminal stop. Cancellation settles only after verified group stop.
Controller reconciliation requires the consumed binding, exact original start
journal/prefix, distinct phase journal and corresponding verified Work facts;
completion rechecks bounded CAS bytes and result digest. Terminal facts and
receipts are exact idempotent replay; receipts are not launch credentials.
Pinned TLS and closed bounded outcome documents carry no remote PID/host path.
Tests: `tests/test_native_remote_outcome.py`, `tests/test_native_remote_executor.py`;
the designated Linux native remote execution gate fails if real observation is
unavailable, rather than accepting a mocked observer or skipped task.

Residual trust: the authenticated Worker reports remote OS observations; the
controller cannot independently prove them. This is the existing trusted-host
reviewed profile, not protection from a malicious administrator, a sandbox,
GPU execution, Ray project-job hosting or two-host/Checkpoint B acceptance.

### TM-077: Native Worker CLI reuses the reviewed boundary

Command composition could silently enable native dispatch, leak credentials
through argv/parser errors, or turn a recovery command into a fresh task.
Controller startup requires explicit paired spec/registry and matching project
before state/listener creation; the existing kernel-bound endpoints still
validate dispatch/start. Worker credentials are bounded private no-follow,
regular single-link files anchored to an owner-only parent. Existing credential
and CA-pin validation is reused without changing legacy semantics. Execution
calls only the fixed reviewed service; observation requires the original closed
bounded request and calls only the existing no-redispatch recovery service.

Stdout uses the existing closed non-launch outcome receipt; parser diagnostics
are sanitized ProblemReport on stderr. Unknown prefixes retain intent and cannot
be converted to success, stop or launch authority by an exit code. Controller
DB/HMAC/private TLS state is neither an argument nor a copied Worker resource.
Tests: `tests/test_native_worker_cli.py`, existing isolated Worker regressions;
the designated native gate requires real separate CLI CPU execution and saved
receipt replay. Residual trust/profile, Ray/GPU and two-host evidence limits
remain those of TM-076; no new launch grant, sandbox or acceptance is introduced.


### TM-078: Ray scheduling cannot invent native authority or outcomes

A vendor retry, forged job status, driver death or uploaded environment could
create duplicate work, expose credentials, or claim success/stop without native
proof. The optional Ray CPU adapter accepts only a fixed installed isolated
Python module and original reviewed request/private paths. Pinned authenticated
loopback Jobs API, empty runtime environment and CPU=1/GPU=0 are explicit vendor
bounds; they are scheduling hints, not an isolation mechanism or GPU capability.
No controller DB, HMAC/private TLS key, Worker grant/session bytes or package
archive is passed to Ray metadata, argv, logs or runtime_env.

Owner-only locked state, bounded 0600 no-follow regular single-link intent and
exclusive fsync precede the sole POST. Project/Run/Attempt, original request,
Worker/origin/pin/grant fingerprint, paths, host/UID/interpreter/driver bytes and
Ray endpoint/token fingerprint/version are bound. Existing intent or lost/refused
POST never resubmits, including vendor history loss. Driver digest/local context
checks and the native live-index original-request check precede preparation/poll;
the existing native consume/start barrier, fixed child and authority checks remain.

Vendor observations verify exact command/metadata/environment; fixed resource
hints are bound in intent/metadata and POST. Pinned Ray JobDetails omits resource
fields; contrary values refuse if supplied, but GET is not a reservation proof.
Observations read no task logs and append no project facts. Native observation/verified output/
receipt recovery runs outside Ray with the original private process identity,
never a new task. Ray stop acknowledgements/status cannot prove group exit;
controller intent and actual saved-group observation establish cancellation.
Gate: `tests/test_ray_native_job.py` refusal/replay fixtures, existing native/CLI
regressions and `tests/test_ray_native_live.py` in designated `ray-native` CI.
The latter requires actual Ray CPU project output, real discarded POST response,
second-instance receipt replay and vendor stop plus controller/OS cancellation;
missing Ray/OS identity or deadline fails, not simulated or skipped acceptance.

Residual trust: only a provisioned owned single-node same-UID compute environment
is supported; installed package/host labels/private credentials are trusted
operator resources. This adds no strong sandbox, remote hardware attestation,
GPU allocation/device inheritance or multi-node path distribution. Selected
host/GPU/Kaggle evidence and Checkpoint B acceptance remain pending-live.


### TM-079: A local browser reads or crashes more than it should

A browser is an untrusted client even on loopback, so a stalled or hostile
socket must not become an unbounded read of the operator's process. The local
API refuses an oversized declared length without reading, cuts an understated
length off at the cap instead of trusting it, and refuses rather than queues a
request above the concurrency cap. Source-byte bounds are not treated as parser
bounds: JSON and YAML bodies are re-decoded through the existing
duplicate-key-rejecting, alias-refusing loader and PDFs through the existing
bounded extractor, so nesting, node count, page count and extraction seconds are
capped during the work rather than after it. Every limit is reported by
`/capabilities` so a client cannot silently assume a larger allowance.

The listener bounds socket handlers before thread creation and applies both an
idle timeout and an absolute request deadline, including headers. SSE keeps its
application slot until exhaustion or close. Dedicated SQLite read-only connections
have a progress-handler deadline; SQL applies project/type filters before LIMIT.
PDF previews use the isolated evidence worker, rather than parsing in-process.

Gate: `tests/test_web_regressions.py` real SSE concurrency, scoped snapshot paging,
10k-store query evidence, PDF worker tripwire, query interruption and header deadline;
`tests/test_web_api.py` body, depth, alias, duplicate-key, PDF,
concurrency and declared-length cases. Residual trust: a local user can still
read their own project through the filesystem, and `wsgiref` is not hardened
against a hostile network peer.


### TM-080: Local API errors leak paths, bodies or credentials

An error body crosses the same trust boundary as a request and is the easiest
place to leak an absolute path, a source document or a stack trace. Every
failure is rendered as one closed `LocalApiError` code with fixed operator
text; the unhandled-exception branch produces the same shape rather than a
traceback. Project views report only manifest-relative paths. Artifact bytes are
inlined only below a size cap and are never returned for a digest the project
does not reference.

Gate: `tests/test_web_api.py` relative-path, unknown-route, oversized-body and
cross-project artifact cases.


### TM-081: A browser session is reused as launch or Worker authority

A local session that also worked as a grant, bearer token or client certificate
would turn a read surface into a launch path. Access requires a one-time
bootstrap secret shown in a URL fragment, which is never transmitted, logged or
put in a `Referer`. The resulting cookie is `HttpOnly; SameSite=Strict` and
exists only in memory, bounded in count and idle expiry. `Host` must equal the
exact configured authority, which closes DNS rebinding; unsafe methods require a
matching `Origin` and a double-submit CSRF token. No route accepts a Worker
grant, a private TLS key or a bearer token, and none forwards a session to the
Worker plane.

Gate: `tests/test_web_api.py` host, origin, bootstrap replay, forged cookie,
missing/mismatched CSRF and session-is-not-a-Worker-credential cases. Residual
trust: any process running as the same OS user can read the operator's files, so
this boundary is same-user, not same-privilege.


### TM-082: A global content index leaks another project's artifacts

The artifact index is keyed by digest alone, so a digest-scoped read would
expose any object ever referenced by any project. Artifact access is proven from
linked events instead: a digest is visible only when a verified event of the
requesting project references it, resolved through a bounded link page rather
than a full-table scan. Event, revision and run pages filter on `projectId`, and
cursors are opaque server-issued values that cannot be forged into an arbitrary
offset.

Gate: `tests/test_web_api.py` cross-project denial, own-project success, forged
cursor and cursor-walk coverage.


### TM-083: The workbench reports an unobserved or synthetic outcome as success

A read view that guesses lifecycle state from event names will eventually render
a run that was never observed, or one that only ever ran a simulated lifecycle,
as a green success — the precise claim this project exists to prevent. State is
therefore derived from the authoritative `RunControl` fold and mapped onto a
closed set, where `cancelled` becomes an observed stop rather than a success and
a fold refusal becomes `absent` instead of an invented status. Provenance is read
from the authorization event the run's `run.queued` fact actually cites, so
`audit-only` or `not-executed` is labelled synthetic; anything the workbench
cannot source stays `absent` and is never called real. Only an observed
successful outcome receives success styling, and `isReportableOutcome` gates
anything that compares results so `unknown` and `lost` cannot enter a comparison
as results.

Gate: `tests/test_web_assets.py` fold-derived state, fold-refusal-absent and
closed-observation-set tests; verified in a real browser against
`example-minimal`, where the run index rendered `Succeeded` with
`Synthetic (not a measurement)`. Residual trust: the view can only be as honest
as the facts it reads; a store whose own facts are wrong is not corrected here.

### TM-084: Client types drift from the server contract

A hand-written client type that silently diverges from the server makes a
contract change look like a working view with empty fields. The wire contract is
owned by frozen Pydantic models, the browser types are generated from them, and a
drift test fails when the committed file no longer matches, so a shape change
breaks `tsc --noEmit` and pytest together. The generated file is checked in and
the generator is named in its header; the check refuses an `any` field and a
malformed optional marker.

Gate: `tests/test_web_assets.py` contract-drift, generated-header and
loose-field tests. Residual trust: the committed JavaScript bundle itself is a
build product and is not rebuilt or diffed by CI, which installs Python only. A
stale bundle is possible; the Python-owned contract types are what CI enforces.

### TM-085: A static asset request escapes the bundle or is mis-typed

Serving the workbench from the installed package adds a file-serving surface to
a loopback service. Each path is resolved by directory descriptor with
`O_NOFOLLOW` on every component, so neither `..` nor a symlink can leave the
asset root, and a symlink's `ELOOP` is mapped to a closed error instead of
escaping as an `OSError` that would surface as a 500. Content types come from a
closed suffix table with `X-Content-Type-Options: nosniff`, so a hostile upload
cannot be re-interpreted. The bundle itself loads without a session, because the
operator must be able to load the page in order to obtain one; every versioned
API route remains behind the session check, which a test asserts explicitly.
`web/node_modules` is excluded from both build targets, so the toolchain cannot
enter the sdist or the wheel.

Gate: `tests/test_web_assets.py` traversal, symlink, directory, content-type,
bundle-without-session and API-still-gated tests; `uv build` verified to ship
`web/static` and no `node_modules`. Residual trust: a same-user local process can
read the installed package files directly, as it could before.

### TM-087: Stale or poisoned read indexes and nested result links expand visibility

A rebuildable artifact/spec index is not an authorization source. The workbench
proves project scope from verified original events even when query caches are
empty or poisoned. Inspecting a nested result link requires a project-linked
root and a bounded chain of hash-verified parent bytes; client-supplied ancestor
names do not grant access. Paths are capped at eight ancestors, references at
100 and inline bytes at 256 KiB. Large objects are explicitly not verified by
this bounded read. Typed spec/plan graph validation precedes topology display;
nested/over-limit graphs stay unsupported. Secret keys and absolute path values
are hidden in structured inspection, and HTML is rendered as React text.

Gate: `tests/test_web_inspection.py` source-fact scope, cache poisoning, fresh
revisions, transitive proof/refusal, redaction, digest and graph contracts;
`web/scripts/smoke.mjs` actual browser navigation over SQLite/CAS fixtures.
Residual trust: project authors control free-form artifact/log content; structured
redaction cannot identify every secret embedded in arbitrary prose. The browser
session remains a read boundary and creates no Worker authority.

### TM-086: A browser command duplicates work or reports a request as an outcome

A click that is dispatched twice, a second window, or a retry after a lost
response must not append a second fact, and an accepted cancellation must never
be shown as a stopped process. The browser mints one command identity per
operator intent and reuses it on retry, so the shared service's durable receipt
decides: same identity and content replays the prior receipt, same identity with
different content is refused, and a stale `expectedHead` or `expectedRevision`
fails visibly. A 5xx or transport loss is reported as *uncertain* with the
identity retained, never as success or failure, and resending it either replays
or appends one fact. The cancellation receipt carries `observedStop: false` and
the run index keeps reporting whatever the run's facts support, so a request
cannot silently become an outcome. Commands reuse the CLI's services rather than
a browser-side state machine, so replay and the CLI cannot disagree.

Gate: `tests/test_web_commands.py` repeat/replay, conflicting content, two
windows, terminal-run refusal, unknown-grant refusal, session/CSRF/Origin
refusals and the `observedStop` assertion; verified in Chrome, where a committed
cancellation left the run index reading `Running`. Residual trust: a real
double-click is not driven in CI, which runs no browser; the receipt semantics
are covered in pytest, not by an end-to-end click.

### TM-087: A browser command needs a Worker credential to revoke authority

Revoking a grant through the Worker plane would require an HMAC key, putting a
Worker credential in the browser's path and turning a read-plus-cancel surface
into a launch-capable one. Revocation therefore appends one `grant.revoked` fact
through the control plane, which needs no Worker credential, never grants, never
completes or stops work, and refuses an unknown grant. No command in this surface
can report `launchAllowed: true`, and the preflight that shows a plan before
authorization is read-only and always reports false.

Gate: `tests/test_web_commands.py` unknown-grant refusal, preflight
`launchAllowed: false`, and the operations surface asserting that a `true`
`launchAllowed` would be flagged. Residual trust: any local process running as the
same user can append facts directly to the store; this boundary is about the
browser surface, not about the filesystem.


### TM-088: A proposal cites evidence that does not exist, or evidence speaks for itself

A citation the project never recorded is not a citation, and a proposal that
cites one would launder an unverified claim into the ledger. Citations are
resolved against the `EvidenceControl` fold on both the read-only validate path
and the mutating submit path, and any unresolved reference refuses the proposal
while naming it. Imported text is data, never an instruction: a rationale that
reads like a tool request is stored verbatim and grants nothing, with
`grantedPermissions` empty and `runQueued` false regardless of its content. A
validated proposal is a draft that queues no Run, and `expectedRevision` binds
it to the revision the caller actually read so a stale proposal cannot land on a
newer revision.

Gate: `tests/test_web_research.py` unresolved-citation refusal, stale-revision
refusal, draft-queues-no-run, and a hostile rationale asserting empty granted
permissions and no queued Run. Residual trust: a project can still import hostile
text; the boundary is that importing it grants nothing.

### TM-089: Overriding a dissent erases the disagreement

A decision that overrides an AI or human objection is a legitimate outcome, but
silently dropping the objection would make the ledger misrepresent the
disagreement that occurred. Overriding therefore records which dissent was
overridden, the dissent itself remains in the ledger, and the browser renders
the decision beside the dissent it overrode with the rationale intact across
refreshes. The ledger separately refuses to re-decide a closed proposal, so a
rejection cannot be manufactured after the fact.

Gate: `tests/test_web_research.py` preserved-disagreement and
rationale-survives-refresh tests, plus the closed-proposal refusal the rejection
test depends on.


### TM-090: A reported number cannot be reproduced, or a better score is treated as a finding

A metric with no stored detail cannot be re-derived, so a result whose aggregate
disagrees with its own per-example artifact is not evidence. Every evaluation
therefore records dataset digest, evaluator version, split, seed and example
count, stores the full per-example detail as one CAS artifact, and appends no
per-sample event. Metrics are fixed-precision decimal strings so a comparison
cannot depend on binary rounding, and `recompute` re-derives the aggregate from
the stored detail. Comparisons across differing provenance are refused with the
mismatch named rather than averaged, a comparison declares
`supportsAConclusion` only with at least two required metrics, and conclusions
are human judgements in a versioned three-verdict contract that records
`systemDerived: false`. A negative or inconclusive result is a legitimate
recorded outcome.

Gate: `tests/test_evaluation.py` determinism, detail reproducibility, provenance
completeness, refused comparison, and the single-metric-cannot-conclude test;
`tests/test_web_evaluation.py` real labelling, no-events-appended, and the
conclusion refusal paths. Residual trust: the held-out set is small, so every
comparison states its repeat-variance limitation in the document itself.


### TM-091: An extension manifest executes code or obtains authority by declaring it

A plugin surface that imports a manifest, or that quietly narrows an unknown
permission, turns a declaration into a grant. Extension manifests are therefore
read with `O_NOFOLLOW` under a size bound, parsed as JSON and validated without
import, evaluation or network access; two tests run an entry module that writes
a marker file and assert it does not appear, both when the manifest is accepted
and when it is refused. Permissions form a closed set and an unrecognised name
refuses the manifest rather than being dropped, so a capability the author
expected is never silently absent. `NEVER_GRANTED` names what this host will
never provide — `execution.launch`, `control.write`, `events.write`,
`artifacts.write`, `authority.create`, `secrets.read`, `network.outbound` — and a
manifest requesting one is refused. Incompatible contract versions are refused
before anything else is trusted, and `trust="untrusted"` is refused outright
because no verified isolation profile exists here.

Gate: `tests/test_extensions.py` inert-load marker tests, unknown and
never-granted permission refusals for every name, contract refusal, symlink and
oversize refusals, and the untrusted trust-level refusal.

### TM-092: An extension crashes, hangs, floods output, or inherits the operator's secrets

A reviewed same-user adapter is still code that can fail, so its message,
duration, output and resource use are bounded, and it receives a minimal
environment rather than the caller's. The child is proven not to inherit
`HOME`, `SSH_AUTH_SOCK` or provider keys, and a crash, a non-zero exit, a
wall-clock timeout and oversized output each leave the registry intact. Output is read into fixed-size buffers; overflow terminates the owned group and
returns an explicit outputLimitExceeded error. Non-UTF-8 replacement stays capped. Critically, the
enforced resource-limit set is probed rather than assumed — macOS rejects
`RLIMIT_AS` — and the capability surface reports what the platform actually
applies, because a limit that cannot be set is not a limit. The surface states
in plain text that these bounds are not a sandbox.

Gate: `tests/test_extensions.py` crash, timeout, output-bound, environment-isolation
and effective-limit-probe tests, plus a crashing extension leaving a healthy one
resolvable.

R14 review strengthens TM-091/TM-092: regular files only (nonblocking open refuses
FIFOs), finite bounded immutable manifest snapshots, closed trust admission and
trust-bound registry identity. Current enabled/reviewed state is checked at
registry dispatch. Child limits run after exec rather than Python preexec_fn;
the timeout includes blocked stdin/inherited pipes, and cleanup kills only the
owned process group. Per-invocation applied limits are reported via a bounded
private pipe. Permissions are inert requests, not OS grants; same-user file and
network access are explicitly not isolated. Disabled state does not cancel
in-flight work. Tests reproduce each repaired boundary.
### TM-093: A backup is taken by copying a live SQLite file, or an image is trusted on its own manifest

A naive file copy of a live WAL database can capture a torn page set and miss
committed content, and a manifest is only a claim until the bytes are re-derived
from it. `backup create` therefore snapshots through the SQLite online backup
API, reads the resulting prefix, then collapses the snapshot to one standalone
file with no `-wal`/`-shm` sidecar so every event the manifest digest covers is
present in the file it covers. The written image is re-verified from a copy
before it is published, and `backup verify` re-derives the snapshot digest, every
object digest and size, and the event count from the image itself. A referenced
content object missing from the workspace aborts the backup instead of producing
an image that restores to a broken project.

Gate: `tests/test_recovery_backup.py` snapshot-shape, tampered-snapshot,
tampered-object, escaping-manifest-key, missing-object, interrupted-backup and
verify-after-create tests, plus the installed-wheel clean-install journey in
`scripts/wheel_smoke.py`.

### TM-094: A restored workspace is treated as resumable, or its diagnostics are shared before inspection

A restore cannot observe a process that belonged to the previous machine, so it
copies facts and nothing else: the restored high-water equals the image
high-water, `appendedEvents` is 0, no Worker is started, and every Run left
non-terminal is reported as `unknown` with a `reconcile-manually` next action
(ADR-0054). A hand-edited manifest is refused: the object *set* is re-derived from the
events and must equal the manifest's, an object key must equal the key derived
from its digest, the snapshot size and the last event digest are compared, the
schema version is compared, and the manifest read is size-bounded. A rename
naming a project the image has no events for fails the ledger comparison rather
than folding an empty ledger on both sides and reporting a match. An occupied
restore destination is refused before anything is written. Diagnostic details carry
counts, booleans and caller-supplied identifiers only, pass through
`redact_object` (TM-007, TM-022), and never carry a host path, a document body
or a credential, so a report is safe to paste into an issue.

Gate: `tests/test_recovery_backup.py` no-relaunch, damaged-image-before-write,
occupied-destination and escaping-key tests; `tests/test_recovery_doctor.py`
host-path-leak, secret-redaction, damaged-store, missing-asset, missing-object
and taken-port tests.

R15 review hardening (2026-10-06): restore binds the copied SQLite bytes to the
verified snapshot digest before opening them; layout overrides cannot escape the
new root, staging directories are unique, and backup reads reject non-regular
files. The manifest is size-bounded during the read. Parent-directory races by
processes with the same filesystem privileges remain outside this local-tool
boundary. Regression evidence: `tests/test_recovery_backup.py`.

### TM-095: A trial record counter is mistaken for phase acceptance

Trial records are self-reported operator documents. Confirmation fields cannot
authenticate an author, prove participant independence, grant remote access or
verify an attached report. The aggregate derives fixed task coverage from
confirmed completed journeys, refuses duplicate IDs and contradictory outcomes,
and preserves arbitrary extra blockers. It always returns `checkpointD: false`
and `acceptance: requires-maintainer-review`; task coverage is a separate result.
Regular-file reads are bounded at 1 MiB per record and 32 MiB per kit. Tests:
`test_recovery_trials.py` and `test_recovery_cli.py`. Real human and selected-host
acceptance remains pending-live and cannot be fabricated by this tooling.

### TM-096: Browser retry or configured profile launches unintended native work

The local browser selects a bounded installed profile ID; it cannot submit
credential paths, code or a profile document. Configuration is installed by the
operator. Inputs are confined to the controller workspace and prepared/state
paths to its Worker root, with ancestor symlink checks and bounded regular-file
reads. Inspection binds material identity; changed material is refused at start.
Existing native reviewed authorization, grant, code/platform/limit, restore and
cancellation gates remain mandatory. Secrets stay in the controller process;
receipts expose identities and observed outcome digests only.

A durable project/Run reservation precedes execution. It persists across failed
HTTP responses, crashes and receipt-write errors, so another browser command
cannot redispatch that Run. Observe uses existing identity and authority only.
Backup restore uses a confined new destination and pins the verified manifest
at materialization. No task is automatically restarted. The native subprocess
continues to be reviewed same-user execution, not an untrusted-code sandbox.
Operator privileges, same-user directory races and deliberate edits to private
SQLite operation state remain outside this browser boundary. Browser request
deadlines can leave a live task requiring explicit observation.

Gate: `tests/test_application_native.py` actual CPU launch, source/target
checkpoint restore, reservation/crash/material-change/escape regressions; actual
browser gate `web/scripts/smoke.mjs` lost-response replay, reconnect and backup
recovery. Existing native/Worker and backup gates remain required.

### TM-097 — Browser research generation and evidence import

Operator-installed model profiles bind bounded workspace request/fixture documents and CAS base/candidate material; browser callers supply a simple ID and an inspected digest. Existing endpoint/permission/secret/budget gates remain authoritative. A durable project/call intent precedes effects; the initial budget or Mock fact uses the caller's expected head. Dispatched uncertainty remains reserved, exact receipts replay, and observation reads stored facts without requesting again. Output is a strict, actor-bound, citation-resolved draft with a recomputed semantic diff, never tool authority.

Frozen evidence only comes from the dedicated inbox and preserves source/version, reading/training rights and bounded isolated extraction. Symlink/path escapes and selecting credentials outside that inbox are refused. Human edits are attributed to the operator and do not erase generated CAS evidence or dissent. These controls do not isolate an adversarial same-user process, validate an operator's license assertion, reconcile provider invoices, or prove human/scientific acceptance. Gate: `test_application_research_workflow.py`, legacy proposal regressions, actual loopback HTTP and committed-bundle browser CI.
