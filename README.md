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
The field-level draft for M1-1 research decision objects is
[research-decision-objects-v0alpha1 (draft)](docs/protocols/research-decision-objects-v0alpha1.md).
M1 has not started delivering code.

Delivered capabilities include: ResearchSpec / ResearchEvent / BlockManifest
protocol foundations, a pure static planning kernel, a SQLite append-only event
fact store, a local content-addressed artifact object layer, a pure Run/Attempt
state machine, RunControl that preflights before write with global CAS, a
GPU-free and network-free deterministic SimulatedRuntime, a plan-authorization
gate bound to three digests, a non-credential authorization CLI, audit-only
evaluation events, read-only lineage, in-process `decisionDigest`, explicit
simulated-run / cancellation-request / artifact-object CLIs, and a non-launching
NativeProcessPreflight.

The tree still does not execute training jobs or real GPU workloads, and it does
not treat authorization, a preflight report, a lineage rebuild, or
`decisionDigest` as an authenticated receipt, a launch permit, or the audit fact
a Run consumed, nor does it report a cancellation request as already stopped.
A real NativeProcessRuntime, remote Workers, a SQLite artifact index, and
authenticated launch credentials are not M0 deliverables.

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
- [ResearchSpec v0alpha1](docs/protocols/research-spec-v0alpha1.md)
- [ResearchEvent v0alpha1](docs/protocols/research-event-v0alpha1.md)
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
plan-authorization gate through a fixed T0 `simulate` capability policy, and
appends Run/Attempt lifecycle events through RunControl only when the plan is a
single `simulated.experiment@0.1.0` whose config names `outcome` explicitly.
`id`/`time`/`streamid` are still supplied by the caller; conflicts are not
retried; `unknown` is not collapsed into failure or success. A simulated
`completed` only means a controlled lifecycle ended, not that training succeeded
or a hypothesis held. A minimal runnable example is in
[M0 SimulatedRuntime](docs/guides/m0-simulated-runtime.md).

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
The tree does not import block entrypoints, does not execute arbitrary training
code, expressions, plugins, or remote Workers, does not write a SQLite artifact
index or durable projections, and does not provide object export/delete, a real
stop adapter, an executable NativeProcessRuntime, or network upload.
A simulated `completed` is not scientific success; `unknown` stays unresolved.
Any real GPU spend, external-account action, or irreversible operation still needs
a separate approval. See the [security policy](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
