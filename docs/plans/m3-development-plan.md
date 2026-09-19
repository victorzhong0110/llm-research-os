# M3 development plan

Planning baseline: `main@e1282c5601e08a0bb46ebe10f8d2eca470b4a015`
(post-`#81` local restricted `NativeProcessRuntime` and SSH onboarding
scaffold). Status: the M3 plan remains **planned**; only the slice 1
implementation in `#81` is merged, and it is not the M3 acceptance, live SSH,
paid cloud, or public MVP.

This file is the repository's single English version of the M3 plan. It
incorporates the plan from PR `#80` and the scope reconciliation done in
R01. It distinguishes accepted constraints, observed implementation, and
recommended additions. Recording the plan does not replace the scope ADR,
acceptance matrix, or current-entrypoint corrections tracked under R01.
New constraints and trade-offs require their own ADR reviews.

## 0. Scope freeze (R01) and current-entrypoint corrections

R01 is this package. It produces scope, task baseline, and entrypoint
corrections only. It does not implement R02–R16. The acceptance matrix for
the remaining packages lives in `docs/evidence/m3/acceptance-matrix.md`.

R01 deliverables:

- A single integrated M3 master plan with R01–R16 work packages, package
  dependencies, deliverables, non-goals, and acceptance conditions. No
  calendar, week-count, or due dates are recorded.
- A `M3-NN ↔ R0X / R1X` mapping (see Section 3) so legacy references to
  `M3-NN` and reviews of PR `#80` still resolve.
- A capability classification table (see Section 4) marking each
  capability as **merged and verified**, **merged but unverified**,
  **planned**, or **pending-live**.
- Current-entrypoint corrections listed under §11 of this plan and
  applied to `CONTRIBUTING.md`, `CONTRIBUTING.zh-CN.md`,
  `docs/guides/first-experiment.md`, the generated status block, and the
  language in `#53`. Historical evidence and dated context in PR `#80`,
  `#79`, `#78`, `#77`, `#73`, and `#54` are preserved.
- Documentation diff checks, link check, generator check (`scripts/project_status.py --check`), whitespace and final-newline checks.
- The relationship with PR `#80` explained in this PR description: this
  work supersedes the original `#80` plan file content by integrating the
  reconciliation onto the post-`#81` snapshot while preserving all of the
  original package intent, deliverables, and non-goals.

R01 non-goals:

- No Web UI, no live SSH, no real native Python execution, no plugins,
  no extension isolation, no ModelProvider integration, no evaluation,
  no startup command, no release, no tags, and no package publication.
- No claim that Issue `#53` is closed or that the M3 slice 1 implementation
  is a live two-host or paid-cloud proof.

## 1. Intended outcome

**M3 should deliver a local research workbench that an individual researcher can
set up, connect to their own machine, and use to complete a reviewable experiment.**

The first user remains the charter's researcher who understands their question
and can read or modify some Python, but lacks mature training infrastructure.
The recommended first profile is single-user, with one project per workspace
and separate storage for independent workspaces. Team permissions, a hosted
control plane, and multi-tenancy are later work.

The complete user journey is:

1. After installation, start the local interface and an example with one command.
2. Complete an offline simulated research loop without a GPU or API key.
3. Import an experiment definition and a source document; inspect an AI proposal,
   its semantic diff, evidence, predictions, risks, and budget.
4. Accept or reject the proposal while preserving dissent, rationale, and
   necessary researcher questions and answers.
5. Connect a user-owned machine through an existing SSH access path and inspect
   the execution profiles that the machine actually supports.
6. Authorize an exact plan, execute a supported task, and inspect state, logs,
   metrics, and artifacts.
7. Reconnect to observe existing work; see evidence of actual stop after
   cancellation; retain `unknown` when execution cannot be established.
8. Compare a baseline and candidate on a fixed evaluation set, record an
   evidence-linked human conclusion, and create a subsequent revision.

Item 8 is a recommended addition to the inherited M3 scope. M2 demonstrates short
training and restore, but its CUDA live records have no `evaluation.metric`
facts. One small real evaluation should make the result useful for a research
decision.

Engineering acceptance produces a release candidate. The public name, version,
tag, package publication, and paid experiments remain separate actions under
existing project rules. Public distribution of local software does not certify
an internet-facing hosted service.

## 2. Verified starting point and gaps

| Area | Observed state at the post-`#81` baseline | Implication for M3 |
| --- | --- | --- |
| Main | `e1282c5`, post-`#81` M3 slice 1 scaffold | Start from current main; historical M2 branches supply evidence only |
| CI on main | `e1282c5` push: Linux OCI integration, Python 3.12/3.13/3.14 (forward-compat) on Ubuntu, Python 3.12/3.13 on macOS, Human authorship on push — passed | Existing CI validates this work; no new test suite required for R01 |
| M1 | ADR-0062 accepts the offline loop; `#38` closed on the accepted scope | Reuse research objects, Mock, budgets, questions, authorization, and reporting |
| M2 | `#73`, `#77`, and `#78` are merged; local/two-host scope is accepted | Reuse Worker and execution lifecycle semantics |
| M3 slice 1 | `#81` merges a local restricted noop `NativeProcessRuntime` plus a SSH onboarding validator with a `pending-live` checklist pack | The slice is implemented and passes existing CI, but it is not entrypoint execution and not a live SSH proof |
| Two-host live evidence | Windows/WSL2 + Docker Engine: CPU, reconnect, cancellation, CUDA 20 steps, 22 uploaded files, and full-state 10-to-12 restore | Do not relabel this evidence as native Linux or paid-cloud validation |
| Mac/MPS | A separate LoRA process-group profile has live evidence | Preserve its platform boundary; this is not the generic NativeProcessRuntime |
| Worker authorization | HMAC grants/sessions, expiry, revocation, plan binding, remote consumption, and idempotent claim/complete exist | Do not rebuild Worker identity, leases, or revocation |
| Signatures | `#78` supplies detached Ed25519 AuthorizationAttestation | Verification still reports `launchAllowed=false`; signatures are not launch authority |
| Issue `#53` | Open, narrowed in `#79` to NativeProcessRuntime authorization consumption | An explicit remaining M3 deliverable; this plan does not close `#53` |
| UI | Static HTML/Markdown reports | Add service entrypoints, browser authority boundaries, APIs, and interaction |
| Evaluation | CUDA live records have no real evaluation metrics; synthetic metrics and static views exist | Add one fixed, reproducible evaluation loop |
| Unverified scope | Paid-cloud spend is CNY 0; no dedicated two-host unknown live experiment | Local acceptance cannot certify cloud cost controls; add dedicated two-host unknown evidence |
| Documentation | README status block is generated; parts of CONTRIBUTING, first-experiment, and the threat-model superscription retain earlier status | Correct current entrypoints; preserve dated evidence and its original outcomes |

Sources: [ADR-0062](../adr/0062-m1-m2-acceptance-and-m3-boundary.md),
[ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md),
[M2 acceptance matrix](../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md),
[Issue `#53`](https://github.com/victorzhong0110/llm-research-os/issues/53),
[Issue `#38`](https://github.com/victorzhong0110/llm-research-os/issues/38),
[slice 1 PR `#81`](https://github.com/victorzhong0110/llm-research-os/pull/81),
[plan PR `#80`](https://github.com/victorzhong0110/llm-research-os/pull/80),
and [post-`#81` main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35449103162).

## 3. Mapping from M3-NN to R0X / R1X work packages

| Plan entry | Work package | Title | Mapped from | Lifecycle |
| --- | --- | --- | --- | --- |
| §0 | **R01** | Scope freeze and current-entrypoint corrections | (this PR; new) | **This PR** |
| §6.1 | **R02** | Shared application services and workspaces | M3-01 | Planned |
| §6.2 | **R03** | Web API and input boundaries | M3-02 | Planned |
| §6.3 | **R04** | First read-only research interface | M3-03 | Planned |
| §6.4 | **R05** | Native execution profile and authorization contract | M3-04 | Planned |
| §6.5 | **R06** | NativeProcessRuntime and Issue `#53` real profile | M3-05 (with merged slice 1 in `e1282c5`) | Partly merged |
| §6.6 | **R07** | SSH onboarding and doctor | M3-06 (with merged scaffold in `e1282c5`) | Partly merged |
| §6.7 | **R08** | Two-host faults and recovery | M3-07 | Planned |
| §6.8 | **R09** | Research workflow and AI proposal interaction | M3-08 | Planned |
| §6.9 | **R10** | Web execution, cancellation, and restore | M3-09 | Planned |
| §6.10 | **R11** | Minimal real evaluation, comparison, and conclusion | M3-10 (recommended addition) | Planned |
| §6.11 | **R12** | Minimal extension boundary | M3-11 | Planned |
| §6.12 | **R13** | Packaging, startup, and recovery diagnostics | M3-12 | Planned |
| §6.13 | **R14** | External trials and milestone closure (matrix publication) | M3-13 deliverable A | Planned |
| §6.14 | **R15** | Evidence index and scope acceptance matrix | M3-13 deliverable B | Planned |
| §6.15 | **R16** | M3 closure ADR and version/publication gate | M3-13 deliverable C | Planned |

R06 reuses the fixed noop helper from `#81`; the real reviewed Python profile
and pre-CAS denial evidence are R06 work. R07 reuses the SSH onboarding pack
writer from `#81`; SSH transport execution, `STATUS.json` flipping from
`pending-live` to `live`, `ONBOARDING.md` / `ACCEPTANCE.md` progression, and
two-host fault evidence are R07 work. R16 closes the milestone by accepting the
matrix and linking release/citation to a separate decision; R16 never publishes
by itself.

## 4. Capability classification

Each row classifies a capability into one bucket, says where the
evidence lives, and notes the first package that advances or accepts it.

- **merged-and-verified** — implemented, integrated on `main`, and verified
  by passing CI plus the package's test suite.
- **merged-but-unverified** — implemented, integrated on `main`, and the
  unit/component test passes, but its live two-host, paid-cloud, or public
  two-user behavior is not yet recorded.
- **implemented-but-pending-live** — the code path exists locally; the
  pack, evidence file, or status field remains `pending-live`.
- **planned** — design exists in this file or its cited ADR/protocol; the
  code path is not yet added.

| Capability | Status | Evidence / pack | First package to advance |
| --- | --- | --- | --- |
| Offline M1 research loop (`m1 prove`) | merged-and-verified | `tests/test_m1_checkpoint.py` | (accepted) |
| Deterministic Mock proposal / question / decision / dissent | merged-and-verified | M1-0..M1-2 tests | (accepted) |
| Local Markdown/PDF evidence import with digest-only facts | merged-and-verified | M1-3 tests + examples | (accepted) |
| OpenAI-compatible generate adapter + CNY budget facts | merged-and-verified | M1-4 tests + examples | (accepted) |
| Synthetic `training.step` / `evaluation.metric` facts | merged-and-verified | M1-5 tests + `runs report` | (accepted) |
| Local `SimulatedRuntime` with one `{eventId, sequence}` consume | merged-and-verified | M1-6 + `test_authorization_consume.py` | (accepted) |
| Static HTML/Markdown Run report | merged-and-verified | `runs report` + `tests/test_run_report.py` | (accepted) |
| Loopback Worker long-poll, HMAC grants, expiry, revoke | merged-and-verified | M2-0 tests + WSL2 fault matrix | (accepted) |
| `execute.local` host-Python helper | merged-but-unverified (loopback only) | `tests/test_worker_protocol.py` | (accepted) |
| `execute.oci` digest-pinned CPU OCIContainerRuntime | merged-but-unverified (Linux OCI CI only) | `tests/test_worker_oci.py` + OCI CI | (accepted) |
| WSL2 + Docker Engine two-host CPU, reconnect, cancel | merged-but-unverified (closed WS) | `docs/evidence/m2-wsl2-cuda-live/` | (accepted) |
| WSL2 + Docker Engine CUDA 20-step + 10→12 restore | merged-but-unverified (cuda.11 only) | `cuda.7` / `cuda.11` matrix rows | (accepted) |
| Detached Ed25519 AuthorizationAttestation | merged-and-verified (offline) | `tests/test_auth_attestation.py` + ADR-0061 | (accepted) |
| macOS / MPS LoRA training profile | merged-but-unverified (MPS LoRA only) | `docs/evidence/m1-m2-maintenance/` | (accepted) |
| Local restricted noop `NativeProcessRuntime` (transport=local) | merged-and-verified (`#81`) | `tests/test_native_process_runtime.py`, ADR-0063, TM-064 | (merged; no live two-host) |
| Native SSH onboarding pack (validator + writer) | implemented-but-pending-live (`#81`) | `tests/test_native_ssh_onboard.py`, ADR-0063, TM-065 | R07 |
| `transport=ssh` execution on this slice | merged-and-verified as **refused** | `tests/test_native_process_runtime.py::ssh refusal past authorization` | R07 |
| Restricted-profile real Python entrypoint execution | planned | R06 design and tests | R05 / R06 |
| Two-host live evidence (SSH + WSL2 / Darwin / Linux native) | planned | new `docs/evidence/m3/` pack | R07 / R08 |
| Web backend (FastAPI + SSE) | planned | R03 design | R03 |
| React/TypeScript/Vite read-only UI | planned | R04 design | R04 |
| Real proposal → decision → Run → evaluation path | planned | R09 / R10 / R11 | R09 |
| Minimal real evaluation and comparison | planned | R11 design | R11 |
| Extension subprocess protocol + first evaluated adapter | planned | R12 design | R12 |
| Installed-wheel startup, demo, doctor, backup/restore | planned | R13 design | R13 |
| External trials | planned | R14 design | R14 |
| Evidence index and acceptance matrix publication | planned | R15 design | R15 |
| M3 closure ADR + version/publication gate | planned | R16 design | R16 |
| Paid-cloud provider spend | not planned; spend stays ¥0 | n/a | deferred (independent approval) |
| Public MVP / multi-tenant / marketplace | not planned | n/a | deferred |

`M3-13` is split into three reviewable items (R14, R15, R16) because the
matrix publication, the trials, and the closure ADR have different
acceptance audiences and different reviews.

## 5. Scope and priority

| Priority | Work | Acceptance treatment |
| --- | --- | --- |
| Required by the accepted boundary | SSH onboarding live execution, restricted non-OCI profile with real Python, NativeProcessRuntime consume evidence, Web UX, external trials, parsing resource limits, and plugin isolation | Inherited from ADR-0062; do not silently omit at closure |
| Required enabling work | Shared application services, immutable revisions, command idempotency, problem contracts, projections, packaging, diagnostics, and recovery | Necessary to make the inherited outcome usable |
| Recommended addition | One real evaluator, baseline/candidate comparison, and an evidence-linked conclusion | Record explicitly in R15 |
| If capacity remains | A few common parameter forms, limited comparison filters, and additional training views | Must not block the complete loop or create a second experiment definition |
| Deferred | Editable DAG canvas, multi-tenancy, cloud account creation/provisioning, multi-cloud scheduling, a second large training backend, distributed scheduling frameworks, plugin marketplace, vector storage and automatic literature crawling, general autonomous-agent orchestration, and parameter self-evolution | Record future needs; do not prebuild empty frameworks in M3 |

React, TypeScript, Vite, and React Flow are an accepted direction. The charter
requires read-only views before editing and does not require an editable canvas
for the first public MVP. One user-owned GPU path, the already validated training
backend, and one lightweight evaluator are sufficient to test the first outcome.
See [charter sections 14.5 and 18, and erratum E7](../charter-v0.1.md).

## 6. Recommended architecture

| Decision | Recommendation | Reason and boundary |
| --- | --- | --- |
| Core | Retain the modular monolith, SQLite EventStore, and CAS | Existing event semantics remain the fact source |
| Application services | Add a thin `application/` layer shared by CLI, HTTP, and SDK | Reuse ResearchControl, RunControl, WorkerPlane, budget, and evidence logic; adapters cannot bypass the kernel |
| Web backend | FastAPI + ASGI as an optional `web` extra | Fits Python/Pydantic; core CLI and Workers need not install Web or training dependencies; lock versions during implementation |
| Frontend | React + TypeScript + Vite; read-only React Flow | Nodes/edges derive from ResearchSpec; layout stays outside its semantic digest |
| Type generation | Generate protocol TypeScript types from published JSON Schema | Do not hand-maintain another ResearchSpec; OpenAPI wraps HTTP, while the server retains semantic validation |
| Live updates | SSE and bounded queries, with polling fallback | The browser primarily consumes changes; reconnect from a cursor without adding a broker |
| Browser authority | Loopback, same-origin access, a local session, and cross-site mutation protection | Binding to localhost alone does not authorize arbitrary browser writes |
| Worker interface | Retain HTTPS/JSON and `rg1`/`ws1` | Browser sessions and Worker credentials remain separate; no simultaneous rewrite of the verified Worker HTTP server |
| SSH | System OpenSSH and existing trusted Host configuration | Onboarding and connectivity use SSH; tasks still use the Worker protocol |
| Native execution | Explicit profiles behind NativeProcessRuntime; R06 advances from the merged noop helper (#81) to a reviewed-Python profile | Reuse process observation/stop; report enforceable constraints honestly |
| Community extensions | Subprocess message protocol; verified OCI boundary for untrusted code | Process separation isolates crashes, not all same-user filesystem or network authority |
| Validation | Existing Python/OCI gates, generated contracts, a small browser E2E suite, and two-host live evidence | Verify failure behavior and authority boundaries instead of inflating snapshot counts |
| Distribution | A standard wheel containing built frontend assets and minimal examples | End users do not need Node; training dependencies remain in the Worker environment |

FastAPI supports modular API routers; React Flow exposes separate controls for
dragging, connecting, and selecting, which suits an initial read-only view.
References: [FastAPI](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
and [React Flow](https://reactflow.dev/api-reference/react-flow).

```mermaid
flowchart TD
    UI["Local Web"] --> API["Session and HTTP API"]
    CLI["CLI and Python SDK"] --> APP["Shared application services"]
    API --> APP
    APP --> K["Existing research and execution kernel"]
    K --> FACTS["EventStore and CAS"]
    K --> WP["Worker protocol"]
    SSH["SSH onboarding and tunnel"] -. "Connectivity" .-> WP
    WP --> NATIVE["Constrained Native profile"]
    WP --> OCI["Existing OCI and GPU profiles"]
```

Neither the browser nor SSH becomes a separate fact source. Cancellation,
recovery, budget, and authorization continue through the same kernel.

## 7. Delivery checkpoints

| Checkpoint | Packages | Observable outcome |
| --- | --- | --- |
| A: Inspect | R02–R04 | Browser access to real events, research ledger, Run details, and the experiment graph |
| B: Connect and control | R05–R08 | Native execution, user-owned SSH host, recovery, and unknown evidence |
| C: Complete research | R09–R11 | Proposal, decision, execution, evaluation comparison, and human conclusion |
| D: Independent use | R12–R14 + R15–R16 | Extension boundary, installable package, clean installation, external trials, evidence index, and the closure ADR |

The first usable read-only interface should appear after Checkpoint A. R15 must
precede any release tag and R16 must approve it; neither auto-publishes.

## 8. Sequential work packages

Every package below is **planned** except R01, which is **this PR** and any
already-merged slice listed in §4. The default is one PR per package. Split a
package into sequential A/B slices if implementation exceeds roughly three
days or becomes difficult to review independently. Merge the prior slice with
maintainer approval and verify actual main CI before starting the next branch.
Do not recreate a long stack of unmerged implementation branches.

### R02: Shared application services and workspaces

**Dependency:** R01.

**Deliverables:** Thin application entrypoints to explicitly create/open a
workspace, read its project, save immutable ResearchSpec revisions, invoke
validate/diff/dry-run, and query the research ledger and Runs. Reuse
`research/control.py`, `runs/control.py`, `execution/`, `report/fold.py`, and
existing storage. Extract only logic required by the new surfaces.

A workspace binds project identity, EventStore, CAS, configuration, and operation
state. Normalize/check paths and reject accidental sharing of control-plane and
Worker roots. The application acts as the existing kernel's caller and supplies
id/time/streamid; preserve explicit identity requirements in low-level APIs.

Define command identity, request digest, the reviewed event head/revision, and a
durable operation receipt. Repeating the same command/content returns its prior
result; reusing an ID with different content fails; stale revisions produce a
conflict. Link receipts to events/artifacts; EventStore remains authoritative
for execution facts. Register payload schemas if new events are needed instead
of introducing an unauditable hidden fact source.

Long operations have recoverable status. After a crash, rebuild facts and pending
receipts rather than treating a browser spinner as evidence of failure. Do not
add Celery or Redis for the first implementation.

**Acceptance:** CLI/application calls have identical semantic digests; revisions
survive restart; conflicts are visible; retries do not create duplicate Runs;
cross-project references fail; core imports and operates without training
extras. Define compatibility with existing SQLite schema v2; new tables or
migrations must preserve historical event digests.

### R03: Web API and input boundaries

**Dependency:** R02.

**Deliverables:** A local API, structured problems, projection reads, and SSE.
The proposed namespace is `/api/v0alpha1`, distinct from Worker `/v0alpha1`.
Initially expose reads, validation, and previews; introduce domain mutations
individually in R09/R10. Do not expose generic event append or arbitrary command
execution endpoints.

Add same-origin local sessions, Host/Origin checks, CSRF protection for
mutations, and clear authentication failures. A browser session cannot mint its
own Worker authority. Hosted remote mode is outside the default profile.
Credentials and sessions must stay out of ordinary logs, exported facts, and
problem bodies.

Enforce body, nesting, node, time, and concurrency limits during parsing.
Existing YAML depth/node checks largely happen after composition; an 8 MiB source
cap alone does not establish service memory isolation. Use a bounded parsing
process or composer-phase budgets at new remote-facing entrypoints, and test
JSON, YAML, and PDF through their actual parsing paths. Stricter ingress limits
must not prevent historical EventStore replay.

Freeze initial route limits in this package: suggested ordinary JSON limit
1 MiB; specs no larger than the existing 8 MiB ceiling; artifacts use a separate
streaming route and the applicable existing profile bound. Bound aggregate
memory, temporary disk, concurrent uploads, and user quotas using measured
failure cases to set final values.

SSE replays project-scoped cursors without double-counting, and snapshots include
their high-water sequence. A lagging client can reload a snapshot. Preserve
existing heartbeat and metric-storage semantics; do not append every high-rate
sample to the fact log. Read bounded/downsampled data from metric chunks.

**Acceptance:** Cross-site mutation, invalid origins, missing authentication,
wrong-project access, oversized/deep inputs, hostile Markdown/HTML, slow clients,
and duplicate requests have explicit outcomes. SSE reconnect catches up. API
errors do not disclose credentials, arbitrary paths, or input bodies.

### R04: First read-only research interface

**Dependency:** R03.

**Deliverables:** React/TypeScript/Vite frontend, generated protocol types, and
generation-drift CI. Minimal views: workspace home, research ledger, Run detail,
machine state, and a read-only experiment graph. Reuse report folds on the server;
the frontend does not implement another Run state machine.

Run details show training, evaluation, system, cost, and lineage. State when data
is absent; do not insert zeros, bridge missing series, or relabel synthetic
curves as real. Expose platform/evidence scope. Distinguish unknown, lost, failed,
cancel-requested, and cancel-observed.

The graph supports zoom, selection, and definition inspection. Layout changes
cannot mutate ResearchSpec. A statically displayable workflow may still be
unsupported for execution; show that limitation and disable execution for it.

**Acceptance:** Read actual locally generated M1/M2 records; refresh and restart
preserve state; dissent and decision rationale are discoverable; evidence links
resolve to event IDs or authorized artifacts. Verify small-screen, keyboard,
empty-state, and failure behavior. This delivers checkpoint A.

### R05: Native execution profile and authorization contract

**Dependency:** R04.

**Deliverables:** An ADR defining the first constrained NativeProcessRuntime
profile beyond the merged `#81` noop helper, pre-launch consumption, capability
mapping, and platforms. Review existing `process.native`/`execute.local` meanings
rather than silently expanding an existing capability into arbitrary host
execution. Publish requests, reports, and valid/invalid examples.

Bind project/Run/Attempt/task, spec/registry/plan/authorization-decision digests,
code artifact digest, interpreter and environment inventory digest,
configuration/input digests, profile version, and resource bounds. An interpreter
path alone does not prove the environment is unchanged.

The recommended first post-`#81` profile executes Python tasks explicitly reviewed
by the user on a local or user-owned machine. Enforce and report process-group
supervision, constrained argv, minimal environment, bounded streams, timeout,
and stop observation. For network, filesystem, and memory limits distinguish
requested, enforced, and unsupported. Do not claim host isolation that is absent.
If policy requires denied network or host access and the platform cannot enforce
it, reject that path and use a supported OCI profile.

This executable profile is not the historical non-launching preflight's fulfilled
promise and is not the `#81` noop helper. Preserve both; separately version and
authorize the actual runtime profile.

Use the trusted control plane and existing Worker grant lifecycle, including for
local execution semantics. Ed25519 verifies facts and is not sufficient launch
authority. Specify the authorization/launch linearization point: revocation
before the gate denies launch; revocation after it enters cancellation/observation
instead of claiming the process never ran.

**Acceptance:** Specify testable denial for wrong project, stale revision,
substituted code/interpreter, expiry/revocation, replayed nonce, incorrect profile,
and unsupported required isolation.

### R06: NativeProcessRuntime real profile and Issue `#53`

**Dependency:** R05.

**Deliverables:** Compose the formal runtime from existing Worker authorization,
binding, recovery, `sandbox.py`, and `supervise.py`, extending the noop helper
merged in `#81`. Merely renaming the host-Python helper does not complete this
package, and the merged noop helper is not the profile that closes `#53`.

Before launch, verify the consumed grant, frozen inputs, and profile. Use a fixed
interpreter/runner and constrained argv; never concatenate configuration into a
shell command. Materialize code/inputs from verified CAS; do not import task
entrypoints in the control-plane process. Record process group, start identity,
stream bounds, and observed termination.

Design the handshake and recovery rules across authorization consumption,
durable launch intent, child creation, durable execution identity, and beginning
user code. In particular, cover a child existing before its identity is saved.
If launch cannot be established, retain unknown and never automatically redispatch
the same Attempt. The goal is to avoid duplicate execution and recover honestly,
not to promise generic exactly-once effects across processes.

**Acceptance:** Success, nonzero exit, timeout, output flood, leftover descendants,
PID reuse, denied authorization, pre-launch file substitution, cancellation races,
and crashes at each persistence boundary. Run real process tests for supported
Linux/macOS profiles. Issue `#53` becomes eligible for closure only after the
runtime's consume, denial, cancellation, and audit evidence is integrated and
the real-profile launch path is recorded in `docs/evidence/m3/`.

### R07: SSH onboarding and doctor

**Dependency:** R06.

**Deliverables:** Extend the merged SSH onboarding pack writer (`#81`) into a
planned, diagnosable, repeatable onboarding flow: probe, produce
installation/connection plan, apply, verify. Freeze actual CLI names in this
package; names in this plan are proposed interfaces.

Use the user's existing trusted SSH Host/agent and verify the host fingerprint.
Do not collect private keys in Web forms. Probe OS, architecture, Python, disk,
GPU/Docker/MPS capabilities, output ownership, network path, and compatibility.
Explain missing prerequisites with concrete repair guidance. Default onboarding
does not run sudo, install system drivers, or modify firewalls.

Install a pinned wheel/locked environment under a user-owned directory and verify
version/digest. Repeated apply must be safe; do not overwrite a mismatched
environment in place. Preserve installation diagnostics. Send remote
configuration through bounded files or stdin. Local `shell=false` does not
prevent SSH's remote shell from interpreting a command: use fixed remote
templates without interpolating user-supplied paths or options.

Support two explicit connectivity profiles: HTTPS on an existing private network,
or a reverse tunnel over existing SSH that binds only to remote loopback. The
Worker still initiates HTTPS requests. No new Worker application listener is
needed; the user must already have SSH access to that host.

Diagnose loopback binding, host verification, forwarding setup failure, liveness,
and reconnection. A successfully created forward does not prove that its target
service is reachable: verify the actual HTTPS handshake and Worker registration.
Certificate SAN must match the Worker's connection name; never disable TLS
verification. References: [OpenSSH configuration](https://man.openbsd.org/ssh_config)
and [SSH forwarding](https://man.openbsd.org/ssh).

The merged `STATUS.json` from `#81` stays `pending-live` until a researcher
provisions a host in R07 and the corresponding pack flips its status to `live`
under a separate reviewable PR.

**Acceptance:** Clean remote onboarding, wrong host fingerprint/certificate,
missing Python, permissions, full disk, incompatible versions, port conflict,
and disconnection are diagnosable. Control SQLite/CAS/TLS private key do not enter
the Worker root. Repeated installation does not duplicate registration or launch
training. SSH transport execution does not regress `#81` ssh refusal.

### R08: Two-host faults and recovery

**Dependency:** R07.

**Deliverables:** Validate the new onboarding path on two real machines, first
with a small CPU task and then one existing GPU profile. Use new authorization
and execution identities; never reuse cuda.1-11. Create an independent evidence
pack recording commit, package identity, both environments, profile, inputs, and
event/artifact digests.

Required fault points: disconnect before claim; SSH tunnel loss during execution;
control-plane restart; Worker restart; interrupted artifact upload; lost complete
response after upload; cancellation while disconnected; and unknown caused by
unavailable process identity observation. Reconnect resumes observation, upload,
or receipts without spawning claimed work again.

Resolve checkpoint delivery explicitly. M2 demonstrates upload and control-side
verification, while Worker GET of ordinary artifact blobs remains restricted by
design. Control-plane-to-Worker checkpoint delivery requires a task-authorized
input materialization/download path; never open the whole CAS. If only
Worker-cached checkpoints are supported, the UI and acceptance must state the
limitation and verify their integrity.

The recommendation is to implement grant-scoped checkpoint input transfer: verified
control-plane artifact to the designated Worker and new Run/Attempt. Retain
profile file-count/size bounds. File-level retry is an adequate first resumption
mechanism; do not expand immediately to arbitrary large objects.

**Acceptance:** Every fault has events, real process/container observation, and
residual-executor checks. Record dedicated two-host unknown evidence. A cancel
request is not displayed as stopped; full-state restore remains distinct from
adapter loading; an Attempt never gets a second training process. Checkpoint B
is complete after this package.

### R09: Research workflow and AI proposal interaction

**Dependency:** R08.

**Deliverables:** Workspace creation, evidence import, proposal, dissent,
questions, decisions, and new revisions through shared services. Supply an
end-to-end deterministic Mock path and connect the existing OpenAI-compatible
adapter for user-configured models. M1 already supplies low-level `ai.call` and
research facts; this package adds orchestration that validates generated output
before turning it into a reviewable proposal.

Every proposal binds a base revision, complete candidate spec in CAS,
server-computed semantic diff, evidence, predictions, falsification conditions,
risk, and budget. Models cannot grant authority or make researcher decisions.
Invalid schema or unresolved references produce a visible failure/pending repair,
not execution. An AI edit first produces a draft.

Preserve human rationale and overridden dissent. Use `question.asked` and
`question.answered` for necessary information, explaining why the unknown matters
to the decision. Reuse `ai.call.*` and `budget.*`; an uncertain dispatched request
must not release its reservation and retry indefinitely.

Display evidence origin, snapshot, and permitted uses. Reading permission does
not imply training permission. Browser excerpts use authorized, bounded artifact
reads rather than embedding whole private sources into events.

**Acceptance:** Complete the Mock journey with no key. Validate real HTTP
interaction against a local compatible server. Rejection queues no Run; stale
proposals cannot overwrite later revisions; hostile evidence cannot invoke tools
or change permissions; refresh preserves decisions. Paid external-model trials
have separate budgets and are not prerequisites for offline acceptance.

### R10: Web execution, cancellation, and restore

**Dependency:** R09.

**Deliverables:** Show dry-run, execution profile, target Worker, actually
enforced constraints, resources/budget, and actions awaiting authorization.
Accepting a research proposal and authorizing execution are distinct business
states even if the UI guides the user through them consecutively.

Execution accepts only a frozen, currently valid plan identity. Start, cancel,
and restore use R02 receipts. Double-clicks, retransmission, timeouts, and
multiple tabs must not duplicate dispatch. Return Run/operation identity and
query facts for progress.

For unknown or lost work, offer reconnect/observe-existing-work actions. A new
attempt requires explicit handling of the old Attempt, new authority/decisions,
and a valid state transition. Restore shows checkpoint digest and restore mode;
unsupported profiles fail closed.

**Acceptance:** Browser E2E covers start, duplicate clicks, stale plans,
cancel-requested versus observed stop, offline reconnect, completion recovery
after upload, and domain errors. UI, CLI, and replay agree on state.

### R11: Minimal real evaluation, comparison, and conclusion

**Dependency:** R10.
**Scope status:** Recommended addition recorded in R15.

**Deliverables:** One deterministic evaluator and fixed evaluation set, using the
already validated small-model/ms-swift path. Install evaluation dependencies on
the Worker while retaining an independent core. No model judge, external
leaderboard, or second training framework is required.

Record data digest, split, rights, model/tokenizer versions, evaluator version,
and configuration first. A useful first example computes token-weighted held-out
loss/NLL and retains a small set of outputs for identical inputs. Add exact match
only for a task with a clear scoring definition. Do not mix training and
evaluation data. A short LoRA run's negative result is valid; model improvement
is not an engineering acceptance condition.

Compare a baseline model and one candidate checkpoint. Recompute aggregates from
bounded detail artifacts; show sample count, missing/failed cases, metric
direction, and aggregation definition. Mark differing evaluator/configuration
results as not directly comparable instead of simply plotting them together.

Keep execution narrow. Training and evaluation may be two Runs with explicit
artifact dependency, coordinated by a bounded application recipe and linked
report. Do not first build a general DAG scheduler; graph visibility does not
make an unsupported multi-node workflow executable.

Conclusion drafts cite actual metrics, event IDs, and artifact digests. Humans
record supported, not supported, or insufficient-evidence judgments while
retaining dissent. If a separate conclusion object is introduced, version its
schema; do not insert new values into the existing `Decision.outcome` enum. A
minimal implementation can link a conclusion artifact to existing Run decisions
and review facts.

**Acceptance:** A small CPU case validates the evaluator protocol. On one
supported hardware profile, perform real baseline/candidate evaluation. Keep
synthetic and real results distinct; recomputation matches the report; absent
metrics never imply a supported hypothesis. This completes checkpoint C.

### R12: Minimal extension boundary

**Dependency:** R11.

**Deliverables:** A versioned subprocess protocol, manifest/capability
negotiation, timeout, output limits, problem mapping, and conformance examples
for the first external adapter. Choose a small extension without paid effects,
such as an evaluation-output converter. Defer a marketplace and automatic
discovery/installation.

Manifest loading remains inert and cannot import external entrypoints. Do not
pass EventStore connections, control-plane keys, or arbitrary host file handles
to an extension. Minimize its environment and mediate external access through
policy-controlled paths.

Claim only the isolation T2 actually provides. A same-UID subprocess can still
access user files and networking; it is not a malicious-code sandbox. Untrusted
arbitrary code requires OCI or another verified OS boundary. If unavailable,
reject the extension rather than silently falling back to host execution.

**Acceptance:** Crash, hang, output flood, excess capabilities, and incompatible
versions do not corrupt the control plane. Route high-risk plugins into enforced
isolation or refuse them. Removing ms-swift leaves the core, offline demo, and
generic Python brick usable. Pass this gate before accepting the first community
adapter.

### R13: Packaging, startup, and recovery diagnostics

**Dependency:** R12.

**Deliverables:** Include built Web assets, offline templates, and examples in the
wheel. Proposed post-install entrypoint: `researchos start --demo`; this command
does not exist merely because the plan names it. Make workspace creation explicit
and never overwrite a conflicting existing path. Startup should not require a
source checkout, Node, training frameworks, or hand-edited protocol JSON files.

Doctor reports versions, ports, disk, workspace structure, Worker connectivity,
certificates, and supported execution capabilities with actionable remedies.
Diagnostics export is field-redacted and inspectable before sharing.

Backup freezes an EventStore high-water mark and enumerates immutable CAS objects
referenced by that prefix; do not copy a live SQLite file casually. Restore to a
new directory and verify events/objects. Restoring a database does not restart
old tasks. If upgrades require a schema migration, back up first and document
downgrade compatibility. Automatic artifact GC is out of scope.

**Acceptance:** Clean Apple Silicon Mac and Linux installations run the built
package outside the checkout, without Node or training extras. Diagnose port
conflicts, damaged workspaces, missing static files, interrupted backups, and
restore failures. Successful restore preserves digests and the research ledger.

### R14: External trials

**Dependency:** R13.

**Deliverables:** At least two people matching the intended audience who did not
implement the system independently follow the documentation through the offline
journey. At least one also connects a user-owned remote host and runs a small
task. The maintainer arranges invitations; the plan does not send messages.

Record failed steps, elapsed time, developer interventions, hand-edited settings,
unclear diagnostics, and misunderstood conclusions. Fix main-path blockers and
repeat affected paths rather than indiscriminately rerunning every test.

**Acceptance:** Both trial users finish the offline journey within the time bound
without developer file edits, and at least one completes the SSH + small-task
leg. Record elapsed time, interventions, and hand-edited settings. Update the
matrix and accept-or-defect the affected packages before R15 publication.

### R15: Evidence index and acceptance matrix publication

**Dependency:** R14.

**Deliverables:** Publish `docs/evidence/m3/acceptance-matrix.md` and an
`index.md` enumerating every M1/M2 acceptance, M3 slice evidence, two-host
records, and each R-package's per-matrix row. Do not relabel evidence across
packages; keep accepted-evidence, implementation, and live-execution SHAs
distinct. Update English README and its Chinese translation, getting-started
documentation, and generated status.

**Acceptance:** Every R02–R14 row in the matrix has at least one cited evidence
path. The generated status block reproduces the matrix's status assignments.
No new execution capability is claimed by the matrix; packages that remain
incomplete are explicitly marked.

### R16: M3 closure ADR and version/publication gate

**Dependency:** R15.

**Deliverables:** A closure ADR (next available number) records the actual
accepted scope, the matrix reference, hardware matrix, limitations, and live
execution SHAs. The ADR does not publish, tag, or release by itself.

**Acceptance:** The closure ADR explicitly enumerates M3 acceptance, the
remaining deferred items, and the separation between engineering completion and
publication. The release/version decision is a separate reviewable action and
cannot be initiated from R16. `Issue #53` closes only after R06 evidence and the
closure ADR are both integrated; R16 does not decide the publication form.

## 9. Proposed code and interface placement

Confirm paths and names against the code during each slice. Do not create empty
modules in advance.

| Location | Responsibility | Packages |
| --- | --- | --- |
| `src/llm_research_os/application/` | Workspaces, shared commands, receipts, bounded workflow coordination | R02, R09, R10, R11 |
| `src/llm_research_os/web/` | Sessions, API, SSE, static-asset entrypoint | R03, R13 |
| `web/` | React UI, generated types, frontend checks | R04, R09, R10, R11 |
| `execution/` and `workers/` | Native profile, authority binding, execution, recovery | R05, R06, R08 |
| SSH module under `workers/` | Onboarding plan, probe, install, tunnel, diagnostics | R07 |
| `evaluation/` or one adapter module | Evaluator contract, comparison, detailed artifacts | R11 |
| `plugins/` or adapter-boundary module | External process protocol and conformance | R12 |
| `tests/` and frontend test directories | Contract, fault, real-process, and focused browser tests | With each slice |
| `docs/protocols/` and `docs/guides/` | External contracts, usage, limitations | With each slice |
| `docs/evidence/m3/` | Evidence index, environments, acceptance, limits | R08, R11, R15 |

Organize API operations around project/revisions, proposals/dissents/questions/
decisions, plans, runs, workers, artifacts, and event streams. Long model/start/
stop operations return an operation identity and inspectable result instead of
blocking request handling for minutes. Reads use projections; each mutation maps
to an existing or explicitly introduced domain command.

## 10. Public-MVP acceptance mapping

All rows below describe **planned evidence**, not completed M3 checks.

| Charter section 14.5 condition | Implementation | Required evidence |
| --- | --- | --- |
| 1. One-command Mac/Linux startup | R13 installed package and demo entrypoint | Clean-install records on both platforms |
| 2. Complete simulation without GPU | R09/R13 | Offline, no-key, no-training-extras accept/reject flow |
| 3. Connect a user-owned remote GPU | R07/R08/R10 | New two-host onboarding, GPU profile, task and authorization identities |
| 4. Inspect the same experiment definition | R02/R04 | YAML/SDK/UI refer to the same revision and semantic digest; read-only graph creates no separate spec |
| 5. Review every AI change | R09 | Diff, evidence, predictions, risk, and budget; invalid references rejected |
| 6. Human rejection and preserved dissent | R09 | Rejection creates no Run; rationale/dissent survive refresh |
| 7. Stop and distinguish execution states | R06/R08/R10 | Actual process exit, reconnection, and independent unknown evidence |
| 8. Complete result lineage | R04/R08/R11 | Verifiable data, code, environment, configuration, sources, and output digests |
| 9. Core survives training-adapter removal | R12/R13 | Installed wheel, simulation, and generic Python brick without ms-swift |
| 10. Versioned core contracts and tests | Every slice | Generated schema, valid/invalid examples, generated TS, and semantic contracts agree |

Additional M3 gates: Native consumption evidence for `#53`; input resource
boundaries; extension isolation; at least two target-user trial records; and the
recommended real evaluation comparison if adopted in R15.

## 11. Current-entrypoint corrections (R01 execution checklist)

Each item below is part of this R01 PR and is verified by `git diff` against
the post-`#81` main:

1. `CONTRIBUTING.md` and `CONTRIBUTING.zh-CN.md`: replace "current phase is
   the M1 research-assistant loop" with the post-acceptance entrypoint
   (M1/M2 accepted; M3 work starting from `#81` slice 1). Preserve
   `uv sync --locked --all-groups` and the CI recipe; preserve the
   `S` / `PT011` rules.
2. `docs/guides/first-experiment.md`: remove "Charter v0.2" and the
   `NativeProcessRuntime (preflight still forbids launch)` items from the
   "still not a release" list. Add a pointer to the merged M3 slice 1
   guide (`docs/guides/m3-native-process-runtime.md`) and the SSH
   onboarding guide (`docs/guides/m3-native-ssh-onboarding.md`).
3. `docs/status.json`: update only the `NativeProcessRuntime` row text
   from "in progress" to "slice 1 merged (ADR-0063, `#81`); SSH
   execution refused; live SSH and real-profile launch remain
   planned." Leave `baseline` and `acceptedEvidence` unchanged
   (ADR-0062 accepted-evidence identity is preserved).
4. `CHANGELOG.md`: under "Unreleased", record this PR as the integrated
   plan refresh. Preserve the existing M3 slice 1 entry.
5. `Issue #53`: do not close or modify in this PR. R01 only updates
   documentation; R06 evidence closes it.
6. `docs/plans/m3-development-plan.md`: this file. R01 owns it.
7. `docs/evidence/m3/`: R01 publishes a stub `acceptance-matrix.md` that
   enumerates the R02–R16 rows and references existing evidence; the
   actual rows are filled incrementally by R15.
8. `README.md` and `README.zh-CN.md`: add a link to this plan and to
   `docs/evidence/m3/acceptance-matrix.md` in the "Project documents"
   list. Keep the generated status block intact; rely on
   `scripts/project_status.py` to regenerate from `docs/status.json`.
9. ADR index: do not open a new ADR in this PR. The plan is the R01
   deliverable; ADRs ship with the package that introduces a constraint
   (charter §23 E10).

## 12. Validation and success measures

### Validation layers

| Layer | Checks | Limitation |
| --- | --- | --- |
| Pure models/properties | Digest, schema, diff, state machine, authority binding, idempotency/conflicts, references | Does not prove actual stop or remote networking |
| Local integration | Installed package, API, SSE, real child process, restart, backup/restore, absent training extras | Does not prove SSH or remote GPU |
| Browser E2E | Offline journey, reject, duplicate click, stale plan, cancellation request, errors/empty states | Does not replace executor evidence |
| Designated Linux OCI CI | Real containers and live faults; missing runtime is failure | Does not certify MPS, WSL CUDA, or paid cloud |
| Two-host live | SSH/TLS, independent roots, CPU, disconnect, cancel, unknown, artifacts, one GPU path | Does not generalize to every cloud or GPU |
| External trial | Install, understand, complete, diagnose, count interventions | Two participants are not a statistically representative sample |

Run relevant behavior checks and repository gates for each change. Preserve the
unrounded 85% statement-plus-branch coverage floor, ruff, formatting, mypy,
generated schemas, JCS conformance, event catalog/status generation, wheel build,
and installed-wheel smoke. Required protocol selection follows current CI's
`not oci_live and not slow`; designated OCI runs separately. Add frontend build,
type checks, generated-contract drift, and essential E2E checks.

R01 runs documentation-only validation:

- `scripts/project_status.py --check`
- `uv run ruff check . && uv run ruff format --check .` (a dry-run on the
  planned change set)
- Markdown link check covering `README.md`, `README.zh-CN.md`,
  `CONTRIBUTING.md`, `CONTRIBUTING.zh-CN.md`, the new plan file, the new
  acceptance-matrix stub, and the guides/protocols they reference.
- Whitespace and final-newline checks against touched files.

R01 does **not** expand the runtime test suite.

### Suggested measurement targets

| Measure | Target | Measurement boundary |
| --- | --- | --- |
| First offline result | Within 5 minutes after template initialization | Exclude installation download; separate system and reading time |
| New-user offline journey | Both trial users finish within 15 minutes without developer file edits | Prerequisites installed; documentation allowed; report each result without population-level claims |
| First SSH onboarding | Within 20 minutes when prerequisites exist; no hand-filled tokens/multiple protocol JSON files | Record environment/model download time separately |
| Denied launch | Zero launches for denied, stale, mismatched identity/digest cases | Within the declared fault/live matrix |
| Duplicate dispatch | Zero extra starts for the same command/Attempt in the fault matrix | No generic exactly-once promise |
| Honest state | Unknown and cancel-requested never appear as success/stopped in acceptance cases | Compare events and real executor observation |
| UI freshness | Suggested P95 event-to-view at most 2 seconds | Fixed host/data volume; disconnections measured separately; not an existing SLA |
| Interactive query | Suggested P95 at most 300 ms for common queries at 10k events; bounded behavior at 100k | Establish R03 baseline; optimize projections/paging before changing databases |
| Attention cost | Count manual inputs, blocking questions, repeated authorization, and developer interventions | Reduce questions the system can resolve; retain necessary research decisions |
| Real evaluation | Recompute one baseline/candidate comparison from detail artifacts | Negative outcomes are acceptable; quality improvement is not a gate |

## 13. Risks and responses

| Risk | Early signal | Response |
| --- | --- | --- |
| UI duplicates the kernel | Frontend/routes independently decide authorization, budgets, or Run state | Shared services and CLI/API semantic-contract checks |
| Native isolation is overstated | Documentation promises no network but code only cleans env or starts a process group | Report actual enforcement; reject unmet policy; distinguish reviewed and untrusted code |
| Browser retries duplicate work | A timed-out POST simply creates a new Run | Stable commands, durable receipts, consumed grants, launch handshake, observation on uncertainty |
| SSH becomes another executor | Training runs directly through SSH and its exit code substitutes for Worker facts | Keep SSH in onboarding/connectivity; execute through Workers |
| UI hides missing research evidence | A green experiment-success label appears without evaluation | Separate execution completion and conclusion review; show missing evidence |
| Old docs override current state | Contributors follow M1 or generic pending-live guidance | Correct current entrypoints, date history, link successors, keep generated status authoritative |
| Platform scope expands prematurely | Work shifts into multi-cloud, marketplaces, tenancy, or arbitrary DAGs | Return to the four checkpoints; put additions into backlog |
| Manual packaging remains hidden | UI launch still requires editing several request/grant JSON files | Application services prepare identities/configuration/dependencies; retain an expert export path |
| Restore prerequisites are incomplete | UI offers resume while the checkpoint exists only on control CAS | Deliver grant-scoped input transfer in R08 or explicitly block unsupported restores |
| Evidence is relabeled to new code | Historical hardware evidence is shown as a pass on the latest SHA | Record implementation SHA, build digest, and live-runtime SHA independently |

## 14. Collaboration and PR rules

Retain the maintainer's existing workflow: sequential packages, contributors
implement, and the maintainer controls merges. Update this allocation only when
the maintainer changes it.

1. R01 (this PR) prepares the integrated plan, the R01-R16 work-package
   mapping, the capability classification, the current-entrypoint corrections,
   and the acceptance-matrix stub. R01 does not implement any other package.
2. Each subsequent package is implemented against the R01 baseline and
   describes alternatives when an accepted constraint needs to change.
3. R01 reviewer (`@victorzhong0110`) reviews diffs, failure behavior,
   evidence, language, and documentation consistency and provides concrete
   corrections.
4. Each PR is independently reviewable; merge requires maintainer
   confirmation. Do not auto-merge or use an administrator bypass.
5. After squash integration, check actual main CI before starting the next
   implementation branch from main.

Code, maintained protocols/ADRs/guides, and commit messages use English.
README and CONTRIBUTING retain synchronized Chinese translations. This file
is the maintained English plan; do not add a second complete Chinese
engineering-plan copy to the repository.

R01 does not require review-only permissions outside the existing ruleset.

## 15. R02 handoff for the next implementer

```text
Repository: victorzhong0110/llm-research-os
Work package: R02 — shared application services and workspaces (was M3-01)

Start from the latest verified main after R01 is integrated. Use the
R01 acceptance matrix stub at docs/evidence/m3/acceptance-matrix.md and
append R02's per-package row only after the package lands; do not edit
prior package rows.

Read applicable CONTRIBUTING.md, docs/engineering-standards.md,
docs/charter-v0.2.md, charter v0.1 sections 14.5 and 18 with incorporated
errata, ADR-0062, ADR-0063, the M2 acceptance matrix, Issue #53, this
plan, and the relevant protocols before editing.

Goal:
Introduce a thin application/services layer that exposes the existing
kernel (research/control, runs/control, execution, report/fold, evidence
import, authorization, budget) as explicitly identity-bound operations
on a workspace that owns a single project identity, EventStore, CAS, and
configuration. Reuse Worker HMAC grants, expiry, revocation, and leases;
reuse the merged noop NativeProcessRuntime only as a reference executor
for restricted-profile tests; do not implement R05/R06 design yet.

Deliver:
1. New `src/llm_research_os/application/` package with workspace open/save,
   immutable revision save, validate/diff/dry-run, and research-ledger
   reads. Each command returns an identity-bound, durable operation
   receipt that links to events/artifacts.
2. Plan-authorization, native-preflight reuse from R02 onwards; do not
   bypass.
3. A `researchos` CLI subcommand to demonstrate each new application
   path under tests/.
4. The first per-package row in docs/evidence/m3/acceptance-matrix.md,
   citing the merged R01 plan as the package plan and pointing at the
   test paths.

Constraints:
- One sequential package. No Web, SSH, native runtime, evaluation, or
  plugin implementation in this PR.
- Reuse Worker HMAC grants, expiry, revocation, and leases; do not
  introduce a parallel authority store.
- Fact signatures (ADR-0061) and the noop native preflight (ADR-0063)
  are not launch authority.
- Preserve low-level identity, digest, and append-only event contracts.
- Distinguish accepted evidence identities from the latest docs SHA.
- Mark proposed CLI/API names as proposed, not available functionality.
- Do not merge, change protection, tag, publish, provision a host, or
  start live training/model calls.

Validation:
Run `uv run ruff check . && uv run ruff format --check . && uv run mypy
src && uv run pytest --cov=llm_research_os --cov-fail-under=85 && uv run
researchos schema --check-all`. Use existing PR CI. Do not fabricate live
evidence or add mirror tests for documentation edits. Report exact
commands/outcomes. Begin R03 only after maintainer-approved integration
and successful actual main CI.
```

## 16. Supporting material

Repository implementation was inspected at the post-`#81` baseline.
Recommendations and capability classifications are engineering judgments,
not completed implementation or accepted ADRs.

- [Charter v0.2](../charter-v0.2.md): retained research and governance constraints.
- [ADR-0062](../adr/0062-m1-m2-acceptance-and-m3-boundary.md): accepted checkpoints
  and explicit M3 deferrals.
- [ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md): merged slice 1
  constraints; this plan treats the noop helper and SSH pack writer as
  implemented-but-pending-live.
- [M2 live matrix](../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md): platform,
  restore, upload, evaluation, and unknown evidence limits.
- [ADR-0008](../adr/0008-native-process-and-oci-runtimes.md): dual runtimes and
  non-launching native preflight.
- [ADR-0009](../adr/0009-worker-semantics-independent-of-transport.md) and
  [ADR-0021](../adr/0021-remote-worker-transport.md): semantic Workers and SSH
  bootstrap; their pending-live language describes their historical slices.
- [ADR-0061](../adr/0061-detached-authorization-attestations.md): signed facts
  versus execution authority.
- [Research decision protocol](../protocols/research-decision-objects-v0alpha1.md):
  proposal, dissent, decision, question/answer, and field constraints.
- [WorkerPlane](../../src/llm_research_os/workers/plane.py) and
  [supervision](../../src/llm_research_os/workers/supervise.py): existing lease,
  consume, process-observation, and recovery boundaries.
- [Input parsing](../../src/llm_research_os/spec/io.py) and
  [threat model](../security/threat-model.md): local bounds and service gaps.
- [Engineering standards](../engineering-standards.md) and
  [CI workflow](../../.github/workflows/ci.yml): language, slices, coverage, and
  packaging gates.
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53):
  remaining M3 NativeProcessRuntime authorization consumption; closed only by
  R06 evidence and R16 closure.
- [Plan PR #80](https://github.com/victorzhong0110/llm-research-os/pull/80):
  the original M3 plan; this R01 PR supersedes its plan file while preserving
  the original section structure and package intent.
- [Slice 1 PR #81](https://github.com/victorzhong0110/llm-research-os/pull/81)
  and [main CI for `e1282c5`](https://github.com/victorzhong0110/llm-research-os/actions/runs/35449103162):
  merged noop helper and SSH onboarding scaffold; live SSH and entrypoint
  execution remain R05–R08 work.
