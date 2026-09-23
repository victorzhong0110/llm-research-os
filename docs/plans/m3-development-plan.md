# M3 development plan

Status: **R01 integrated by PR #84 at `7d1bcbe`; R02 is under review in #105.** This is the
single maintained M3 task plan. Recording a task does not complete it.
Planning baseline: `main@e1282c5601e08a0bb46ebe10f8d2eca470b4a015`, after #81.
R01 integration: `7d1bcbe0c956e0fd7d7ce98f07b6c42c8439cc47`.
Start implementation from the latest verified main after predecessor acceptance.
Work-package navigation: [GitHub index #104](https://github.com/victorzhong0110/llm-research-os/issues/104).

This revision supersedes the proposed ordering in PR #80 and the earlier
`fabd73d` / `1729cb2` drafts of #84. Those drafts put Web before native
execution and assigned different meanings to R03–R16. They are historical
review material, not alternative execution instructions. PR #80 is not an
additional plan to merge after #84; its disposition remains with the maintainer.

The maintainer's agreed R01–R16 definitions below are authoritative for this
phase. Global planning and review belong to the designated planning/review
assistant; implementation belongs to the assigned implementer. See
[development governance](../development-governance.md) and
[ADR-0064](../adr/0064-planning-and-implementation-ownership.md).
There is no personal calendar, effort-duration estimate, or delivery deadline.

## Outcome and checkpoints

Deliver a local research workbench: inspect evidence and an AI proposal,
make a human decision, authorize an exact experiment, execute on a local or
user-owned remote machine, observe or cancel it, compare real results, and
preserve an evidence-linked human conclusion. Real evaluation is required
in R13; it is not an optional decision deferred to milestone closure.

| Checkpoint | Packages | Observable outcome |
| --- | --- | --- |
| A | R02–R06 | Real local native execution with bound inputs, authorization, artifacts, cancellation, and recovery |
| B | R07–R08 | SSH onboarding, task-scoped transfer, and new two-host fault evidence |
| C | R09–R13 | Browser operation, AI proposal review, real evaluation, and human conclusions |
| D | R14–R16 | Extension boundary, installation/recovery, and independent trials |

The default sequence is R01 → R02 → R03 → R04 → R05 → R06 → R07 → R08 →
R09 → R10 → R11 → R12 → R13 → R14 → R15 → R16. Each package depends on
acceptance of the preceding package. Smaller sequential PRs are permitted;
renumbering or replacing packages is a planning change. At A/B/C/D submit a
runnable demonstration, validation results, and remaining gaps for review.

## Verified baseline and evidence boundaries

| Capability | Implementation / verification | Evidence and limitation |
| --- | --- | --- |
| M1 research loop, Mock, questions, dissent, decisions, simulated authorization consume | Merged; accepted offline scope | ADR-0062; installed-wheel acceptance; no real model/training claim from simulation |
| Evidence import, OpenAI-compatible adapter, synthetic metrics, reports | Merged; tested within their documented contracts | Existing M1 tests; synthetic metrics are not real evaluation evidence |
| Worker HMAC grants/sessions, expiry, revocation, claim/complete | Merged; tested and used in accepted M2 paths | Reuse existing Worker authority and lifecycle |
| Local host-Python helper | Merged; verified at unit/loopback scope | Does not certify the planned generic native entrypoint profile |
| CPU OCI runtime | Merged; verified in designated Linux OCI CI and accepted WSL2/Docker scope | Existing OCI/fault tests and M2 evidence; not a generic host-native claim |
| WSL2/Docker two-host CPU, reconnect, cancel, CUDA short training, checkpoint upload and 10→12 restore | Merged; accepted live evidence at recorded identities | ADR-0062 and M2 matrix; cuda.9 remains partial, cuda.10 failed, cuda.11 full-state restore |
| macOS/MPS LoRA profile | Merged; scoped live evidence acknowledged by ADR-0062 | Separate MPS profile; not generic native or OCI validation |
| Detached Ed25519 attestations | Merged; verified offline audit contract | ADR-0061; `launchAllowed=false`, not launch authority |
| #81 restricted native noop | Merged; CI-verified fixed helper and cancellation behavior | ADR-0063; entrypoint not imported; no real task lifecycle or artifact claim |
| #81 SSH pack writer and SSH refusal | Merged; validator/writer/refusal tested | Actual onboarding and execution remain pending-live; a pack is not a two-host proof |
| R02–R16 capabilities | Planned | Per-package evidence must be supplied; no new capability is accepted by this plan |
| Paid cloud, hosted multi-tenancy, marketplace | Deferred | No new spend or publication authorized by the plan |

Verification always records its scope and implementation/evidence identity.
Historical accepted hardware evidence remains accepted at its recorded SHA;
it does not certify a newer implementation. Lack of a paid-cloud, new-platform,
or external-trial record does not downgrade an already accepted local path.
See [ADR-0062](../adr/0062-m1-m2-acceptance-and-m3-boundary.md), the
[M2 matrix](../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md), and the
[M3 acceptance matrix](../evidence/m3/acceptance-matrix.md).

## R01: Scope, capability state, and acceptance baseline

**Dependency:** none; this documentation PR.

Establish one consistent task baseline without extending runtime behavior.

**Deliverables**

- Align every package, dependency, checkpoint, evidence row, and handoff with this R01–R16 sequence.
- Keep historical acceptance scoped to its platform and SHA; distinguish implementation, validation, live evidence, and maintainer acceptance.
- Record ownership of normative files and correct current contributor entrypoints. Map original M3 identifiers by subject, not by inherited execution order.

**Acceptance**

- README/status/plan/matrix agree; the integrated R01 SHA and post-merge CI are recorded without claiming R02–R16 acceptance.
- No claim that #81 completes real native execution, SSH live acceptance, or Issue #53.

**Out of scope:** Runtime code, new execution authority, issue closure, release, or tags.

## R02: Shared application services

**Dependency:** R01 accepted.

Expose existing domain operations through a thin shared layer for CLI, Python, and later Web callers.

**Deliverables**

- Bind workspace project identity, EventStore, CAS, configuration, and operation state; reject cross-project references and accidental shared control/Worker roots.
- Extract only required workspace/revision, validate/diff/dry-run, ledger, decision, and Run-query operations. Reuse existing controls instead of duplicating state machines.
- Define command identity, request digest, expected revision/head, and durable receipts linked to facts/artifacts. Same identity/content returns the prior result; conflicting content or stale revisions fail visibly.
- Preserve explicit identity and time inputs at low-level boundaries. Define SQLite schema v2 compatibility and any necessary migration without rewriting historical event digests.

**Acceptance**

- CLI and Python entrypoints have identical semantic results; revisions and receipts survive restart.
- Repeated operations cannot create duplicate Runs; cross-project references fail; core works without training extras.

**Out of scope:** Web, actual native launch, SSH, new authority stores, and general workflow engines.

## R03: Real native execution contract

**Dependency:** R02 accepted.

Freeze the reviewed native profile and authority boundaries before implementing a real runner.

**Deliverables**

- The planning/review assistant owns the ADR and contract requirements; the implementer may draft schemas/examples and feasibility evidence within that assignment.
- Bind project, Run, Attempt, task, spec/registry/plan/decision, code, inputs, configuration, interpreter/environment inventory, profile version, and resource limits.
- Define supported platforms and reviewed-code trust explicitly. Separate requested, enforced, and unsupported network/filesystem/memory restrictions; reject required isolation that the selected platform cannot enforce.
- Reuse Worker grants, expiry, revocation, and consumption. Specify the launch linearization point: pre-gate revocation denies; post-gate revocation enters cancellation/observation.
- Keep the historical non-launching preflight and #81 fixed noop contracts distinct from the executable profile. Fact signatures do not grant launch permission.

**Acceptance**

- Versioned request/report contracts and valid/invalid examples cover stale or substituted identities, expiry, revocation, replay, and unsupported profiles.
- The chosen trust/platform boundary is reviewed before R04/R05 implement it.

**Out of scope:** Arbitrary untrusted host-code execution, invented sandbox guarantees, and redesigning Worker credentials.

## R04: Verifiable code and runtime environment

**Dependency:** R03 accepted.

Prepare immutable, digest-bound executable inputs and a verifiable environment.

**Deliverables**

- Materialize reviewed code/config/data from bounded verified artifacts. Record interpreter and dependency/environment identity; a mutable executable path is insufficient.
- Design protection against substitution between approval, verification, and launch. Bind prepared material to the grant/plan rather than accepting newly changed source paths.
- Provide environment preparation and doctor diagnostics with safe repeated execution and explicit handling of mismatched existing environments.
- Use a lightweight CPU Python brick as the first real fixture; prepare examples and tampering cases without requiring GPU or training extras.

**Acceptance**

- Replacing code, configuration, inputs, or required environment identity invalidates the old binding before user code starts.
- A fresh workspace can prepare and verify the inputs; incomplete or damaged preparation is diagnosable and not silently reused.

**Out of scope:** Implicit system installs, arbitrary dependency execution in the control plane, cloud provisioning, or training-framework requirements for the core.

## R05: Real native execution through the Worker lifecycle

**Dependency:** R04 accepted.

Execute a real reviewed entrypoint and record its outcome in existing Run/Attempt and artifact mechanisms.

**Deliverables**

- Compose existing Worker authorization, binding, claim/complete, RunControl, CAS, and supervision. Import user entrypoints only in the task process.
- Consume valid launch authority before starting user code; freeze inputs and use fixed runner/argv with bounded structured input, output, and diagnostics.
- Persist launch intent and execution identity. Define recovery across consumption, child creation, identity persistence, and start of user code, including a child created before identity is durably recorded.
- Collect task-scoped output into verified artifacts and record completion/failure/audit facts; a process exit alone is not a full research result.

**Acceptance**

- A real CPU task produces reproducible output, lifecycle facts, and verifiable artifacts.
- Denied, expired, revoked, substituted, or duplicate claims do not start unauthorized or duplicate tasks.
- Faults at persistence boundaries remain explainable; uncertainty does not automatically redispatch the same Attempt.

**Out of scope:** A separate task ledger, shell-concatenated commands, public-key launch credentials, or treating the noop as real execution.

## R06: Cancellation, observation, and crash recovery

**Dependency:** R05 accepted.

Make real task stop and recovery obey the existing observation and identity rules.

**Deliverables**

- Reuse ADR-0054 process-group observation and recorded execution identities; never infer full stop from only the leader exit or a failed probe.
- Honor the authorized termination policy, including TERM/grace/KILL where supported. Cover remaining children, PID reuse, permission errors, and cancellation races.
- Recover after controller/Worker restart by observing existing work and reconciling facts; unknown does not grant rerun authority.
- Define checkpoint integrity, compatibility, restore mode, new Attempt identity, and lineage. Distinguish full-state restore from adapter-only loading.

**Acceptance**

- Only observed stop becomes cancel-observed; unavailable evidence stays unknown.
- Real-process tests cover supported Linux/macOS profiles, crash boundaries, leftover descendants, and restored-state prerequisites.
- Checkpoint A demonstrates an actual local task, cancellation, and restart/recovery with inspectable evidence.

**Out of scope:** Automatically repeating unknown tasks, killing unverifiable reused PIDs, and inventing checkpoint success from file presence.

## R07: SSH onboarding and doctor

**Dependency:** R06 accepted.

Turn the validated pack into a repeatable connection/bootstrap flow for a user-owned machine.

**Deliverables**

- Probe platform, Python/environment, disk, permissions, capabilities, and network prerequisites; explain concrete repairs.
- Validate host-key pinning and rotation behavior. Use approved dedicated credentials or existing trusted SSH configuration without writing private keys to packs, events, or Web forms.
- Install/verify a pinned package in a user-owned directory with idempotent registration and cleanup of only resources created by this operation.
- Keep execution on the existing Worker protocol. SSH provides bootstrap/connectivity, including a reviewed tunnel when needed; verify actual TLS and Worker registration, not just tunnel creation.
- Use fixed remote command templates and bounded stdin/files. Local shell=false alone does not neutralize the remote shell. Preserve no agent forwarding and TLS verification.

**Acceptance**

- Clean-host onboarding succeeds on an authorized host; key/certificate mismatch, missing prerequisites, permissions, disk/port conflicts, and disconnects have explicit outcomes.
- Repeated preparation neither overwrites unrelated resources nor launches training. No control SQLite/CAS/private TLS key is copied into the Worker root.
- Only evidence for the specific environment and operation can advance a pending-live record.

**Out of scope:** A second SSH task executor, automatic sudo/driver/firewall changes, and claiming live success from configuration generation.

## R08: Two-host artifact transfer and fault acceptance

**Dependency:** R07 accepted.

Verify new native execution and recovery across two actual machines.

**Deliverables**

- Implement grant/task-scoped verified input and output transfer with path, symlink, count, size, temporary-disk, and integrity bounds; never expose the entire CAS.
- Support bounded file-level retry and interrupted transfers. Deliver verified checkpoints to the designated new Attempt or clearly refuse unsupported restores.
- Exercise disconnect before claim, tunnel loss during execution, controller/Worker restart, interrupted upload, lost completion response, disconnected cancellation, and unavailable process-identity observation.
- Record new implementation/runtime/input identities and process observations for a real CPU native task; exercise one already supported GPU profile where authorized. Do not reuse cuda.1–11 or relabel M2 OCI evidence as native proof.

**Acceptance**

- Reconnect resumes observation, transfer, or receipts without a duplicate task start.
- Corruption and unauthorized paths are rejected; two-host unknown and cancel-requested remain distinct from failure/success/stopped.
- Checkpoint B has a new scoped evidence pack; lack of a second authorized host is pending-live, not simulated acceptance.

**Out of scope:** General large-object infrastructure, paid-cloud certification, and assuming old accepted hardware records certify this implementation.

## R09: Local API and browser authority boundaries

**Dependency:** R08 accepted.

Expose the shared services safely to a local browser after execution foundations are accepted.

**Deliverables**

- Provide versioned read/validation/preview endpoints, structured errors, bounded projections, and resumable SSE with polling fallback.
- Use local same-origin sessions with Host/Origin validation, authentication, and applicable CSRF protection; browser sessions are not Worker credentials.
- Apply body/depth/node/time/concurrency limits during parsing, including actual JSON/YAML/PDF paths. Preserve existing replay compatibility; source-byte bounds alone do not ensure parser resource bounds.
- Scope cursors and artifact access to projects; include snapshot high-water marks and use bounded metric chunks rather than appending each sample as an event.

**Acceptance**

- Cross-site/unauthorized requests, wrong-project access, hostile documents, oversized inputs, slow clients, and reconnects have tested outcomes.
- Queries at representative event volumes stay bounded; record a baseline before optimizing storage.
- Errors and logs do not leak credentials, source bodies, or arbitrary host paths.

**Out of scope:** Generic shell/path/event-append endpoints, hosted multi-tenancy, and a second authorization implementation.

## R10: Read-only research workbench

**Dependency:** R09 accepted.

Present real project, experiment, execution, and evidence data in the browser.

**Deliverables**

- Build project overview, immutable spec/plan inspection, read-only graph, Run/Attempt details, logs, metrics, artifacts, and environment views.
- Show decision/dissent/authorization history and evidence lineage. Reuse backend folds; graph layout does not change semantic digests.
- Provide meaningful empty/error/offline states, keyboard access, and bounded rendering; distinguish synthetic, absent, and real data.
- Generate frontend types from published contracts and test drift; keep unsupported execution graphs visibly unsupported.

**Acceptance**

- All views use actual API data; refresh/restart preserves meaning; result-to-data/code/config/decision links resolve.
- Unknown, lost, failed, cancel-requested, and observed stop are distinguishable without misleading success styling.

**Out of scope:** Editable DAGs, hand-maintained duplicate ResearchSpec models, and browser-side Run state machines.

## R11: Browser approval, execution, cancellation, and restore

**Dependency:** R10 accepted.

Operate the existing execution system through explicit reviewed browser actions.

**Deliverables**

- Show exact plan identity, target, permissions, supported/enforced limits, and resource/budget requirements before approval.
- Expose start, revoke-unused-authority, request-cancel, reconnect/observe, and valid restore through shared idempotent commands.
- Handle double-clicks, retransmission, stale tabs, concurrent windows, and uncertain HTTP responses through durable operation/Run identities.
- Keep proposal acceptance and execution authorization distinct. Changed plans require revalidation; new Attempts need valid authority and disposition of old work.

**Acceptance**

- Browser E2E covers duplicates, stale plans, cancellation, disconnect/reconnect, and restore prerequisites.
- UI, CLI, and event replay agree; request acceptance is not misrepresented as observed process completion.

**Out of scope:** UI-created authority, automatic rerun after timeout, or optimistic stop claims.

## R12: AI proposals, citations, and researcher decisions

**Dependency:** R11 accepted.

Bring the existing M1 research objects into a usable evidence-linked browser workflow.

**Deliverables**

- Reuse evidence import, Mock, OpenAI-compatible provider, questions, dissent, decisions, budget reservations, and research ledger.
- Bind each proposal to a base revision, candidate artifact, server-derived diff, versioned sources, predictions, falsification conditions, risks, and resource needs.
- Support acceptance, rejection, amendment, questions, and preserved disagreement; generated text first becomes a validated draft.
- Reject unresolved citations and invalid outputs; distinguish reading rights from training rights; treat imported text as evidence, not executable instructions.
- Retain an offline no-key path. Uncertain dispatched model calls do not release reservations and retry without bounds.

**Acceptance**

- Rejection creates no Run; stale proposals cannot overwrite revisions; refresh preserves decisions and rationale.
- Local compatible-server integration tests exercise the real HTTP contract without a paid-model prerequisite.
- Model output or hostile evidence cannot grant tools, change permissions, or launch work.

**Out of scope:** General autonomous-agent orchestration, literature crawling infrastructure, and mandatory paid API calls.

## R13: Real evaluation, comparison, and conclusions

**Dependency:** R12 accepted.

Produce a reproducible baseline/candidate comparison required for this phase.

**Deliverables**

- Implement one deterministic evaluator and fixed held-out data with explicit metric definitions, aggregation, seeds, versions, and provenance.
- Use a small CPU fixture for contract coverage and one supported real model/evaluation path for acceptance. Reuse the existing adapter where suitable; no second large training framework is required.
- Compare baseline and candidate artifacts, retain bounded detail results/failure cases, and allow aggregate recomputation.
- Flag incompatible datasets/evaluator/configurations instead of silently comparing them. Explain limitations and repeat variability where relevant.
- Generate an editable evidence-linked report; humans record supported, unsupported, or insufficient-evidence conclusions. Version new conclusion contracts rather than extending unrelated enums silently.

**Acceptance**

- A real baseline/candidate result is reproducible from detail artifacts; synthetic results remain labeled.
- Missing metrics or one improved score cannot automatically establish a research conclusion; negative results are valid.
- Checkpoint C demonstrates proposal → decision → real run → comparison → human conclusion in the browser.

**Out of scope:** Optionalizing evaluation at closure, model-judge infrastructure, leaderboards, or claiming research improvement from a short training smoke.

## R14: Minimal extension mechanism and permission boundary

**Dependency:** R13 accepted.

Enable a small real extension while keeping capability and failure boundaries explicit.

**Deliverables**

- Specify versioned interfaces/manifests for relevant bricks, evaluators, and providers, including compatibility, declared permissions/dependencies, disable/uninstall, and diagnostics.
- Prove the boundary with an existing small adapter; do not create unused plugin frameworks.
- Keep manifest loading inert; bound subprocess messages, duration, output, and errors; do not pass control-store connections or control-plane secrets.
- Treat reviewed same-user processes as trusted-code execution. Route untrusted code to a verified isolation profile or refuse it.

**Acceptance**

- Crash, hang, excess permissions, and incompatible versions do not corrupt the control plane or increase authority.
- Removing training adapters leaves core startup, offline workflow, and a generic CPU task functional.

**Out of scope:** Marketplace, automatic third-party installs, and calling subprocess separation a malicious-code sandbox.

## R15: Installation, startup, backup, and recovery

**Dependency:** R14 accepted.

Make the workbench usable from an installed package on supported Mac/Linux systems.

**Deliverables**

- Package built frontend assets, minimal examples, and an offline no-key/no-GPU demonstration; users should not require a source checkout or Node.
- Provide explicit workspace initialization, doctor, redacted diagnostics, and supported data migrations.
- Back up a consistent EventStore high-water prefix plus referenced immutable CAS objects; verify integrity when restoring into a new directory.
- Document credential treatment, Worker identity, active-task reconciliation, and downgrade limits. Restore must not automatically relaunch historical tasks.

**Acceptance**

- Clean-install tests outside source cover supported platforms, missing assets, port conflicts, damaged data, and interrupted backup/restore.
- Restored event/artifact digests and research ledger match; diagnostics exclude secrets and are inspectable before sharing.

**Out of scope:** Publishing packages/tags by default, automatic artifact garbage collection, or copying a live SQLite file without consistency handling.

## R16: Independent trials and phase acceptance

**Dependency:** R15 accepted.

Validate the usable product and close only the scope supported by evidence.

**Deliverables**

- Prepare fixed tasks for at least two intended users who did not implement the system; the maintainer handles invitations/authorization.
- Record install/offline journey results, interventions, confusion, and recovery; at least one authorized remote journey must be evidenced.
- Fix main-path defects and rerun affected paths. Aggregate the evidence recorded with each preceding package; do not postpone evidence collection until this package.
- The planning/review assistant prepares the scoped closure ADR and remaining backlog; keep implementation, accepted evidence, and live runtime identities distinct.
- Treat release name/version/tag/publication and new paid activity as separate maintainer decisions.

**Acceptance**

- Independent users complete core journeys; material defects are resolved and remaining limitations are explicit.
- Checkpoint D provides the installed demonstration, trial evidence, acceptance matrix, and scoped closure record for maintainer review.
- Unperformed live work remains pending-live and prevents claiming the corresponding checkpoint complete.

**Out of scope:** Declaring the whole phase complete because code merged, overwriting historical results, or automatically publishing a public service.

## Architecture and existing mechanisms

Retain the modular monolith, SQLite EventStore, CAS, ResearchControl, RunControl,
WorkerPlane, HMAC grants/sessions, and existing process supervision. Extract thin
services under `src/llm_research_os/application/`; keep CLI, Python, and Web as
callers of the same commands. An operation receipt links to domain facts rather
than becoming a parallel execution ledger. Long operations return inspectable
identities; uncertain outcomes are reconciled rather than redispatched.

The proposed Web direction is optional FastAPI/ASGI plus React/TypeScript/Vite,
read-only React Flow, generated types, SSE with bounded polling fallback, and
built assets in the wheel. Lock concrete dependencies during R09/R10; do not
precreate empty modules. Browser sessions and Worker credentials are distinct.
SSH is bootstrap/connectivity around the existing HTTPS Worker protocol.

Control-plane and Worker roots remain separate. Input artifact delivery is
grant-scoped. TLS verification, host-key pinning, secret redaction, parsing
resource budgets, and honest process observations are part of implementation,
not optional documentation promises. Preserve the fixed-noop #81 behavior until
a separately versioned real profile is reviewed. Unsupported required limits
fail closed; reviewed native code and isolated untrusted code are different
trust profiles.

## Legacy subject mapping

This table preserves traceability to PR #80. It does not inherit that draft's
Web-first dependency order. R identifiers above must not be reassigned.

| Original proposal | Current work packages by responsibility |
| --- | --- |
| M3-00 scope and entrypoints | R01 |
| M3-01 application services | R02 |
| M3-02 Web API | R09 |
| M3-03 read-only UI | R10 |
| M3-04 native profile contract | R03; environment preparation elaborated in R04 |
| M3-05 native runtime | R04 preparation, R05 execution, R06 cancellation/recovery |
| M3-06 SSH onboarding | R07 |
| M3-07 two-host faults/transfer | R08; local recovery foundation in R06 |
| M3-08 research/AI workflow | R12 |
| M3-09 Web operations | R11 |
| M3-10 real evaluation | R13; required in this phase |
| M3-11 extension boundary | R14 |
| M3-12 packaging/recovery | R15 |
| M3-13 trials and closure | R16; evidence is added with every package |

## Evidence, Issue #53, and publication

Use the [acceptance matrix](../evidence/m3/acceptance-matrix.md) throughout the
phase. Implementers add candidate evidence in their package PR, including exact
commands, source SHA, platform, outcome, and limitations. The planning/review
assistant reconciles acceptance; after integration add the actual main SHA and
its CI result without changing the original evidence identity. No commit may
claim its own future merge SHA. Preserve history with explicit superseding
records rather than rewriting past outcomes.

[Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53) tracks
native authorization consumption, not every M3 feature. Review it independently
once R03–R06 provide real-profile plan-bound launch, denial, expiry/revocation,
cancellation/unknown, and durable audit evidence. R08 supplies additional remote
proof where relevant to a claim. Closure requires maintainer review of that
checklist; it does not wait automatically for R16 or close automatically at a
package merge. The issue remains open pending the scoped R03–R06 evidence.

Checkpoints A/B/C/D and milestone acceptance do not publish a version or authorize
paid resources. M2 evidence stays accepted in its original scope. M3 two-host
acceptance needs new evidence. If live access is unavailable, finish useful
local work, record pending-live, and request only the missing prerequisite;
Mock, test skipping, and prose cannot substitute for required live validation.

## Validation and handoff rules

Use [engineering standards](../engineering-standards.md) and the current
[CI workflow](../../.github/workflows/ci.yml) for authoritative commands.
Preserve lint, formatting, strict typing, schema/JCS consistency, generated
catalog/status checks, installed-wheel smoke, build, and the unrounded 85%
statement-plus-branch coverage floor. Protocol selection follows CI; designated
OCI and supported-platform process tests retain their separate scope.

Each feature validates its meaningful failure cases as well as success. Add
browser contract/E2E checks with Web work, and measure query/log/artifact behavior
at explicit data volumes before optimizing. For documentation-only R01, check
links, exact package mapping/dependencies, lifecycle status consistency,
translations, generated status, and whitespace; no new runtime tests are needed.
CI success does not by itself establish scope or scientific acceptance.

Assigning the full backlog does not authorize parallel R branches or silent scope
changes. Work sequentially from verified main; each package or smaller slice has
an independently reviewable PR. The implementer handles routine technical choices,
testing, and in-scope repairs without repeated approval requests. The maintainer
controls merges; the planning/review assistant maintains global instructions and
reviews checkpoints. See [governance](../development-governance.md) for file roles.

## Implementation handoff for R02

Read this plan, governance, applicable `AGENTS.md`, CONTRIBUTING, engineering
standards, ADR-0062/0063, and relevant existing contracts. Begin from the latest
verified main after R01 is merged. Do not branch from the old `e1282c5` snapshot
when a newer accepted main exists.

Inspect `research/control.py`, `runs/control.py`, `execution/`, `report/fold.py`,
`storage/`, and existing CLI handlers. Add only the thin shared services required
by R02: workspace/revision operations, validate/diff/dry-run, ledger/Run reads,
and bounded identity-bound command receipts. Reuse existing domain actions for
idempotency tests. Do not implement real native launch or Web to demonstrate R02.
Proposed CLI names become available only with their implementation and tests.

Deliver code, semantic CLI/Python equivalence tests, restart/conflict/cross-project
cases, compatibility notes, package documentation, and an R02 candidate evidence
row. Internal modules may receive small justified changes; a blanket ban on
editing existing controls is not required. Do not weaken their contracts.
Report the branch/head, changed behavior, exact validation outcomes, gaps, and
normative decisions requiring review. R03 follows only after R02 acceptance;
its global profile contract is prepared by the planning/review assistant.

## Sources

- [Charter v0.2](../charter-v0.2.md): accepted research and governance baseline.
- [ADR-0062](../adr/0062-m1-m2-acceptance-and-m3-boundary.md): scoped M1/M2 acceptance.
- [ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md): fixed noop and SSH scaffold.
- [ADR-0054](../adr/0054-process-observation-tristate.md): process observation semantics.
- [ADR-0061](../adr/0061-detached-authorization-attestations.md): audit signatures.
- [PR #81](https://github.com/victorzhong0110/llm-research-os/pull/81): merged first slice.
- [PR #80](https://github.com/victorzhong0110/llm-research-os/pull/80): superseded proposal.
- [Post-#81 CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35449103162): baseline checks.
