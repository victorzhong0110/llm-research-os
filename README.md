# LLM Research OS

> Canonical English README. Chinese translation: [README.zh-CN.md](README.zh-CN.md)
> (keep both in the same pull request; [ADR-0040](docs/adr/0040-english-primary-and-engineering-standards.md)).
>
> The current name is a working title. The public name will be confirmed by ADR
> before a public release.

LLM Research OS is an independent, open-source, model-neutral, training-backend-neutral,
and compute-provider-neutral operating system for LLM research. It is used to state
research questions, compose experiments, let AI propose and contest plans, execute
on local or remote Workers, and record training, evaluation, system, cost, lineage,
and AI decisions.

It serves the period in which human help remains necessary for AI: it turns the
information and the authority a researcher supplies into cheap, high-information,
durable, auditable facts. The researcher is a teacher, not only an approver
([ADR-0039](docs/adr/0039-human-help-period-purpose.md)).

## Current status

Project charter v0.1 and chapter 18 are the accepted baseline. **The M0 kernel
proof closed on 2026-09-03**; scope is
[ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md); the native-process milestone
erratum is [ADR-0034](docs/adr/0034-m0-scope-clarification.md). Post-closure
charter errata, M0 debt, and the M1 slice order, security gates, checkpoint, and
budget are in [ADR-0038](docs/adr/0038-charter-errata-after-m0.md) and charter §23.
The field-level contract for M1-1 research decision objects is
[research-decision-objects-v0alpha1](docs/protocols/research-decision-objects-v0alpha1.md).
M1-0 is in tree: schema v2 query tables and a verified high-water cache
([ADR-0041](docs/adr/0041-verified-high-water-cache-and-query-tables.md)), typed
[`SecretRef`](docs/protocols/secret-ref-v0alpha1.md), optional ResearchEvent
actor `kind` / `modelId`, and SimulatedRuntime emission of `attempt.cancelled` /
`run.cancelled`. M1-1 lands `proposal.submitted`, `dissent.recorded`,
`decision.recorded`, a rebuildable `ResearchLedger`, and the matching CLI.
M1-2 lands [`ModelProvider`](docs/adr/0017-minimal-model-interface.md), a
deterministic mock, and `ai.call.*` digest facts (never inline prompt/output).
M1-3 lands local Markdown/PDF import as `evidence.imported` with default
`LicenseRef-Unknown`. PDF extraction is bounded in a subprocess with a minimal
worker environment. M1-4 lands an
OpenAI-compatible HTTP adapter (loopback default) gated by `SecretRef`,
`read.external_api`, HTTPS, a positive remote CNY cap/reserve, and atomic
budget reserve-or-exceed. M1-5 emits seeded synthetic
`training.step` / `evaluation.metric` facts and `researchos report RUN`
static HTML/Markdown (React Flow deferred). M1-6 lets SimulatedRuntime consume
one local `{eventId, sequence}` citation of `plan.authorization.evaluated`
([ADR-0042](docs/adr/0042-m1-local-authorization-consume-and-closure.md)); that
is not a signed launch JWT. Issue #19's local consume is delivered; signatures,
expiry, and revocation are [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53).
The question channel is `question.asked` / `question.answered` with
`questions ask` / `questions answer`. `researchos m1 prove` records one offline
corpus chain (Mock proposal through simulated report, or reject without a Run).
Umbrella #38 stays open. Numbered slices are not the M1 checkpoint.
M2-0 is a free loopback Worker CPU loop
([ADR-0043](docs/adr/0043-m2-loopback-worker-and-hmac-grants.md)): HMAC
grants with expiry/revoke bound to an authorized `execute.local` brick,
CAS-pinned python helper, artifact + report. Isolated control-plane and
Worker processes use pinned loopback HTTPS
([ADR-0044](docs/adr/0044-isolated-control-plane-and-loopback-https.md));
that is not a cross-machine proof. Remote Worker transport is
[ADR-0021](docs/adr/0021-remote-worker-transport.md): a pending-live pack
with independent EventStore/CAS roots (`secondHost: not-provisioned`),
not a two-host run. CPU OCIContainerRuntime is a
digest-pinned docker adapter ([ADR-0045](docs/adr/0045-cpu-oci-container-runtime.md));
a missing engine fails closed and is not a mocked success. Worker
stop/fault recovery is [ADR-0046](docs/adr/0046-worker-stop-fault-recovery.md):
a cancel request is not a stopped process; completed work reconciles
Run/Attempt; unknown cannot auto-succeed. Observed execution identity is
[ADR-0050](docs/adr/0050-observed-execution-identity.md). Live CPU fault
acceptance is [ADR-0051](docs/adr/0051-live-cpu-fault-acceptance.md):
`plane.fail` is not a stop. EventStore 10k/100k baseline
and CAS metric chunks are [ADR-0047](docs/adr/0047-eventstore-performance-and-metric-sampling.md);
bench receipts are not SLA. It is not GPU
completion, not NativeProcessRuntime, not a kernel sandbox, and not Issue #38.

Delivered capabilities include: ResearchSpec / ResearchEvent / BlockManifest
protocol foundations, a pure static planning kernel, a SQLite append-only event
fact store with rebuildable query tables, a local content-addressed artifact
object layer, a pure Run/Attempt state machine, RunControl that preflights
before write with global CAS, a GPU-free and network-free deterministic
SimulatedRuntime that can consume a cancel request, a plan-authorization gate
bound to three digests, a non-credential authorization CLI, audit-only
evaluation events, read-only lineage, in-process `decisionDigest`, a local
`{eventId, sequence}` consume on SimulatedRuntime, explicit
simulated-run / cancellation-request / artifact-object / research-decision /
mock-model-call / evidence-import / OpenAI-compat / static-report /
M1-checkpoint CLIs, a non-launching NativeProcessPreflight, loopback Worker
registration / HMAC grants / `researchos m2 prove`, a host-python helper that
is not NativeProcessRuntime and not a kernel sandbox, and a CPU
`OCIContainerRuntime` adapter that fails closed without a live digest-pinned
image.

`researchos m2 bench` records 10k/100k EventStore timings (not SLA).
`researchos m2 usage` measures the Worker/RunControl path (not that fill).

The tree still does not execute training jobs or real GPU workloads. Authorization
events, preflight reports, lineage rebuilds, and `decisionDigest` are not signed
receipts or launch permits. SimulatedRuntime does consume one local
`{eventId, sequence}` citation of the audit fact on this EventStore (ADR-0042);
lineage stays `not-consumed`. A cancellation-request CLI still does not send a process signal;
the observed cancelled outcome is a later SimulatedRuntime fact. A real
NativeProcessRuntime, non-loopback Workers, paid GPU, and JWT launch
credentials are not M0 or M1 deliverables. M2-0 loopback CPU is in tree
([ADR-0043](docs/adr/0043-m2-loopback-worker-and-hmac-grants.md)). Isolated
loopback HTTPS is ADR-0044 and is not a cross-machine Worker. CPU OCI is
ADR-0045 and is not a live GPU proof. Designated Linux OCI CI (ADR-0049)
must not skip; ordinary hosts without docker may skip `oci_live`. Worker
stop/fault recovery is ADR-0046. EventStore performance baseline is ADR-0047.
Pinned ms-swift parse/plan is ADR-0048 and is not a GPU run.
Worker/RunControl usage evidence is ADR-0052 (`m2 usage` is not `m2 bench` fill).
The GPU experiment sheet is ADR-0053 (named AutoDL 4090 combo, unpaid).
Process observation is ADR-0054 (running/exited/unknown; failed probes
are not exited). Live OCI faults are ADR-0055: designated Linux CI runs
every `oci_live` test; inspect failure is unknown. Independent GPU
execution is ADR-0056 (`gpu-oci-container` / `execute.gpu`; `gpu-not-run`).
Data snapshot and checkpoint collect is ADR-0057 (Hub revision, pending-live
dataset SHA, overlay resume; not a CUDA result).

## M0 goals

The historical goals below were closed by
[ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md). The list is kept as the
acceptance checklist of that milestone.

1. Short ADRs and a living threat model;
2. Pydantic models for `ResearchSpec v0alpha1`;
3. Versioned JSON Schema with valid and invalid examples;
4. A validator and semantic diff;
5. CloudEvents-compatible `ResearchEvent`;
6. A minimal SQLite fact store and `SimulatedRuntime`;
7. A first vertical loop with no GPU.

## Accepted baseline

- Python 3.12+, `pyproject.toml`, uv;
- Pydantic is the M0 authoring entry; versioned JSON Schema is the external contract;
- Append-only events, rebuildable projections, content-addressed artifacts;
- An independent Research IR, not a shell around NeMo, ms-swift, or an agent framework;
- The researcher has the final decision by default; AI may and should file dissent;
- Any real GPU spend, external-account action, or irreversible operation still
  needs a separate approval.

## Project documents

- [Project charter and minimal kernel spec v0.1](docs/charter-v0.1.md) (Chinese original)
- [Chapter 18 decision guide v0.1](docs/chapter-18-decision-guide-v0.1.md) (Chinese original)
- [Engineering standards](docs/engineering-standards.md)
- [Changelog](CHANGELOG.md)
- [ResearchSpec v0alpha1](docs/protocols/research-spec-v0alpha1.md)
- [ResearchEvent v0alpha1](docs/protocols/research-event-v0alpha1.md)
- [Research decision objects v0alpha1](docs/protocols/research-decision-objects-v0alpha1.md)
- [SecretRef v0alpha1](docs/protocols/secret-ref-v0alpha1.md)
- [ModelProvider / ai.call v0alpha1](docs/protocols/model-provider-v0alpha1.md)
- [Evidence import v0alpha1](docs/protocols/evidence-import-v0alpha1.md)
- [OpenAI-compatible generate / budget v0alpha1](docs/protocols/openai-compat-v0alpha1.md)
- [Synthetic metrics and static Run report v0alpha1](docs/protocols/run-report-v0alpha1.md)
- [BlockManifest v0alpha1](docs/protocols/block-manifest-v0alpha1.md)
- [DryRunReport v0alpha1](docs/protocols/dry-run-report-v0alpha1.md)
- [Block command report v0alpha1](docs/protocols/block-command-report-v0alpha1.md)
- [ProblemReport v0alpha1](docs/protocols/problem-report-v0alpha1.md)
- [Semantic content digest v0alpha1](docs/protocols/digest-v0alpha1.md)
- [Run/Attempt state v0alpha1](docs/protocols/run-attempt-state-v0alpha1.md)
- [SimulationRequest v0alpha1](docs/protocols/simulation-request-v0alpha1.md)
- [RunCancellationRequest v0alpha1](docs/protocols/run-cancellation-request-v0alpha1.md)
- [ArtifactObjectReport v0alpha1](docs/protocols/artifact-object-report-v0alpha1.md)
- [PlanAuthorizationRequest/Report v0alpha1](docs/protocols/plan-authorization-v0alpha1.md)
- [PlanAuthorizationEventRequest v0alpha1](docs/protocols/plan-authorization-event-v0alpha1.md)
- [PlanAuthorizationLineageQuery/Report v0alpha1](docs/protocols/plan-authorization-lineage-v0alpha1.md)
- [NativeProcessPreflightRequest/Report v0alpha1](docs/protocols/native-process-preflight-v0alpha1.md)
- [Static planning kernel guide](docs/guides/m0-static-planning.md)
- [M0 SQLite event store](docs/guides/m0-event-store.md)
- [M0 local artifact store](docs/guides/m0-artifact-store.md)
- [M0 RunControl](docs/guides/m0-run-control.md)
- [M0 deterministic plan-authorization gate](docs/guides/m0-plan-authorization.md)
- [M0 explicit plan-authorization CLI](docs/guides/m0-plan-authorization-cli.md)
- [M0 plan-authorization evaluation events](docs/guides/m0-plan-authorization-events.md)
- [M0 plan-authorization lineage](docs/guides/m0-plan-authorization-lineage.md)
- [M0 Native Process Preflight](docs/guides/m0-native-process-preflight.md)
- [M0 SimulatedRuntime](docs/guides/m0-simulated-runtime.md)
- [M0 Simulated Run CLI](docs/guides/m0-simulated-run-cli.md)
- [M0 Run Cancellation CLI](docs/guides/m0-run-cancellation-cli.md)
- [M1 research decision CLI](docs/guides/m1-research-decisions.md)
- [M1 ModelProvider mock CLI](docs/guides/m1-model-provider.md)
- [M1 evidence import CLI](docs/guides/m1-evidence-import.md)
- [M1 OpenAI-compatible generate CLI](docs/guides/m1-openai-compat.md)
- [M1 synthetic metrics and static Run report](docs/guides/m1-run-report.md)
- [M1 checkpoint CLI](docs/guides/m1-checkpoint.md)
- [Worker protocol v0alpha1](docs/protocols/worker-v0alpha1.md)
- [Authorization grant v0alpha1](docs/protocols/authorization-grant-v0alpha1.md)
- [M2 Worker CLI](docs/guides/m2-worker.md)
- [M2 CPU OCI](docs/guides/m2-oci.md)
- [M2 GPU slice (direction only)](docs/guides/m2-gpu-slice.md)
- [First experiment](docs/guides/first-experiment.md)
- [Architecture decision records](docs/adr/README.md)
- [Living threat model](docs/security/threat-model.md)
- [Contributing](CONTRIBUTING.md)

## Local development

Python 3.12+ and [uv](https://docs.astral.sh/uv/). Training backends are not
installed into the core control-plane environment.

```bash
uv sync --locked --all-groups
uv run researchos validate examples/valid/minimal.yaml
uv run researchos blocks list
uv run researchos dry-run examples/valid/minimal.yaml
uv run researchos schema --check-all
uv run ruff check .
uv run mypy src
uv run pytest --cov=llm_research_os --cov-fail-under=85
node conformance/digest/verify.mjs
```

Generated JSON Schema is the language-neutral contract for third-party implementers:

```text
schemas/research-spec/v0alpha1.schema.json
schemas/research-event/v0alpha1.schema.json
schemas/block-manifest/v0alpha1.schema.json
schemas/block-command-report/v0alpha1.schema.json
schemas/dry-run-report/v0alpha1.schema.json
schemas/problem-report/v0alpha1.schema.json
schemas/run-state/v0alpha1.schema.json
schemas/simulation-request/v0alpha1.schema.json
schemas/run-cancellation-request/v0alpha1.schema.json
schemas/artifact-object-report/v0alpha1.schema.json
schemas/plan-authorization-request/v0alpha1.schema.json
schemas/plan-authorization-report/v0alpha1.schema.json
schemas/native-process-preflight-request/v0alpha1.schema.json
schemas/native-process-preflight-report/v0alpha1.schema.json
```

Do not edit these files by hand. `researchos schema --check-all` checks every
committed schema against the CLI contract registry; a new contract is registered
once in `src/llm_research_os/cli/contracts.py`. After changing a Pydantic authoring
model, regenerate with the matching `--contract` and review the protocol diff:

```bash
uv run researchos schema --output schemas/research-spec/v0alpha1.schema.json
```

## Static dry-run

```bash
uv run researchos dry-run examples/valid/minimal.yaml --format json
```

`ready` only means the spec, block resolution, ports, resources, and static plan
are complete. It does not mean the experiment is approved, executed, or
scientifically correct. Loops are not expanded, `until` is not evaluated, and
config and approval bodies enter the report only as digests.

Additional block manifests are read only from ordinary YAML/JSON files or a
non-recursive directory the user names explicitly:

```bash
uv run researchos blocks validate examples/manifests/example-train.yaml
uv run researchos dry-run examples/valid/bounded-loop.yaml \
  --registry examples/manifests/example-train.yaml
```

## Plan-authorization gate

`authorize_plan` re-validates a ready report semantically and binds the
authorization policy to `specDigest`, `registryDigest`, and `planDigest` at once.
Declared capabilities and permissions must be granted exactly; every requirement
the planner produced must be approved explicitly. Missing grants or a denial yield
`denied`; missing approvals yield `pending`; only `authorized` may enter an
execution path. The gate does not authenticate the approver, persist a decision,
or emit events or runtime side effects. See
[M0 deterministic plan-authorization gate](docs/guides/m0-plan-authorization.md).

External callers can evaluate the exact plan regenerated from the current inputs
with a versioned request:

```bash
uv run researchos authorize \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  --format json
```

`authorized` exits `0`; a valid `pending`/`denied` exits `1`; input or digest-binding
errors exit `2`. The report always declares `not-authenticated`, `not-persisted`,
and `not-executed`. It is not a signed or revocable authorization receipt. See
[M0 explicit plan-authorization CLI](docs/guides/m0-plan-authorization-cli.md).

For append-only audit, a second strict request records the recomputed result into
an already-existing EventStore:

```bash
uv run researchos authorizations record \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  examples/plan-authorization-events/valid/minimal.json \
  research.db --format json
```

The command fully verifies the event store first, then appends one
`plan.authorization.evaluated` under global head CAS. `authorized` exits `0`; a
recorded `pending`/`denied` exits `1`; input, integrity, or concurrency errors
exit `2`. The event declares `not-authenticated`, `audit-only`, and
`not-executed`, so it is a replayable audit fact, not a runtime credential. See
[M0 plan-authorization evaluation events](docs/guides/m0-plan-authorization-events.md).

The same plan identity can then be rebuilt from matching audit facts by a
read-only query, without promoting them to a Run reference or a launch credential:

```bash
uv run researchos authorizations find \
  examples/plan-authorization-lineage/valid/minimal.json \
  research.db --format json
```

Exit `0` only means a frozen event prefix was rebuilt; `matchCount` may be `0`.
The report always declares `not-authenticated`, `audit-only`, `not-executed`, and
`not-consumed`. See
[M0 plan-authorization lineage](docs/guides/m0-plan-authorization-lineage.md).

## Native-process preflight

A single, already-authorized Python task may enter pure preflight, not process
execution:

```bash
uv run researchos native preflight \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  --registry examples/native-process-preflight/manifest.yaml \
  --format json
```

Preflight re-validates the ready plan, the sealed registry, three-digest
authorization, and the authorization decision digest. It accepts only a fixed
JSON-stdio runner, `shell=false`, network denied, an empty environment allowlist,
an isolated temporary workspace request, and bounded output/timeout. Exit `0`
only means the report is reviewable; the report is always `launchAllowed=false`,
`isolation=not-enforced`, `execution=not-executed`, and the entrypoint appears
only as a digest. The command does not resolve an interpreter, import a module,
create a workspace, start a process, send a signal, or write durable storage.
See [M0 Native Process Preflight](docs/guides/m0-native-process-preflight.md).

## Event query and replay

Read-only commands open an existing SQLite database. They do not create a missing
path and they do not append events:

```bash
uv run researchos events get research.db evt.example.1 --format json
uv run researchos events list research.db --after-sequence 0 --limit 100
uv run researchos events replay research.db --page-size 100
uv run researchos events verify research.db --format json
```

`replay` writes JSON Lines and freezes the high-water mark at start, so events
appended during the run do not enter this result.

## RunControl

`RunControl` replays and preflights Run/Attempt lifecycle events against a frozen
global head before writing to the EventStore, then uses `expected_last_sequence`
as global CAS. It does not generate `id`/`time`/`streamid`, does not retry
conflicts, and does not execute any block. After a CAS failure the caller must
`append` again so replay and validation run on the new head.

## SimulatedRuntime

`SimulatedRuntime` re-runs dry-run on a frozen ResearchSpec snapshot, calls the
plan-authorization gate through a fixed T0 `simulate` capability policy, consumes
the cited local authorization row, and appends Run/Attempt lifecycle events through
RunControl only when the plan is a single `simulated.experiment@0.1.0` whose config
names `outcome` explicitly. `id`/`time`/`streamid` and the authorization citation
are still supplied by the caller; conflicts are not retried; `unknown` is not
collapsed into failure or success. A simulated `completed` only means a controlled
lifecycle ended, not that training succeeded or a hypothesis held. Create the
EventStore, record the authorization fact, then simulate. A minimal runnable
example is in [M0 SimulatedRuntime](docs/guides/m0-simulated-runtime.md).

The command-line vertical loop uses a separate explicit request file. It does not
generate `id`, `time`, or `streamid`:

```bash
uv run researchos runs simulate \
  examples/valid/minimal.yaml \
  examples/simulation-requests/valid/success.json \
  research.db --format json
```

JSON stdout is a `RunSnapshot` constrained by the published schema. Exit `0` only
means the simulated lifecycle `completed`; `failed`, `unknown`, and `unresolved`
exit `1`; input, integrity, or concurrency errors exit `2`. The facts can then be
checked independently with `events verify` / `events replay`.

Cancelling an existing Run or an active Attempt requires another explicit request.
The command only appends a `*.cancel.requested` fact. It does not send a process
signal and it does not emit a `*.cancelled` outcome:

```bash
uv run researchos runs cancel \
  examples/run-cancellation-requests/valid/run.json \
  research.db --format json
```

The database must already exist; a missing path is not created. Exit `0` only
means the cancellation-request fact was committed. Inspect
`RunSnapshot.cancellationRequested`; do not claim the job has stopped.

One command records the offline research chain the M1 checkpoint names. It does
not close Issue #38:

```bash
uv run researchos m1 prove \
  examples/m1-checkpoint \
  research.db \
  --format json
```

`--decision reject` records the same research facts and must not queue a Run.
See [M1 checkpoint CLI](docs/guides/m1-checkpoint.md).

One command records a loopback Worker CPU loop (CAS brick, artifact, report).
It does not spend GPU and does not close Issue #38:

```bash
uv run researchos m2 prove \
  examples/m2-checkpoint \
  research.db \
  --format json
```

See [M2 Worker CLI](docs/guides/m2-worker.md),
[M2 CPU OCI](docs/guides/m2-oci.md),
[M2 performance baseline](docs/guides/m2-perf.md), and
[first experiment](docs/guides/first-experiment.md).

Research proposals, dissents, decisions, and questions are separate EventStore
facts. The database must already exist. `accept` is not a launch credential.
An answer is data with rights, not an instruction:

```bash
uv run researchos proposals submit \
  examples/research-decisions/valid/proposal-submit.json \
  research.db --format json
uv run researchos dissents record \
  examples/research-decisions/valid/dissent-record.json \
  research.db --format json
uv run researchos decisions record \
  examples/research-decisions/valid/decision-record.json \
  research.db --format json
uv run researchos questions ask \
  examples/research-decisions/valid/question-ask.json \
  research.db --format json
uv run researchos questions answer \
  examples/research-decisions/valid/question-answer.json \
  research.db --format json
uv run researchos research ledger research.db \
  --project example-minimal --format json
```

A deterministic mock model call is a pair of EventStore facts. Prompt and
output text stay in the fixture file:

```bash
uv run researchos models generate \
  examples/model-generate-requests/valid/generate.json \
  research.db \
  --fixture examples/model-fixtures/valid/generate-json.json \
  --format json
```

An OpenAI-compatible local server is the default HTTP path (cap `0.00` CNY).
Prompt and completion stay off the event; budget facts are recorded:

```bash
uv run researchos models generate \
  examples/openai-compat-requests/valid/local.json \
  research.db \
  --fixture examples/model-fixtures/valid/compat-local.json \
  --format json
```

Local Markdown or PDF notes become `evidence.imported` facts. The file path and
extracted text stay off the event. PDF extract is subprocess-isolated with page,
character, wall-clock bounds, and a minimal worker environment:

```bash
mkdir -m 700 artifacts
uv run researchos evidence import \
  examples/evidence/valid/import-markdown.json \
  research.db \
  --source examples/evidence/sources/eval-split.md \
  --artifacts artifacts \
  --format json
```

A success SimulationRequest may also name `training.step` and
`evaluation.metric` identities. The report is a static projection:

```bash
uv run researchos report run.simulated \
  --database research.db \
  --format markdown
```

A local artifact object root must be created first. Import and full verification
both return a versioned object report and never print object bodies:

```bash
mkdir -m 700 artifacts
uv run researchos artifacts put artifacts checkpoint.bin --format json
uv run researchos artifacts verify artifacts \
  sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --format json
```

`put` does not overwrite an existing object whose digest conflicts; `verify`
fully recomputes the digest and does not repair corruption. Neither writes
SQLite, emits a ResearchEvent, nor assigns project/Run, media-type, or URI
semantics to the object.

## Current security boundary

The M0 kernel proof is closed ([ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)).
The boundary below is still a security fact of the current code; closure does not
erase it.

M0 currently validates protocols and diffs, compiles a side-effect-free static
plan, and uses a three-digest-bound pure authorization gate to deny ungranted
capabilities, permissions, or approvals item by item. It can append, query, and
replay event facts in local SQLite, import ordinary local files into a
content-addressed artifact directory, reject illegal lifecycle events before write
through RunControl, and append deterministic lifecycle facts for a single built-in
simulated task through SimulatedRuntime.
`authorize` only reconstructs the static plan and prints a versioned evaluation
report that is explicitly not a credential; it writes no events, artifacts, or
database.
`authorizations record` may append an exact four-digest-bound evaluation fact to
an existing event store, but the actor is still unauthenticated, the event is
audit-only, and no runtime may launch from it.
`native preflight` only freezes the fixed process-review shape of a single task,
explicitly forbids launch, and does not enforce the declared isolation.
`runs simulate` only hands a strict local request to that existing boundary and
does not retry conflicts.
`runs cancel` likewise appends a single request fact through RunControl, requires
an existing database, and neither signals nor infers a cancellation outcome.
`artifacts put` / `verify` only reuse the local object layer: they do not print
object bodies and they do not build an index or lineage.
`models generate` records digest-only `ai.call.*` facts from a local fixture.
The mock path does not open a network connection. The OpenAI-compatible path
defaults to loopback with a `0.00` CNY cap; remote endpoints require `SecretRef`,
`read.external_api`, HTTPS, a recorded project CNY limit, and a request cap that
matches that limit. Uncertain transport after dispatch keeps the reservation.
`researchos m1 prove` records one empty-store research chain from a corpus; it
does not close Issue #38.
`researchos m2 prove` records one loopback Worker CPU loop from a corpus; it
does not spend GPU and does not close Issue #38.
`researchos m2 oci` records the digest-pinned OCI CPU loop when a live
engine has the planned image; otherwise it fails closed and MUST NOT be
described as a successful container run. Ordinary pytest may skip
`oci_live`; the GitHub job `Linux OCI integration` runs `-m oci_live`
(success brick and live faults) and must fail instead of skip.
`researchos m2 bench` records 10k or 100k EventStore timings; it is not
an SLA and does not spend GPU.
`researchos training plan` prints pinned `swift sft` argv and MUST NOT
execute. It is not a real training run.
`researchos training bind` prints the GPU docker argv for that plan and
MUST NOT start a container (`gpu: not-run`).
`researchos training snapshot` / `overlay` / `collect` pin Hub identity,
print resume argv, and put `/work/output` files into CAS. They MUST NOT
download, train, or claim a GPU checkpoint.
`researchos workers serve` / `workers run` split that loop across two
processes over pinned loopback HTTPS; they do not prove a remote Worker.
Cancel supervision records a process or container identity and confirms
exit; it does not stop a cloud instance.
`evidence import` stores a local Markdown or PDF snapshot in CAS and appends
digest-only `evidence.imported`; PDF extract is subprocess-bounded with a
minimal worker environment; unknown
rights cannot authorize training.
`report` rebuilds a static HTML or Markdown projection; it is not a fact source.
The tree does not import block entrypoints, does not execute arbitrary training
frameworks, expressions, plugins, or non-loopback Workers, does not write a
SQLite artifact index or durable projections, and does not provide object
export/delete, a real GPU stop adapter, an executable NativeProcessRuntime, or
network upload of training artifacts.
A simulated `completed` is not scientific success; `unknown` stays unresolved.
Any real GPU spend, external-account action, or irreversible operation still needs
a separate approval. See the [security policy](SECURITY.md).

## License

Copyright 2026 victorzhong0110.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
