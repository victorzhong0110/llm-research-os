# M3 evidence and acceptance matrix

Status: **R01–R07 integrated; R08 CPU native/Ray execution and transfer slices integrated. Checkpoint B is not accepted. Sequential completion through R16 is authorized; each predecessor must be merged and accepted before the next package starts.**
Canonical package definitions: [M3 plan](../../plans/m3-development-plan.md).
Ownership and review: [development governance](../../development-governance.md).

The maintainer's 2026-10-04 direction supersedes the former B freeze in historical
candidate entries below; their implementation identities and evidence gaps are
unchanged. Use the [live runbook](../../guides/r08-live-acceptance.md) and
[pending evidence checklist](r08-live-acceptance.md) to close R07/R08. No B
acceptance or R09 start is claimed by this direction update.

## Recording rules

Implementation, integration, verification, and acceptance are separate columns.
Implementers append candidate evidence in their package PR. After integration,
record the actual merge SHA and main CI result; acceptance requires review of the
specified scope. Do not predict a future merge identity or call CI success live
acceptance. Record exact commands, platforms, input/build/runtime identities,
outcomes, limitations, and links. Supersede old records explicitly rather than
rewriting them. Evidence is collected with every package, not deferred to R16.

A package may be implemented and merged while a required real-host check remains
pending-live. That does not complete its live acceptance or checkpoint. A skip,
Mock, config file, or local test cannot substitute for the missing evidence.

## Work-package ledger

| Package | Scope | Implementation / integration | Verification / acceptance | Evidence |
| --- | --- | --- | --- | --- |
| R01 | Scope, capability state, and acceptance baseline | Merged in #84 at `7d1bcbe0c956e0fd7d7ce98f07b6c42c8439cc47` | Maintainer-directed integration; post-merge CI passed | [Plan](../../plans/m3-development-plan.md), [governance](../../development-governance.md), [ADR-0064](../../adr/0064-planning-and-implementation-ownership.md); [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35452438029) |
| R02 | Shared application services | Merged in #105 at `9fb8f5142bb18adffa1423e96ecf2ca43f650432` | Scoped review accepted after P1 fixes; [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35810232891) passed | [R02 integration](#r02-integration-and-scope), [candidate history](#r02-candidate-evidence) |
| R03 | Real native execution contract | Merged in #109 at `1a08bfede3970f9300ba53078d19e6f21a7f8d79` | Reviewed validation-only contract accepted; no live launch | [R03 integration](#r03-integration-and-scope), [candidate history](#r03-candidate-evidence) |
| R04 | Verifiable code and runtime environment | Merged in #111 at `55b72268fcabe02ba0af0e5f1a6f038a515435e4` | Corrected PR CI passed; post-merge main CI not yet cited here | [R04 candidate](#r04-candidate-evidence) |
| R05 | Real native execution through the Worker lifecycle | Merged in #114 at `7abe55c1a8e770a6b0e5a058ea69563edeb7071c` | PR CI passed on Linux/macOS; checkpoint A needs R06 | [R05 candidate](#r05-candidate-evidence) |
| R06 | Cancellation, observation, and crash recovery | Merged in #115 at `62cfad00af76b04a58de27671edf76a1127b0f5a` | [Main CI #258](https://github.com/victorzhong0110/llm-research-os/actions/runs/36695842170) passed; no blanket checkpoint acceptance | [R06 candidate](#r06-candidate-evidence), [integration record](https://github.com/victorzhong0110/llm-research-os/pull/115) |
| R07 | SSH onboarding and doctor | Merged in #116 at `1f8b14226728a3c3c710ea95ea1e3347d40716be` | [Main CI #260](https://github.com/victorzhong0110/llm-research-os/actions/runs/36696795007) passed; authorized-host acceptance pending-live | [R07 candidate](#r07-candidate-evidence), [integration record](https://github.com/victorzhong0110/llm-research-os/pull/116) |
| R08 | Two-host artifact transfer and fault acceptance | Local foundation merged in #117 at `c9e1d3e55e5eb63a597c5cb01460dab76b6ef338`; HTTPS input slice merged in #118 at `65304b0659168d9661dde010ae751c35dedc81b5`; HTTPS output slice merged in #120 at `575a091d41034a758bcac0c4f8bdf737c7157040` | [Main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36850636460) passed for the foundation; [HTTPS input main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36984410531) passed. [HTTPS output main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349) passed. Remote material preparation merged in #122 at `9ae3a0ccd751543fcf1086f9fe530c3d1191e0a0` ([main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37120726534) passed). Remote executor/recovery merged in #126 at `c6903c3d795fbef3705d966bec84c1a212c491fe`; CLI merged in #127 at `35eda8cc9d9c71f251e35a41a2a231174f40c9e0` ([main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37141821193) passed). Actual selected two-host and GPU evidence remain pending-live | [R08 candidate](#r08-candidate-evidence), [review corrections](#r08-review-corrections), [HTTPS input candidate](#r08-https-input-candidate) |
| R09 | Local API and browser authority boundaries | Merged #131 at `73e1386cd5c3d6cafbc91798b62a5b04460cfc93` | Final-head CI 37209190785 passed; B live evidence remains open | [R09 candidate](#r09-candidate-evidence) |
| R10 | Read-only research workbench | Reviewed repair in #132; exact integration state/SHA at the PR | Final-head browser/type/build/full-suite CI is the integration gate | [R10 candidate](#r10-candidate-evidence) |
| R11 | Browser approval, execution, cancellation, and restore | Partial operations slice merged #133 at `b3a351c690597dc430a713c9a5b8ebf5f6bf3648` | Final-head CI 37224701233 passed; start/restore and B remain open | [R11 review](../../reviews/pr134-136-2026-10-05.md) |
| R12 | AI proposals, citations, and researcher decisions | Partial ledger/proposal slice merged in #134 at `89b9ab4`; final-head CI 37230774848 passed | Integration is not full acceptance; provider generation/evidence import/budget UI remain open | [Review](../../reviews/pr134-136-2026-10-05.md) |
| R13 | Real evaluation, comparison, and conclusions | Partial computed-fixture mechanics merged in #135 at `bc0bcbc`; final-head CI 37232561416 passed | Real-model/report/Checkpoint C acceptance remains open | [Review](../../reviews/pr134-136-2026-10-05.md) |
| R14 | Minimal extension mechanism and permission boundary | Partial Python boundary merged #136 at `bf8a45a`; final-head CI 37233415368 passed | Typed third-party integration/CLI/full R14 and D remain open | [Review](../../reviews/pr134-136-2026-10-05.md) |
| R15 | Installation, startup, backup, and recovery | Reviewed recovery slice in #139; final repair head `d50aff3` and CI 37454556583; exact integration at the PR | Not accepted; no replication, encryption, scheduling, retention, or downgrade support | [R15 candidate](#r15-candidate-evidence) |
| R16 | Independent trials and phase acceptance | Reviewed and repaired trial tooling in #140; final head/checks/integration recorded at the PR | **Not accepted; no trial performed, Checkpoint D open** | [R16 candidate](#r16-candidate-evidence) |

## R10 candidate evidence

Original submission: `abd3524e36d56e6bf711dbfc91878f3bff0e09c0`, #132. Review
repairs integrate merged R09 main `73e1386cd5c3d6cafbc91798b62a5b04460cfc93`.
Cancellation uses the existing reducer and remains distinct from observed stop;
Run details use scoped frozen pages. Event inspection, immutable stored spec/plan
inspection and actual dependency topology, decision/dissent/authorization history,
log/metric/artifact/environment contents and verified transitive lineage are
implemented as bounded reads. Missing content/provenance and unsupported nested
graphs are explicit. No measurements are inferred from IDs or numeric values.

The published response schema and generated frontend contracts are checked against
actual API responses. Focused API/socket/contract/CLI validation: **150 passed**; ruff/format, mypy
(245 source files), generated schemas, frontend type/build and wheel build passed.
The local browser download was blocked; final-head CI must establish its pass.
New regressions cover fresh/poisoned caches, late Run facts,
actual cancellation control, transitive project proof, redaction, oversized/binary
objects and the existing plan compiler. Browser fixtures are synthetic, use actual
SQLite/CAS and preserve the store across server restart; they do not supply live
GPU or Worker acceptance. Final-head CI and exact repair head are recorded in #132.

R09 integration evidence: reviewed repair `ce83a41bc22b3082d47b23c84ecd181bcbd7acb0`,
merged #131 at `73e1386cd5c3d6cafbc91798b62a5b04460cfc93`; CI
[37209190785](https://github.com/victorzhong0110/llm-research-os/actions/runs/37209190785)
passed all five Python and real native/Ray/OCI gates. B remains open. Historical
candidate notes below describe original submissions and do not override this update.

## R09 candidate

Status: **Implemented on branch `r09-local-api`; candidate evidence only. Not merged,
not accepted.** Base: `docs/sequential-r08-r16-acceptance` at `021f18e`. Checkpoint B
is still open and R08 live two-host/GPU evidence is still pending-live; R09 work was
authorized sequentially and does not close that gate.

### Review correction candidate (2026-10-04)

The maintainer assigned Codex to fix and merge #131/#132. #130 was merged at
`a5d730cc171318daafda13dc81d2b0cd6bc18d73`; this candidate integrates that main.
The stdlib transport is accepted by the planning/review assistant for the local,
read-only scope with bounded handler threads, lifetime-held SSE slots, socket
idle/absolute deadlines, read-only SQLite and query budgets. The historical
stacking deviation is superseded by the explicit sequential integration request.
Checkpoint B and selected-host/GPU evidence remain open.

Review regressions cover 1,001-event Run reads, filters before pagination, frozen
scoped cursors, SSE after foreign-project prefixes, concurrent health while SSE
is open, slot release before iteration, read-only stores, SQLite interruption,
and valid PDF extraction in an isolated worker. API/socket/regression suite:
70 passed before the additional absolute-header-deadline regression was added.
Final-head CI remains authoritative; original Mac 3.13 failure is not a green run.

Actual 10,000-event SQLite baseline on this managed Linux Python 3.12.14 host:
5,000 events per project, one Run in the selected project, page limit 100.
Event page: 100 items, 5.443 ms; Run page: one item, 3.480 ms; revision page:
zero items, 0.069 ms; all returned high-water mark 10,000 under the query budget.
This records metadata-query scale, not multi-Run execution or revision-scale
acceptance. Fixtures are synthetic and do not supply R08 live evidence.

### Proposed normative change for review

The R09 plan described "optional FastAPI/ASGI". The implementation is a
standard-library WSGI application on `wsgiref`, loopback only, to avoid adding a web
framework and ASGI server to a core that currently carries five dependencies. The
versioned JSON contract, same-origin session boundary, bounded projections and
resumable SSE are unchanged. Review decision: accept the deviation, or require a
framework-backed implementation. Replacing the transport later does not change the
documented contract.

### Implemented behavior against the plan's R09 deliverables

| Plan deliverable | Where |
| --- | --- |
| Versioned read/validation/preview endpoints | `src/llm_research_os/web/app.py`; `/capabilities`, `/workspace`, `/events`, `/revisions`, `/runs`, `/artifacts/{digest}`, `/preview/document`, `/session` |
| Structured errors | `web/errors.py` closed `ApiErrorCode`; fixed operator text, no request echo |
| Bounded projections | `web/projections.py`; every page carries `nextCursor` and `highWaterMark` |
| Resumable SSE with polling fallback | `web/app.py::_stream`; `Last-Event-ID` or `?cursor=`, `high-water` and closing `idle` events, same cursor semantics on `/events` |
| Local same-origin sessions, Host/Origin validation, authentication, CSRF | `web/sessions.py`; one-time bootstrap secret in a URL fragment, `HttpOnly; SameSite=Strict` cookie in memory, exact-`Host`, matching-`Origin` on unsafe methods, double-submit CSRF |
| Browser session is not a Worker credential | No route accepts a grant, private TLS key or bearer token; asserted by test |
| Body/depth/node/time/concurrency limits during parsing, on real JSON/YAML/PDF paths | `web/limits.py`; oversized declared length refused unread, understated length cut at the cap, JSON/YAML through the alias-rejecting loader, PDF through the bounded extractor, `ConcurrencyGate` refuses instead of queueing |
| Project-scoped cursors and artifact access | `ReadProjections` filters on `projectId`; artifact scope proven from linked events via `EventStore.list_artifact_links_page` |
| Snapshot high-water marks; bounded metric chunks rather than per-sample events | `highWaterMark` on every page; metrics remain CAS chunks per `metrics/chunk.py` and this surface appends no metric fact |

### Acceptance bullets

| Plan acceptance | Result |
| --- | --- |
| Cross-site/unauthorized requests tested | `403 host-forbidden`, `403 origin-forbidden`, `403 csrf-invalid`, `401 session-required`, `401 session-expired`, `409 bootstrap-consumed`, `403 bootstrap-invalid` |
| Wrong-project access tested | Foreign digest is `404 not-found`; own digest is served and inlined |
| Hostile documents tested | YAML alias amplification, duplicate JSON keys, 400-level nesting, malformed PDF, unsupported media type, traversal in `documentName` all refused |
| Oversized inputs tested | Declared and actual body caps, `parameter-invalid` for a non-numeric `Content-Length` |
| Slow clients tested | Above-cap concurrency returns `503 concurrency-exhausted` rather than queueing; the stream closes on its idle deadline instead of holding the connection |
| Reconnects tested | `Last-Event-ID` resume; cursor walk covers every event exactly once; run cursor pages strictly older runs without overlap |
| Queries bounded at representative volume; baseline recorded | Every page is capped at `MAX_PAGE_LIMIT=500` and a stream at `MAX_STREAM_EVENTS=200`. Baseline: with 3 seeded events an event page reads 3 rows, a run page folds 3 events, and a 200-event stream reads 2 verified pages of 100. A large-volume EventStore baseline is still outstanding and is not claimed. |
| Errors and logs do not leak credentials, bodies or host paths | Workspace view reports manifest-relative paths only; error bodies are fixed text; the access log is suppressed because it echoes request paths; artifact bytes inlined only below 256 KiB |

### Validation actually run

Local macOS, Python 3.12.13, branch `r09-local-api`, uncommitted at the time of
recording.

- `uv run ruff check src/ tests/` — passed.
- `uv run ruff format --check src/` — passed.
- `uv run mypy src` — passed, 241 source files.
- `uv run pytest tests/test_web_api.py` — 50 passed.
- `uv run researchos schema --check-all` — every registered schema current.
- `uv run python scripts/event_catalog.py --check` and
  `uv run python scripts/project_status.py --check` — passed.
- `node conformance/digest/verify.mjs` — 13 vectors passed.
- Full `-m "not oci_live and not slow and not ray_native_live"` run with
  `--cov-fail-under=85`: see the pull request for the exact counts.

CI results, the merge SHA and post-merge coverage are recorded after they exist. This
entry predicts neither.

### Local environment limitation, not a repository defect

One pre-existing failure in the mainline suite is unrelated to R09 and reproduces on
`origin/main` in this workspace: `tests/test_native_ssh_live.py::test_offline_install_is_idempotent_and_keeps_unrelated_files`.
The R07 offline install creates its venv with `venv.EnvBuilder(with_pip=True)`, and the
uv-managed standalone CPython 3.12.13 here aborts in the child
`ensurepip` with `dyld: Library not loaded: @rpath/libpython3.12.dylib`, so the install
returns `blocked/install-failed`. It is a macOS dynamic-linking limitation of this
machine's Python, not changed R09 behaviour, and the main CI run at `0acb62b` passes that
test.

### Gaps

- No browser has loaded this surface; there is no E2E or accessibility evidence.
- The run page folds the project's events to derive the index. It is bounded in the
  response, not in derivation cost; a store with many runs needs the existing
  `run_projections` cache, which this surface does not yet use.
- No large-volume query baseline. A slow query at production event volume is unmeasured.
- Mutating browser commands, restore, proposals and evaluation are R11–R13.
- `wsgiref` is a development server. It is loopback-only and single-user, and is not
  hardened against a hostile network peer.
- R08's live two-host and GPU evidence remains pending-live and is not addressed here.


### Integration update (2026-10-02)

PR #118 merged at `65304b0659168d9661dde010ae751c35dedc81b5`.
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36983679149)
and [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36984410531)
passed. The Linux Python 3.12 PR job recorded 1,661 passed, 12 OCI-only deselected,
zero failures/skips, and unrounded statement-plus-branch coverage 85.381944%.
The local fresh locked environment recorded 1,645 passed, 12 namespace/process
observation failures, four skips, 12 deselected and 84.902777% coverage; it did not
pass the CI coverage gate. No skip or threshold was added to hide those failures.
Remote outputs, durable remote staging/execution/recovery, and authorized two-host
and GPU evidence remain incomplete. Checkpoint B is not accepted; R09 is not started.


Base: verified main `c9e1d3e55e5eb63a597c5cb01460dab76b6ef338`, whose
[post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36850636460)
passed. The #117 foundation is integrated; its historical candidate records
below remain historical rather than current integration status.

This slice adds an HTTPS native input endpoint and bounded pinned-TLS client.
Actual recorded Worker grants authorize only immutable planned native
bundle/lock/inventory/input digests. Revoked grants, cancellation and expired
claimed leases refuse downloads. Downloads/replays append no facts and never
claim or launch work. The protocol and residual security boundaries are in
[the input protocol](../../protocols/native-input-transfer-v0alpha1.md) and TM-069.

Local Linux/Python 3.12.14 candidate checks:

- `uv run pytest -q tests/test_native_input_transport.py tests/test_native_transfer_security.py tests/test_worker_isolate.py tests/test_evidence.py` — 69 passed.
- Earlier scoped Worker/protocol/fault/recovery/local-transfer regression — 82 passed before the final cancellation regression was added.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` — passed.
- Schema freshness, event catalog, project status, 13 JCS vectors and `uv build` — passed.

An initial broader run using restored dependencies returned 1641 passed,
15 failed, 4 skipped and 12 deselected, with 84.875% reported coverage. It is
not a passing gate. Three PDF failures came from that restored interpreter
setup and pass in the fresh locked environment; the other failures exercise
AF_UNIX and process observation in this restricted container. Fresh full-suite
results and standard CI must be recorded in the PR before integration.

This is one independently reviewable R08 slice. Remote output upload, durable
remote staging orchestration, remote native launch and full restart/fault
integration are implementation gaps. Authorized two-host and GPU live evidence
are still pending-live. No R08 full acceptance or Checkpoint B closure is claimed.

## R08 HTTPS output candidate

### Integration update (2026-10-03)

PR #120 merged at `575a091d41034a758bcac0c4f8bdf737c7157040`.
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37028030342)
and [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349)
passed all five Python jobs and Linux OCI; PR Human authorship passed. Linux
Python 3.12 recorded 1,697 passed, 12 OCI-only deselected, zero failures/skips,
85.447% reported statement-plus-branch coverage and a passing unrounded gate.
The fresh locked local suite recorded 1,681 passed, the same 12 host namespace/
process-observation failures, four skips, 12 deselected and 84.956% reported
coverage. It did not pass the local coverage gate; no new skips or threshold
changes were added. This records integration, not full R08 or B acceptance.



Base: verified main `6e1e3b0e4fba0776f63e816f55f5a03e4048df2e`, whose
[final main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37021177400)
passed after the project tour and maintenance consolidation. This output slice
is candidate evidence until its PR is merged and main verification is recorded.

The pinned HTTPS output endpoint verifies one canonical native result for an
already consumed, execution-bound lease. Original verified CAS bytes precede
one durable Worker completion; exact replay after acknowledgment loss or
controller restart returns the same fact even after grant expiry/revocation.
Changed output, foreign session/scope, incomplete authorization, cancellation,
insufficient disk, unsafe locks, and missing/damaged completed CAS refuse.
Authorization is rechecked after publication and the EventStore head binds the
final append against concurrent cancellation/revocation. Native HTTP callers
cannot bypass the endpoint through generic artifact upload or completion.
Generated schemas and valid/invalid examples define the output and receipt.
See [the output protocol](../../protocols/native-output-transfer-v0alpha1.md)
and TM-070 for the exact boundaries.

This slice neither launches a process nor appends Run/Attempt lifecycle facts.
The reported full request digest is syntax checked, not independently rebuilt;
full result verification belongs to the controller's execution integration.
Durable remote staging, remote executor/recovery and new authorized two-host
fault evidence remain gaps. Checkpoint B is open, and R09 is not started.
Candidate check results are recorded in the PR before integration.

## R08 bound request context candidate

Base: verified main `575a091d41034a758bcac0c4f8bdf737c7157040` with passing
[main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37077796349).
This slice reconstructs the existing full reviewed request from the exact human
authorization fact, recorded grant and immutable queued execution, and delivers
it over bounded pinned HTTPS without creating authority, claims or facts. The
output endpoint requires its reported request digest to match this full
reconstruction; syntax-only checking of that citation is superseded by this
candidate. Existing execution/configuration and grant semantics are retained.
See [the context protocol](../../protocols/native-request-transfer-v0alpha1.md)
and TM-071. Integrated in [#121](https://github.com/victorzhong0110/llm-research-os/pull/121)
at `e5f01f32f668842604506a0b13b1d332e81c7061`; final-head CI
[37079684137](https://github.com/victorzhong0110/llm-research-os/actions/runs/37079684137)
passed all five Python jobs, Linux OCI and authorship. Linux Python 3.12 passed
1731 selected tests, with 12 OCI-only deselected and zero failures/skips.
[Post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37080366169)
passed all five Python jobs and Linux OCI at that exact merge commit. Local
final-head evidence was 1715 passed, the same 12 host namespace/process failures,
4 skips and 12 deselected; unrounded coverage was 85.025624%. The local suite
still failed due to those environment-sensitive failures; no gates were weakened.
Remote material staging, executor/recovery integration and new authorized
two-host/GPU evidence remain open; no Checkpoint B acceptance or R09 start.

## R08 remote material preparation candidate

Base: verified main `e5f01f32f668842604506a0b13b1d332e81c7061` and passing
[main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37080366169).
This slice adds a closed pinned material index and exact bundle-member,
interpreter/review/configuration downloads, plus Worker-local durable staging
and atomic preparation. It verifies actual Worker environment bytes and rechecks
live metadata before publishing the existing non-launching R04 receipt. The
Worker receives no controller database or HMAC key. Persistent journals retain
zero starts; corrupted caches/stages/workspaces refuse without repair. Review
also requires private CAS/staging parents and synchronizes newly created nested
directory entries before atomic workspace publication. These checks are in the
implementation and refusal tests, not waived by transport-only success.

See [the protocol](../../protocols/native-material-preparation-v0alpha1.md),
TM-072 and the slice PR for exact-head validation/CI evidence. Required
unsupported isolation and remote checkpoint restore explicitly refuse. Remote
executor/Run integration and process recovery remain implementation gaps, and
new authorized two-host/GPU proof remains pending-live. This is candidate
preparation behavior, not R08 full acceptance or Checkpoint B closure. No R09.

## R08 controller-bound remote claim candidate

Base: verified main `9ae3a0ccd751543fcf1086f9fe530c3d1191e0a0` (#122),
with passing [main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37120726534).
The native HTTPS poll boundary requires actual controller-owned spec/registry,
rebuilds the authorized execution binding and queues one bound Run/Attempt
before existing Worker grant consumption. Partial lifecycle prefixes replay
exactly; any existing lease returns resumed, including partially claimed leases.
Attempt remains queued, with no process start or remote PID observation.
Missing context/TLS, drift, cancellation/revocation, foreign Run and unknown
Attempt without a lease refuse. The PR records final-head tests and review.
Remote launch/process recovery and new authorized-host evidence remain open.

| Evidence dimension | Current status | What it does not establish |
| --- | --- | --- |
| Remote CPU native chain and faults | New two-host execution pending-live; transport/preparation/claim tests use real local TLS | GPU availability or GPU execution |
| Supported GPU runtime | New environment compatibility and real task pending-live; Kaggle is a candidate resource | Remote connection or process recovery |
| Remote GPU integration | New authorized supported-profile execution and fault evidence pending-live | Inferred from either row above |

These separate records preserve the existing R08 acceptance requirements.
Checkpoint B is open; freeze after its explicit acceptance; no R09.

## R08 optional open-source compute adapter candidate

The maintainer authorized evaluating available open-source execution services
on 2026-10-03. The current base is verified main
`8979bd3c6325fa2f1a8babe5ecc448d95ade93f4` (#123), with passing
[main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/37128007772).
#123 integrated actual controller plan binding, exact-prefix single-Run queueing
and conservative existing-lease replay; it did not start remote processes.

The optional Ray Jobs 2.59.0 bridge submits only fixed resource probes, persists
intent before a single POST and resumes only observation after interruption or
cluster history loss. A dedicated real Ray CPU job is the integration gate;
ordinary HTTP fixtures are not a pass for this gate. This workspace's actual
Ray startup currently fails on Ray/psutil PID visibility (`NoSuchProcess`),
so no local successful Ray/GPU evidence is claimed. The PR records exact-head
CI results and review. CUDA/Kaggle execution remains pending-live.

The next concrete decision is whether the demonstrated optional backend is
usable on the selected compute host. Its probe/result is separate from the
native CPU remote-chain and remote GPU integration records above. A Ray resource
probe cannot substitute for grant-bound project execution, a supported GPU
profile, verified results or actual fault/process observation. Full remote
executor/recovery remain gaps; B is open, freeze after acceptance, no R09.

## R08 remote start-record candidate

The verified base is #124, `c8f0195c71947ea117c668c16209ba91c065e03e`;
main CI 37131649684 passed all five Python jobs, live OCI and real Ray CPU.
The finite Ray bridge is merged, but CUDA and project-task execution remain open.

The next controller boundary records a consumed, fully-bound native lease's
start intent over pinned TLS. It rechecks actual kernel plan binding, complete
preparation citations and exact Run prefix, persists an immutable identity-bound
journal, and appends/replays one `attempt.started`. No process is started or
observed here; `launchAllowed` remains false. Unknown/terminal state and changed
or missing execution state never authorize redispatch. The implementation PR
records exact-head review and CI; local TLS fixtures are not two-host evidence.

Next decision: once the boundary passes review/CI, integrate the existing
Worker-local fixed child and backend with this record, then verify actual task
execution and conservative recovery. Full remote executor/output reconciliation,
new authorized CPU/GPU evidence and B acceptance remain pending; freeze after
actual B acceptance, no R09.

## R08 remote Worker execution candidate

The verified base is #125, `9b11323eaa2bccf651c633c0d5e0aaffb23df5d3`;
main CI 37133951296 passed all five Python jobs, live OCI and real Ray CPU.
This slice composes independent Worker-local preparation/CAS and the controller
start record with the fixed reviewed child. Launch intent precedes claim; local
identity and controller acknowledgement precede user-code import. Recovery only
observes saved identity or replays saved results, never claims or launches again.

A designated Linux native remote execution job requires real CPU output, observed
cancellation, lost acknowledgement and interrupted-upload recovery without mocked
OS identity or skip. Ordinary TLS outcome tests use explicit Worker-report
fixtures and prove only controller reconciliation. This workspace hides POSIX
start identity, so local live tests remain skipped and are not acceptance.
The implementation PR records exact final-head review and CI outcomes.

Controller lifecycle facts trust the bound authenticated Worker's OS observation;
no PID, private controller key or database crosses into Worker state. An unknown
observation cannot settle terminal facts or create rerun authority. An actual
single-host TLS/CAS integration is still not two distinct machines, GPU execution
or Ray project-job hosting. Those evidence records and Checkpoint B remain open;
freeze after actual B acceptance and do not begin R09.

## R08 native Worker CLI candidate

Verified base: #126, `c6903c3d795fbef3705d966bec84c1a212c491fe`;
main CI 37139063831 passed all five Python jobs plus live native, OCI and Ray.
The main Linux suite had 1926 passed, zero failures/skips and 85.605744% coverage.
#126 integrated actual Worker-local CPU/barrier/output and conservative recovery;
its 13 designated real-process tests are integration evidence, not two hosts.

This slice exposes that same service through existing Worker commands and
explicit trusted spec/registry on controller startup. Private credentials and
original recovery request are bounded; no fresh poll/launch occurs in recovery.
It prints the existing non-launch outcome receipt. The required native gate
adds real CLI CPU execution and a second isolated CLI process replaying the
same receipt. Ordinary unsafe input/context fixtures cannot replace that gate.
The PR records exact final-head review and CI. Ray project-job hosting, GPU/
Kaggle, actual selected hosts and B acceptance remain open; no R09, freeze after
actual B acceptance. No baseline authorization/profile/schema meaning changes.

## R08 optional Ray CPU project candidate

Verified base: #127, `35eda8cc9d9c71f251e35a41a2a231174f40c9e0`;
main CI 37141821193 passed all five Python jobs and real native/OCI/Ray gates.
Native integration ran 15 actual process tests, including independent CLI replay.
This is single-host integration, not selected two-host or GPU acceptance.

The optional fixed Ray driver now composes that reviewed native CPU service.
Private durable intent precedes a single vendor POST; lost/refused responses and
history loss permit observation only. The driver binds the original request
before native preparation/poll, with no arbitrary commands/packages/environment
or credential bytes in vendor metadata/argv. Vendor statuses append no Run facts.
Native recovery executes outside Ray on the same compute host and uses the
original saved process identity/result/receipt. Tests include protocol fixtures
and a separate designated real Ray project execution gate; exact final-head
checks and live results are recorded in the PR, not inferred from fixtures.
GPU scheduling/device profiles, Kaggle execution, selected two hosts, B closure
and R09 remain open. Freeze follows actual B acceptance. No authority/schema or
acceptance criterion is weakened.

## Checkpoints

| Checkpoint | Packages | Required evidence |
| --- | --- | --- |
| A | R02–R06 | Real local task, authorized launch/denial, artifacts, actual stop, and crash recovery |
| B | R07–R08 | New authorized two-host native execution, verified transfers, reconnect/cancel/unknown faults |
| C | R09–R13 | Browser proposal/decision/execution and recomputable real evaluation with human conclusion |
| D | R14–R16 | Extension boundary, clean install/restore, independent trials, and scoped closure review |

## Preserved historical acceptance

| Capability | Accepted or verified scope | Canonical evidence |
| --- | --- | --- |
| M1 offline research loop | Accepted offline behavior; no live-model inference | [ADR-0062](../../adr/0062-m1-m2-acceptance-and-m3-boundary.md), [wheel smoke](../m1-m2-maintenance/wheel-smoke.json) |
| Local host-Python helper | Verified unit/loopback helper only | Existing `tests/test_worker_protocol.py`; not generic native entrypoint acceptance |
| CPU OCI | Designated Linux OCI CI and accepted WSL2/Docker path | [ADR-0055](../../adr/0055-live-oci-fault-acceptance.md), [M2 matrix](../m2-wsl2-cuda-live/m2-closure-matrix.md) |
| WSL2/Docker two-host CPU/CUDA/restore | Accepted live at original recorded identities; cuda.9 partial, cuda.10 failed, cuda.11 full-state restore | [M2 matrix](../m2-wsl2-cuda-live/m2-closure-matrix.md), ADR-0062 |
| macOS/MPS LoRA | Separate scoped live profile; not generic native execution | [MPS guide](../../guides/m2-mps-acceptance.md), [live receipt](../../../examples/m2-mps-checkpoint/live-evidence.json), ADR-0062 |
| #81 fixed native noop | Merged, CI-verified helper/refusal; real entrypoint not executed | [ADR-0063](../../adr/0063-m3-native-process-runtime-slice-1.md), `tests/test_native_process_runtime.py` |
| #81 SSH pack | Merged validator/writer tests; actual SSH onboarding/execution pending-live | ADR-0063, `tests/test_native_ssh_onboard.py` |

These records remain valid within their original scope and SHA. They are not
relabelled as unverified because a different platform or a newer runtime has not
been exercised. They also do not supply the new native two-host proof for R08.
Keep `docs/status.json` historical baseline/evidence identities distinct from
per-package implementation and live-runtime identities.

## R02 candidate evidence

Scope: shared application services only. This section preserves evidence
recorded while R02 #105 was an open candidate; the integration identity and
scoped acceptance are recorded below. These pre-merge checks do not prove a
live-host native execution path. No pending-live check is required for R02.
Schema v2 was not migrated; historical event digests are not rewritten.

Commands, run from the repository root on the implementation host:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run pytest --cov=llm_research_os --cov-fail-under=85`
- `uv run researchos schema --check-all`
- `node conformance/digest/verify.mjs`
- `uv build`

Package tests: `tests/test_application_service.py`. They cover CLI/Python
semantic equality, receipt restart, content conflict, stale head and revision,
cross-project refusal, overlapping control/Worker roots, duplicate-run
simulation, decision receipts linked to facts and CAS digests, import
without training extras, duplicate event-id recovery, `expectedHead` at the
decision append and at the first simulation write, and one frozen snapshot
for spec, decision, simulation request, and registry inputs.

Historical implementer report at `a15b106d4fd211f4c6aaa16d92ae859f0b5de390`, after the
simulation `expectedHead` follow-up:
`ruff check`, `ruff format --check`, and `mypy src` passed;
`pytest tests/test_application_service.py tests/test_run_control.py tests/test_simulated_runtime.py`
passed 106 tests. `pytest --cov=llm_research_os --cov-fail-under=85` passed
1458 tests, failed 1, and skipped 10. The failure is
`tests/test_m2_perf.py::test_perf_baseline_100k_keeps_report_lineage_short`
(`append_seconds` 213.72 against a 180 second bound). That test is marked
`slow` and is outside the CI selector `not oci_live and not slow`. Coverage
was 20831/24418 = 85.310017% (`scripts/check_coverage.py` passed). Ten
existing OCI tests were skipped because this host has no OCI runtime. That
skip is not R02 live evidence and does not replace the designated OCI job.
`researchos schema --check-all`, `node conformance/digest/verify.mjs`
(13 vectors), `event_catalog.py --check`, and `project_status.py --check`
passed. `uv build` was not re-run; packaging inputs were unchanged.
Outcomes belong to the PR head, not to the later merge commit.

## R02 integration and scope

PR [#105](https://github.com/victorzhong0110/llm-research-os/pull/105) was
squash-merged into `main` at `9fb8f5142bb18adffa1423e96ecf2ca43f650432` after the
review follow-up head `9e67f86b26b44873bc2f548d739afb09675718fb`.
The [post-merge CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35810232891) completed successfully on that merge SHA:
Ubuntu Python 3.12/3.13, macOS Python 3.12/3.13, Linux OCI, and the
forward-compat Python 3.14 job passed; authorship and fork DCO jobs were
skipped for the push event. The corrected tree also passed 147 focused local
tests, `uv build`, lint, type, schema, event catalog, and project-status checks.
The unchanged 100k slow benchmark passed on the corrective tree; an earlier
host run failed its 180-second append bound, while a baseline main rerun passed.
Both outcomes remain historical evidence of host timing variance, without a
claim that R02 caused the earlier timeout.

The planning review accepts R02 within the shared application-service contract:
workspace identity binding, common CLI/Python semantics, durable receipts,
conflict and stale-head refusal, and unchanged EventStore schema v2. It does
not accept real native execution, SSH live operation, browser controls, real
evaluation, or Issue #53 closure. R03 remains a separate work package.

## R03 candidate evidence

Scope: reviewed-native request/report contract only. The validator does not
import an entrypoint, spawn a process, consume a Worker grant, or append a
Run/Attempt fact. `launchAllowed` is false. This section preserves the original
candidate evidence before the review fixes. It is not the merge SHA or live
execution. Issue #108 is a prior CI rerun note and is not R03 execution
evidence. Real entrypoint execution remains R05. Issue #53 stays open.

Commands below were run on the original candidate tree before #109's head was
published. The original head `b7b3ab69082d12c8a0bd0bcfabdddf5c91e48b61` is not the merge
SHA. Host: Linux 6.12.94+ x86_64, CPython 3.12.3. `observe_host_feasibility()`
on that host reported `linux/x86_64`, with network, filesystem, memory,
process-group, wall-clock, and output-byte enforcement all false, and
`launch_implemented` false.

- `uv run ruff check .` passed
- `uv run ruff format --check .` passed
- `uv run mypy src` passed
- `uv run pytest -m "not oci_live and not slow" --cov=llm_research_os --cov-fail-under=85` passed: 1520 passed, 12 deselected, coverage 21434/25113 = 85.350217%
- `uv run python scripts/check_coverage.py coverage.json` passed
- `uv run researchos schema --check-all` passed
- `node conformance/digest/verify.mjs` passed (13 vectors)
- `uv run python scripts/event_catalog.py --check` passed
- `uv run python scripts/project_status.py --check` passed
- `uv build` passed

Package tests: `tests/test_native_reviewed_execution.py` (62 passed inside
the suite above). They cover the generated schemas, valid Linux and macOS
documents, stale or substituted bindings, expiry, revocation, replay, resumed
claim, unsupported profile and platform, required but unenforced isolation,
and the absence of entrypoint import or subprocess. A darwin document checked
on this Linux host is a contract result, not a live macOS run. No pending-live
host is required for this validation-only package; R05/R06 live execution
remains absent. Twelve deselected tests are the existing `oci_live` and `slow`
selectors, not R03 evidence.

## R03 integration and scope

PR [#109](https://github.com/victorzhong0110/llm-research-os/pull/109)
merged at `1a08bfede3970f9300ba53078d19e6f21a7f8d79`; the final PR
head was `b6c3ad7e66e5c088c8cc60288f4917059b268483`. Review fixes
accepted an authorization containing `execute.native` plus other capabilities,
bound the grant contract view to the Run, and rejected duplicate JSON keys,
invalid UTF-8, excessive JSON nesting, and oversized numeric literals with a
contract error. Regression coverage is in `tests/test_native_reviewed_execution.py`;
the grant fixtures include a foreign-Run denial. The final guide explicitly
labels caller-provided citations as contract fixtures. R04/R05 must rebuild
real facts and bytes before using a report for preparation or launch.

[Final PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35846797682)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, Linux OCI,
and human-authorship checks. The [post-merge main CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/35847460260)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, and Linux OCI;
authorship and fork-only DCO jobs were skipped on the main push.
Local review-host checks passed 68 targeted tests,
ruff, format, mypy, generated schemas, digest, event catalog, project status,
and `uv build`. The local full selection had 1523 passed, 2 skipped,
12 deselected, and 85.357% coverage; one unrelated Unix-socket artifact test
failed because the review container denied socket creation. GitHub CI ran that
test successfully on its supported runners.

Acceptance is limited to a non-launching request/report contract and its
validator. No entrypoint execution, real grant consumption, real host
enforcement, or live macOS execution was accepted. Issue #53 remains open;
R04 is the next package.

## R04 candidate evidence

Scope: verifiable code and runtime environment only. Preparation rebuilds the
authorization fact, HMAC grant, and CAS bytes, then writes or diagnoses a
private workspace. It does not import an entrypoint, spawn a process, install
a package, consume a Worker grant, or append a Run/Attempt fact.
`launchAllowed` is false. This section is candidate evidence for the open PR
head. It is not a merge SHA, not acceptance, and not live execution. Real
entrypoint execution remains R05. Issue #53 stays open.

The first fixture is the CPU brick at
`examples/native-reviewed-preparation/brick/task.py`. Valid and invalid
documents live beside it. The static Linux receipt uses a synthetic
interpreter digest and is a document fixture, not a live prepare of that
host. Package tests build the interpreter document from the process under
test. No GPU or training extra is required. No pending-live host is required
for this non-launching package.

Commands, run from the repository root on the candidate head
`c27495e67bef7d1095d3a86d63a113991252db34`. Host: Linux 6.12.94+ x86_64,
CPython 3.12.3. Base: `1a08bfede3970f9300ba53078d19e6f21a7f8d79`.

- `uv run ruff check .` passed
- `uv run ruff format --check .` passed
- `uv run mypy src` passed
- `uv run pytest -m "not oci_live and not slow" --cov=llm_research_os --cov-fail-under=85` passed: 1543 passed, 12 deselected, pytest-cov total 85.249%
- `uv run coverage json -o coverage.json` from that `.coverage` file, then `uv run python scripts/check_coverage.py coverage.json` passed: 22377/26249 = 85.248962%. The first invocation without a JSON report failed only because the file was absent (`Errno 2`); it was not a coverage-floor miss
- `uv run researchos schema --check-all` passed
- `node conformance/digest/verify.mjs` passed (13 vectors)
- `uv run python scripts/event_catalog.py --check` passed
- `uv run python scripts/project_status.py --check` passed
- `uv build` passed

Package tests: `tests/test_native_reviewed_preparation.py` (17 passed inside
the suite above). They cover a fresh workspace, repeat prepare, substitution
of code, config, inputs, and environment identity before user code,
mismatched and incomplete or damaged trees, expired, forged, revoked, and
consumed grants, `execute.local`, symlink rejection, CLI prepare/doctor, and
the absence of entrypoint import or subprocess. Twelve deselected tests are
the existing `oci_live` and `slow` selectors, not R04 evidence. No
pending-live host is required for this non-launching package.

Review follow-up on PR #111: the original candidate compared the dependency
lock and inventory to each other without checking installed packages, and its
interpreter document only named a CPython version, ABI, and platform. A
missing pinned dependency still produced `prepared` and `ready` on that head.
The corrected candidate hashes the host interpreter executable and every
listed installed distribution file, checks those bytes at prepare and doctor,
and refuses missing or altered dependencies. Regression tests cover a missing
package, valid installed package, wrong package digest, changed installed file,
wrong interpreter digest, and an executable path changed after preparation.
The generated interpreter schema, example, protocol, and guide changed with
the model. The R03 acceptance row from main #110 is preserved; the stale R03
integration note originally on this R04 branch was superseded.

On the review Linux container (CPython 3.12.14), the focused R04 suite had
19 passes. Ruff, formatting, mypy, and generated schema checks passed on the
corrected tree. The full `not oci_live and not slow` run had 1530 passes,
12 failures, 3 skips, and 12 deselections; one failure came from denied Unix
socket creation, and the others from host process observation/cancellation
restrictions. Coverage on that interrupted run was 84.207%, below the 85%
gate; this is **not** a passing full-suite result. Required GitHub CI must
validate the corrected head on supported runners before integration.

PR #111 was subsequently merged as `55b72268fcabe02ba0af0e5f1a6f038a515435e4`.
The corrected PR head `7b33809ab4f0774ecc3c145864bb7f3b89bbf9b4`
passed [CI run 36421032133](https://github.com/victorzhong0110/llm-research-os/actions/runs/36421032133)
on Ubuntu 3.12/3.13/3.14, macOS 3.12/3.13, and Linux OCI. Ubuntu 3.13
recorded 1545 passed, 12 deselected, 22441/26328 = 85.236250% coverage.
The earlier failing local container run above remains a separate record.

## R05 candidate evidence

Scope: `execute_reviewed_native` and `researchos native execute-reviewed` run
one prepared reviewed Python Attempt. The dedicated Worker runtime/media pair
binds the planned task's R03 `configDigest` to its CAS bundle and
`execute.native` capability. The entrypoint is imported only by a fixed
isolated-mode child. The parent checks R04 material, writes an fsynced launch
intent, consumes Worker authority, records Run/Attempt facts, starts the child
behind a pipe barrier, fsyncs process identity, and releases the barrier.
The child rechecks each prepared file against a pre-gate manifest, freezes
reviewed source in memory, and imports only those verified module bytes.
It accepts the contracted dotted callable names. Before success, the parent
requires process-group exit observation; exceptional cleanup signals the group
even when its leader has exited. Success stores a task-identified canonical JSON artifact in CAS,
then records `work.completed`, `attempt.succeeded`, and `run.completed`.
Observed task exceptions record Worker and Run failure facts. After uncertain
persistence, the consumed grant and launch intent block automatic redispatch.

Local Linux CPU tests cover deterministic output and CAS verification,
duplicate refusal, prepared-code substitution, pre-gate revocation and
expiry, substitution after child creation but before import, failed task
facts, identity-persistence failure after child creation, and CLI parity.
Focused command on the candidate tree:
`uv run --no-sync pytest -q tests/test_native_reviewed_child.py
tests/test_native_reviewed_runtime.py
tests/test_native_reviewed_preparation.py tests/test_native_reviewed_execution.py
tests/test_worker_protocol.py tests/test_event_catalog.py` — **127 passed**
after adding intent replay, post-preflight receipt/code substitution, stdout
bound, symlinked state directory, and a failed `attempt.started` persistence
case after grant consumption. The runner unit tests cover malformed/oversized
frames, path traversal, symlinks, byte substitution, structured success, and
task exceptions; the separate integration tests still execute an actual child.
The interpreter's actual executable image is hashed through Linux procfs
when accessible; hosts hiding process entries and macOS rehash the reviewed
interpreter path while the child remains behind the barrier. This fallback
does not prove the kernel's loaded inode identity. Network, filesystem,
memory, and process-count isolation is not claimed; R04 rejects any
unenforceable restriction marked required. R06 still owns cross-restart
observation, cancellation, and checkpoint recovery. No paid cloud or SSH
host was used. This is candidate implementation evidence, not maintainer
acceptance or a claim that a result is scientifically valid.

The local scratch container denies Unix socket creation and hides other
processes' `/proc` entries. Those restrictions break pre-existing Worker
observation and socket tests. The complete local run on this branch reported
15 failures, 1532 passed, 3 skipped, 12 deselected, and 84.291% coverage;
it is **not** passing CI evidence. The R05 tests themselves and targeted
contract/Worker regressions run separately below; supported GitHub runners
must decide the full required matrix before merge.

The first PR #114 CI run `36457193021` passed Linux OCI and the authorship
gate. Its Python tests passed (Ubuntu 3.12/3.13: 1553 passed, 12 deselected;
macOS 3.12/3.13: 1552 passed, 1 skipped, 12 deselected), but the coverage gate
failed: 84.984% on Ubuntu, 84.939% on macOS 3.12, and 84.988% on macOS
3.13. The optional Ubuntu
3.14 job also completed 1553 tests and failed only its 84.988% coverage
gate. The six added negative tests above are the follow-up for this real
coverage shortfall; a new CI run is required before review readiness.

Second CI run `36458092929` at head `64193e4b` passed Ubuntu 3.12 and 3.13,
including 1559 tests each and unrounded coverage 85.016092% and 85.004865%.
Linux OCI and human authorship passed. The optional Ubuntu 3.14 job completed
1559 tests but was still 84.997% covered. Runner branch tests were added
after this run.

Verified implementation head `79701ba4e0952eb6cb9db108ab225ba25f1f6c8f`:
[CI run 36524778920](https://github.com/victorzhong0110/llm-research-os/actions/runs/36524778920)
passed Ubuntu Python 3.12/3.13/3.14 (1571 passed, 12 deselected in each),
macOS Python 3.12/3.13 (1570 passed, 1 skipped, 12 deselected in each),
Linux OCI integration, and human authorship. The unrounded coverage range was
85.148293%–85.219176%, above the 85% gate. Regression tests cover an unlisted
unchecked `.pyc` alongside unchanged reviewed source, a dotted callable, a
surviving descendant after leader exit, and a descendant retaining pipes past
the wall-clock limit. The standalone runner reproduction and CI establish these
specific repairs; cancellation and restart reconciliation remain R06.

## R06 candidate evidence

R06 starts at main `7abe55c1a8e770a6b0e5a058ea69563edeb7071c`.
`reconcile_reviewed_native` reads the fsynced R05 launch intent, rebuilt
Worker grant/lease and Run facts, and saved process identity. A new Worker
instance can request observed stop for an already consumed lease. The fixed
profile sends TERM, waits three seconds for process-group exit, then KILL if
needed. A Linux start token or a Darwin process start observation must match;
missing identity, PID reuse, failed probes, and ambiguous outcomes remain
unknown. Post-consumption grant revocation becomes a Run cancellation request.
Cancelled is appended only after the group observer reports exited. A consumed
lease may record observed cancellation after grant expiry/revocation without
minting new launch authority. Reconciliation never redispatches an Attempt.

The companion `NativeRestoreClaim` requires a completed source Run and Worker
artifact, verified CAS bytes, distinct target Run/Attempt, matching reviewed
code/environment, an exact checkpoint input, and mode-specific state fields.
It does not assert that generic user code actually loaded state; the reviewed
task owns that behavior. `full-state` requires model, optimizer, scheduler,
and RNG fields; `adapter-only` requires adapter data and does not claim
optimizer restoration. The source/target lineage claim is saved with the new
launch intent. CLI exposes `native reconcile-reviewed` and optional restore
claim/source request arguments on `native execute-reviewed`.

Candidate tests: `tests/test_native_reviewed_recovery.py` exercises a real
sleeping task, cancellation using a newly constructed Worker/EventStore,
idempotent reconciliation, missing identity, PID reuse refusal, a still-running
Attempt without redispatch, concurrent Worker and Run cancellation fact appends,
and a
revoked/expired consumed grant that remains unknown until observed exit.
`tests/test_native_reviewed_checkpoint.py` checks a real completed source
artifact, accepts an adapter-only envelope, and rejects missing state,
incompatible mode, lineage, environment, artifact size, and digest. The
pre-claim gate rejects checkpoint input without its source and restore claim.
This scratch host cannot consistently observe process groups, even when its
start-token probe succeeds; supported Linux/macOS CI supplies the live stop
and restart result. The first [R06 CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36533850590)
found a concurrent event-ID race. Its [corrected successor](https://github.com/victorzhong0110/llm-research-os/actions/runs/36552639786)
at `bbf158f` passed the Linux 3.12/3.13 and OCI jobs, while macOS lacked
0.013 percentage points of coverage and the optional 3.14 job exposed a test
using its own ABI as an incompatibility fixture. The next
[CI run](https://github.com/victorzhong0110/llm-research-os/actions/runs/36553519194)
at `0dfc8a5` passed Linux 3.12/3.13/3.14, macOS 3.12, OCI, and authorship.
Its macOS 3.13 run exposed a second concurrent Run preflight race: the same
`attempt.cancelled` event had already made the Attempt terminal. The final
candidate handles that state only when the exact event is persisted, and its
real stop test now includes a descendant that must not survive cancellation.

Final code candidate `21792828c42ef2725ae049f52f689d5744b7ab42`:
[PR CI #251](https://github.com/victorzhong0110/llm-research-os/actions/runs/36554473144)
passed Ubuntu Python 3.12/3.13/3.14, macOS Python 3.12/3.13, Linux OCI, and
authorship. Each Python job passed 1,583 tests (12 OCI-only tests deselected).
The unrounded coverage range was 85.023693%–85.089814%, above the 85% gate.
The live test starts a reviewed task and a descendant, records a Run
cancellation, reconstructs a new Worker/EventStore, observes group exit,
verifies `cancel-observed` and `run.cancelled`, and checks that the descendant
does not run after stop. Synthetic fault tests separately cover an expired,
revoked consumed grant, PID reuse, unavailable identity, and two competing
reconcilers. This is PR verification, not post-merge CI or maintainer
acceptance; Checkpoint A remains under review until integration review.

## R07 candidate evidence

R07 is stacked on the R06 candidate branch at
`194802d9180365a9bc8a0a45b7fde99104e1662b`; R06 acceptance and merge are
still prerequisites for an integrated R07. The doctor adds explicit pinned
OpenSSH probe, deterministic offline wheelhouse installation in a private
user-owned runtime, and authenticated TLS Worker identity verification on the
existing Worker plane. The SSH pack's `pending-live` marker is not promoted by
these actions; native `--transport ssh` remains unavailable for tasks.

Local verification uses a fake SSH transport that executes the same fixed
remote program and stdin locally. It covers host-key mismatch, private-key
permissions, absent workdir, port conflict, offline wheel install/repeat/failure
cleanup, Worker registration and CA mismatch, and disconnect. The Worker
identity check appends no facts. The local transport and loopback Worker are
not an authorized second machine, so clean-host onboarding, actual host-key
rotation, network faults, and cross-machine Worker reachability remain
`pending-live`. No control SQLite, CAS, or TLS private key was sent in these
tests. The candidate does not enable an SSH task executor. Explicit, reviewed reverse
loopback tunneling is available for Worker verification; actual tunnel evidence
on an authorized second host remains pending-live.

Repository verification in this execution environment also exposed a
pre-existing R06 process-group observation ambiguity: the signal namespace
reported a present group while `/proc` exposed members under different PID
identities. The candidate now reports `unknown` when the two views disagree;
the focused descendant and synthetic regression tests pass. The Unix socket
artifact-store test cannot run here because socket creation returns `EPERM`;
that environmental exclusion is reported separately from the CI matrix.

Candidate checks on the Linux Python 3.12 implementation container:

- `pytest -q tests/test_native_ssh_live.py tests/test_native_ssh_onboard.py tests/test_worker_supervise.py::test_procfs_observation_and_group_listing tests/test_native_reviewed_runtime.py::test_descendant_cannot_outlive_recorded_success`: 62 passed, 2 skipped (no usable IPv6 link-local interface).
- `ruff check .`, `ruff format --check .`, `mypy src`, `researchos schema --check-all`, JCS conformance (13 vectors), and `git diff --check`: passed.
- Broader `pytest -q -m 'not oci_live and not slow' -k 'not test_source_symlink_directory_and_special_files_are_rejected' --cov=llm_research_os --cov-fail-under=85` before the final focused coverage additions: 1,575 passed, 11 failed, 4 skipped, 13 deselected; 83.661% coverage. Eleven existing live process-observation tests cannot resolve PIDs across this container's mixed signal/procfs views. The excluded Unix socket test raises `EPERM` here. This is **not** a passing full gate; standard CI must establish coverage and platform behavior for the final candidate.


## R08 candidate evidence

Scope: grant- and task-scoped file transfer only. `researchos native transfer`
copies manifest digests between one CAS and one directory. It does not list a
CAS, follow symlinks, or start a second lease when a journal already names one.
Fault classification keeps `unknown` and `cancel-requested` distinct from
`success`, `failure`, and `stopped`. A verified checkpoint can be copied into
the designated new Attempt; an unsupported restore is refused.

This section is candidate evidence for the open PR. It is not a merge SHA, not
maintainer acceptance, and not two-host proof. No second machine was
authorized. `gpu-oci` and `macos-mps` stay `pending-live`. Historical
cuda.1–11 and M2 OCI records are not reused. Issue #53 stays open.

The local CPU check runs one reviewed native task on the implementation host,
then copies only that task's result artifact. The receipt records
`native-scoped-transfer/v0alpha1`, the host `runtime` string, the manifest
digest, and the process identity saved by that task. That host is not a second
machine.

Package tests: `tests/test_native_transfer.py`.

## R08 review corrections

The original candidate `6382b0d4211766188daad61fb550eb9caf6f6d03` passed
[PR CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36838992563).
Review found temporary-journal symlink writes, path check/open races, short
write publication, interrupted-file retry and concurrent journal claim issues.
The follow-up pins directory descriptors, writes private exclusive temporary
files completely, publishes files without overwrite only after fsync, and
holds a journal lock across bounded read/modify/atomic publication. FIFO and
oversized journal reads are refused. Targeted transfer/security tests passed
29 cases locally; the original R07 SSH suite also passed 38 cases on this host.
Static, schema, digest and generated-state checks passed. Final candidate CI
must verify the published follow-up at its actual SHA.

The broader local run returned 1,624 passed, 12 failed, 4 skipped and 12
deselected, with 84.731% coverage. One unchanged artifact test cannot create
an AF_UNIX socket (`EPERM`); eleven unchanged Worker fault/MPS/supervision
tests cannot observe process identities in this container's mixed signal/procfs
views. This is not a passing full gate. Standard Linux/macOS CI must establish
the supported-platform results and the unrounded coverage floor. New regression
tests added after collection are included in the final candidate's CI run.

This explicitly supersedes any interpretation of the original candidate as
implemented authenticated two-host transfer. The helper trusts local manifest
correlation IDs; it does not consume a launch grant, contact another host or
exercise real disconnect/restart faults. Those remain R08 implementation work,
separate from missing authorized-host evidence. Local identity metadata is not
a new live process observation. Checkpoint B, R08 full acceptance and Issue #53
closure are not claimed. R06/R07 integration rows above supersede their old
candidate-only ledger entries; their historical candidate evidence is preserved.

Follow-up `a4e7fa89454aef18ec205aa424500cc1b780d17b` passed all Linux jobs,
OCI and macOS Python 3.13 in [CI](https://github.com/victorzhong0110/llm-research-os/actions/runs/36848733227).
macOS Python 3.12 reached 85.369% coverage but failed the competing-thread
claim regression (one claimant returned `transfer-journal-invalid`). The next
fix pairs an in-process mutex with the inter-process flock and creates the
stable lock inode exclusively before reopening it. A separate-process claim
regression complements the thread test. No failed CI is recorded as passing.

## R15 candidate evidence

Status: **candidate on the R15 branch; not merged, not accepted.** Checkpoint B
is still open and R08 live two-host/GPU evidence is still pending-live; R15 was
authorized sequentially and does not close that gate.

### Delivered

| Area | What exists | Where |
| --- | --- | --- |
| Install | Wheel carries the built workbench bundle and a minimal research corpus; `researchos workspace demo` builds a working workspace from packaged data in one command, with no key, no GPU, no Node and no training extras | [`wheel_smoke.py`](../../scripts/wheel_smoke.py), `src/llm_research_os/recovery/demo.py` |
| Initialize | `app init` plus `workspace doctor`, `workspace migrate` | [`r15-installation-and-recovery.md`](../../guides/r15-installation-and-recovery.md) |
| Startup | `web serve` reports a taken port as a closed `listener-unavailable` code and exits `2` instead of raising a traceback — **already delivered by merged R14**, so R15 proposes no change here; a missing bundle is a startup failure | `src/llm_research_os/web/serve.py` (merged) |
| Backup | Verified high-water prefix plus referenced immutable objects, online-backup snapshot, closed codes | [`backup-restore-v0alpha1.md`](../../protocols/backup-restore-v0alpha1.md) |
| Restore | Verified before any write, assembled in a `.partial` directory and renamed, no relaunch, non-terminal Runs reported `unknown` | same |
| Diagnostics | Redacted report: counts, booleans and caller-supplied identifiers only; no host path or credential | `src/llm_research_os/recovery/doctor.py` |

New published contracts: `backup-manifest`, `backup-report`, `restore-report`,
`workspace-diagnostic`, all `researchos.dev/recovery/v0alpha1`, generated from
Pydantic and checked by `researchos schema --check-all`. New threat-model rows
TM-093 (live-file copy or trusted manifest) and TM-094 (restore treated as
resumable, or diagnostics shared before inspection).

### Nine defects found before submission, and the correction

Four were found by self-review. Five more were found by an independent
adversarial review run against this branch; all five reproduced, and the two
critical ones are the reason the "verify trusts nothing in the manifest" claim
below had to be rewritten rather than merely restated.

1. **A persisted document could not round-trip.** `BackupManifest.objects`,
   `RestoreReport.reconciledRuns` and `DiagnosticReport.checks` were declared
   `tuple[...]`. The external documents inherit the strict event-document config,
   so `model_validate_json` rejected a JSON array for a tuple field: every
   manifest this package wrote failed its own `verify`. They are now `list[...]`,
   because these are serialized documents and JSON has arrays.
2. **The snapshot was not self-contained.** `EventStore` opens every database in
   WAL mode, so reading the snapshot left committed pages in a `-wal` sidecar
   that `snapshotDigest` did not cover. An image would have verified and then
   lost events on a restore that copied the single file. The snapshot is now
   collapsed to one standalone file before the digest is taken, and the image is
   re-verified from a copy. Collapsing to `journal_mode=DELETE` also exposed that
   `EventStore` can only open such a file read-write, so verification and
   restore open the store accordingly.

3. **An interrupted restore left a half-workspace.** The restore wrote directly
   into the destination, so a failure partway through left a directory that a
   retry refused as `workspace-exists`. It is now assembled in a sibling
   `.partial` directory and renamed into place, matching the backup path.

4. **The demonstration labelled its workspace with a project id its events did
   not carry.** The new restore ledger check refused the result, which is the
   check working. The demo now uses the id the packaged corpus already contains.

5. **Critical — `verify` trusted the manifest's object set.** It re-hashed each
   object the manifest *listed* and never re-derived which objects the event
   prefix references, so deleting one `objects[]` entry produced
   `verified: true` and a restore of a project referencing an object it did not
   hold. `verify` now re-derives the set from the events and requires equality.
   Eight further manifest fields were likewise trusted verbatim; the snapshot
   size, the last event digest, the schema version and digest, and the object
   size total are now compared.

6. **Critical — the SQLite snapshot URI was unquoted.** `#` terminates a URI
   fragment and `?` a query, and both are legal POSIX filename characters, so a
   workspace under `ws#frag/` was backed up from a *different* database and the
   resulting image was internally self-consistent. The path is now
   percent-encoded. A test backs up and restores a workspace whose path
   contains both characters.

7. **Restore verified the manifest and then re-read it.** The verified parse and
   the applied parse were different objects, a time-of-check/time-of-use gap on
   exactly the artifact an operator restores from a mounted archive. Restore now
   uses the manifest object the verification checked.

8. **A `storageKey` not derived from its digest passed verification** and then
   broke restore with an untyped `ArtifactNotFoundError`, outside the closed-code
   table. Each key must now equal `storage_key_for(digest)`. This also closes
   the NUL, backslash, and `.` keys the earlier traversal check allowed through,
   which surfaced a bare `ValueError` from the kernel.

9. **`ledgerMatches` was vacuous under a project rename and gated nothing.** The
   ledger fold filtered by project, so a rename to a project no event carried
   folded an empty ledger on both sides and reported a match. It now also
   compares how many events carried the project, and a difference is a
   `restore-ledger-mismatch` refusal rather than a reported boolean.

Also corrected: an untrusted manifest read is size-bounded; the snapshot no
longer reports the object-missing code when the snapshot itself is absent; the
doctor's migration branches were dead because `EventStore.__init__` refused a
too-new header first, so the header is now read through a plain connection and a
too-new store is reported as a downgrade; the backup path was changed to 16 GiB
before release; and the backup no longer replays the prefix three times.

Two pieces of dead code were removed rather than left as padding:
`EventStore.list_referenced_digests_page` and `EventStore.header_version`, each
added for this package and then superseded — the authoritative object set comes
from replaying the events, and the header is read without an `EventStore`. Both
had ended up referenced only by a test.

Three tests were also rewritten because they passed without testing their claim:
the redaction test proved `redact_object` works while saying nothing about
whether `doctor` calls it, the API-version assertion had a dead `or` disjunct,
and one was named for traversal while only exercising a regex mismatch.

### Local verification

Executed on the R15 branch from a clean `uv sync` (Python 3.12.14, Linux
container), marker selection `not oci_live and not slow and not ray_native_live
and not native_remote_live`:

- Recovery suites: 140 tests collected across `tests/test_recovery_backup.py`,
  `tests/test_recovery_doctor.py`, `tests/test_recovery_contracts.py`,
  `tests/test_recovery_trials.py` and `tests/test_problem_report_type_vocabulary.py`;
  138 passed and 2 skipped locally because this container runs as root and a
  privileged reader ignores mode bits. Those two run in ordinary CI.
- Whole selected suite: **2,385 passed, 0 failed, 2 skipped, 30 deselected.**
  This suite previously reported 4 failures in `tests/test_native_ssh_live.py`
  and recorded them as pre-existing environment failures, verified as such on an
  untouched worktree at `main`. That explanation was correct but the failures
  were **not** in fact unavoidable, and the honest reading of "pre-existing"
  should have been "not mine" rather than "not fixable". The cause was the test
  harness, not the container: the local transport runs the real remote command
  `python3 -I -c ...`, resolving `python3` from `PATH` inside this container,
  which is 3.11.2 while the probe requires 3.12+ on a worker host. The probe was
  correct to refuse the simulated host; the harness was simulating the wrong one.
  `_setup` now pins `PATH` to the interpreter running the suite, a guard test
  fails loudly if that pinning stops working, and the old-host rejection is
  still tested directly. All 39 tests in that file pass. CI runs 3.12/3.13, where
  they had passed all along.
- The two skipped `test_recovery_*` tests are skipped only because this container
  runs as root and a privileged reader ignores mode bits. They run in ordinary CI.
- Coverage: **85.686539%** (30,441/35,526 statement and branch counts), above the
  unrounded 85% floor. `scripts/check_coverage.py` independently reproduces the
  integer counts and exits 0. The new `recovery/` package is 92.7%–100% by file.
- `ruff check .` clean, `ruff format --check .` clean, `mypy src` clean over 267
  files, `researchos schema --check-all` current, `scripts/event_catalog.py
  --check` and `scripts/project_status.py --check` pass, and
  `node conformance/digest/verify.mjs` passed 13 RFC 8785 vectors.
- Clean install outside source: `uv build` then the wheel installed into a fresh
  venv and `wheel_smoke.py` run with `-I` outside the checkout reported
  `doctorHealthy: true`, `packagedBundle: true`, and a backup/verify/restore
  round trip with `ledgerMatches: true` and `appendedEvents: 0`.
- Ruff, format and mypy are local results. **No CI run exists for this branch
  yet**, and the 85% coverage floor has not been measured on this branch.

### Gaps and required inputs

- No replication, encryption, scheduling, retention, or artifact garbage
  collection for images. Copying an image off the machine is an operator action.
- **Downgrade is refused, not supported.** A store whose header is newer than
  this build reports `control.migration: failed`.
- Worker identity is not part of an image. A restored Worker root is empty and
  re-onboarding goes through the existing R07 flow; no live two-host restore was
  exercised because that access is still missing (COMM-0004).
- An earlier change to `init_workspace` that created the control store was
  reverted: `ApplicationService.open` reporting `store-missing` on a fresh
  workspace is the accepted R02 contract. The doctor reports that state instead.
  A fresh workspace consequently has no EventStore until the first append, and
  `evidence import` on a brand-new workspace fails until some other command
  creates the store. Recorded as a review item rather than changed unilaterally.
- The R10–R14 ledger rows link to `#r1x-candidate-evidence` anchors that no
  section defines. This section defines the R15 anchor; the earlier ones remain
  broken and are not repaired here because that rewrites another package's
  record.
- Independent trial evidence is R16 and is not present. See
  [`r16-independent-trials.md`](../../evidence/m3/r16-independent-trials.md).

### Next action / owner

Reviewer decides whether R15 may close on a local verified prefix backup with no
replication or encryption, or requires more. Checkpoint D additionally needs the
R16 trials, which need the maintainer's invitations.

## Issue #53 evidence checklist

Review closure independently when the relevant R03–R06 evidence is integrated:

- Plan-bound valid authorization consumed before real native user code starts.
- Denial for wrong/stale/substituted bindings and required expiry/revocation cases.
- Durable Run/Attempt/audit outcomes for launch, failure, and uncertain execution.
- Actual cancellation/stop observation and conservative unknown recovery.
- Explicit supported profile/platform limitations and evidence identities.

Add R08 remote evidence for any remote claim. The maintainer reviews closure;
R01 closes nothing, a package merge does not auto-close it, and R16 is not an
additional blanket prerequisite. Ed25519 audit attestations remain distinct from
Worker launch grants. Publication, paid resources, and public-service acceptance
are separate decisions.


R07 follow-up: PR #116 at `087da05` passed all 1,594 selected tests on Ubuntu
3.13, but failed the 85% coverage gate at 84.804%. The follow-up adds remote
entrypoint/input refusal and bounded SSH response tests plus a loopback-only
reviewed tunnel. This newer container denies even TCP socket creation (`EPERM`);
focused checks here returned 73 passed, 2 failed (socket permission), 2 skipped.
Standard CI must verify the follow-up at its actual published commit.

After local loopback permission was granted, the restored focused suite passed
77 tests. Additional prerequisite/timeout cases are included in the final
candidate. Ruff, format and mypy checks passed. Full standard CI remains the
authoritative cross-platform and coverage gate for this follow-up.

At `4ff19dffae6e7d072a5d3775b2bc4c1129be48c8`, CI run
[255](https://github.com/victorzhong0110/llm-research-os/actions/runs/36671646529)
passed Ubuntu Python 3.12/3.13/3.14 and Linux OCI. macOS 3.13 passed all
1,609 selected tests but coverage was 84.984%, below the gate. The local
complete suite also passed 1,609 tests with 84.991% coverage. The next
follow-up adds prerequisite, credential privacy, bounded pack and failed-install
cleanup tests; its 37 SSH tests, ruff, format and mypy checks passed locally.

At `f0b8914fe6b6f9368c5ad8eef9727600d7828d98`, CI run
[256](https://github.com/victorzhong0110/llm-research-os/actions/runs/36672183995)
passed all Ubuntu/OCI checks. macOS coverage reached 85.106%, but the output
limit fixture's shell pipeline encountered a denied group cleanup signal,
masking its original bound error. The follow-up preserves that error, falls
back to killing its own SSH child, and uses a single-process output fixture.
The 38 SSH tests and static checks passed locally before publication.

## R16 candidate evidence

Status: **trial kit prepared and machine-checkable on the R16 branch; no trial
performed; not merged, not accepted.** Checkpoint D is open and cannot close from
this branch. Each record additionally awaits the participant's own confirmation,
which no implementer or observer can supply for them.

R16 is the one package whose deliverable is human work by people who did not
implement the system. What this branch can honestly contribute is the kit that
makes such a trial measurable and the record that makes its absence visible.

### Delivered

| Item | Where |
| --- | --- |
| Fixed trial tasks T1–T5 and REMOTE, offline, no key, no GPU | [`r16-independent-trials.md`](r16-independent-trials.md) |
| A validated `TrialRecord` / `TrialKit` contract and published schemas | [`trial-record`](../../schemas/trial-record/v0alpha1.schema.json), [`trial-kit`](../../schemas/trial-kit/v0alpha1.schema.json) |
| `researchos trial scaffold/validate/aggregate` | `src/llm_research_os/cli/trial_commands.py` |
| TRIAL-01..05 pending table with owners | same |
| Aggregated per-package roll-up, checkpoint status, and BACKLOG-01..12 | [`m3-closure-record.md`](m3-closure-record.md) |

### The kit is machine-checkable, not a prose template

A trial record kept as free text cannot be validated, aggregated, or
distinguished from one the implementer filled in. `TrialRecord` is a closed
contract instead:

- `interventions` and `confusionObserved` are the measurement, and a record
  authored by `recordedBy: implementer` is **refused** if either is non-empty.
  The guard is the point: without it, "no confusion observed" and "nobody wrote
  down the confusion" look identical.
- `evidenceAttached` must be non-empty, so a record that cannot be reviewed
  later is refused now.
- `task` is restricted to the agreed task list, so a report from outside the kit
  cannot be aggregated with the rest of R16's evidence.
- `researchos trial scaffold` writes deliberately **invalid** record slots and
  exits `1`. An unrun trial therefore reads as unrun in a machine-readable way
  rather than as a missing file.
- `researchos trial aggregate` reports participants, tasks covered, recorded
  remote journeys, and the blockers still unresolved, and reports
  `checkpointD: false` until two participants and one remote journey exist.

### One main-path defect fixed, and its path re-tested

Found during R15 implementation rather than during a trial, and recorded as
such: a fresh workspace has no EventStore until the first append (the accepted
R02 contract), and the first command an operator ran against one returned
`EventStoreSchemaError: database does not exist: /absolute/host/path`. That
rendered a host path into CLI output, which the rest of the project treats as a
disclosure defect, and gave no next step.

`EventStoreSchemaError` now carries a `code` attribute, and the
missing-database message is path-free and actionable: the control store does not
exist, a fresh workspace has no EventStore until a command appends a fact, or
restore one from a backup image. The R02 contract is unchanged; only the message
changed. This does **not** close TRIAL-04, which is scoped to defects found in
TRIAL-01/02.

### `ProblemReport.type` is now a code, adopted

The proposal below was taken on maintainer instruction. `EventStoreSchemaError`
joins the coded errors, so `type` carries `event-store-absent` rather than the
class name, and `docs/protocols/problem-report-v0alpha1.md` now states the rule:
`type` is a stable machine identifier, a caller may branch on it, it is never a
class name, and an error with a closed code set surfaces its code while one
without falls back to its class name. The three CLI tests that pinned
`EventStoreSchemaError` were updated, and `tests/test_problem_report_type_vocabulary.py`
pins the vocabulary and the one-directional fallback.

**Writing the test found a second leak the first fix had missed.**
`_validate_database_path` had four rejections that still interpolated the host
path — missing parent directory, inspect failure, symlink, and not-a-regular-file
— and none of them had a test. The first version of the new test only covered
the missing-database case and passed, because the path it used had a missing
*parent*, which is a different branch. All four now carry no path, and the
parameterised test covers each. Every control-store message is now path-free;
`evidenceAttached` and the absent-database message keep their actionable halves.

### Implementer self-run of T1–T5 — four main-path defects, and what it is not

The plan's "fix main-path defects" deliverable needs defects, and the only
defects that count come from TRIAL-01/02. Those have not run. So the implementer
ran T1–T5 themself, from a clean wheel outside any checkout, to find defects that
a person who did not build this would hit first.

**This is not a trial and is recorded as none of the things a trial is.** It is
not TRIAL-01 or TRIAL-02, it produces no `TrialRecord`, it has no participant,
and it cannot be self-confirmed. It contributes implementation findings only. A
rehearsal by the implementer is evidence about the *product* and never about its
*usability for someone else*. The R02/R15 acceptance language is unchanged and
Checkpoint D is exactly as unclosable as it was.

What it found, and what was fixed:

| # | Defect | Why it matters | Fix |
| --- | --- | --- | --- |
| 1 | `researchos app init` required four layout arguments with no defaults, no examples and no help text | T1 forbids cloning the repository, so `--help` is the only documentation a participant has — and it did not carry the layout convention. T2 as written was not executable. | The four arguments now default to the conventional `control/events.sqlite`, `cas`, `worker` under `--root`, with help text and a description carrying an example. Explicit values still work. |
| 2 | A freshly initialized workspace reported `healthy: false` with `control.store`, `control.migration` and `objects.referenced` all `failed`, `reason: absent` | Those three are the *expected* state of a workspace that has not appended a fact (the accepted R02 contract). T2 tells a user to init a workspace and then read the diagnostic; what they read was "unhealthy", three times. | Reported as `skipped` with `reason: not-yet-populated` and a note. A fresh workspace is now `healthy: true`. |
| 3 | `objects.referenced` reported `verified: false` on a shallow run that had re-hashed nothing | The key reads as "these objects are not fine" on an `ok` check. | Split into `bytesVerified` (needs `--deep`) and `presenceChecked` (always true), so the two meanings cannot be confused. |
| 4 | `backup create` took `--out` and `backup restore` took `--root`, so `--root` meant source on one subcommand and destination on the other; T4's text named neither | A participant copying the flag vocabulary from T3 to T4 fails. Found because the self-run did exactly that. | `backup restore` accepts `--out` as well, with `--root` kept working; both now say "this command's output". |

One further gap was found and is **not** closed here: T3 says "import the
example evidence", but the only copy of that example lived in the repository
that T1 forbids cloning. The evidence request and its Markdown source are now
packaged inside the wheel beside the rest of the offline corpus, and
`researchos workspace demo` prints the exact import command as its first `next`
hint, so the journey is runnable by copy-paste with no checkout. That makes T3
executable; it does not make it observed.

### The CLI layer was the weakest code in the package

The recovery suites tested the library functions underneath the new commands and
never the commands, so the dispatch layer went in almost uncovered. It was the
three lowest-covered modules in the project, and all three were added by this
work:

| Module | Before | After |
| --- | --- | --- |
| `cli/trial_commands.py` | 35.53% | **93.42%** |
| `cli/recovery_commands.py` | 39.00% | **90.00%** |
| `cli/application_commands.py` | 52.27% | **81.82%** |

`tests/test_recovery_cli.py` drives `main(argv)` directly — the same
`build_parser`, the same handlers, the same exit codes — rather than spawning
`python -m llm_research_os`. In-process is deliberate: a child process reports
coverage to a different file, so a suite that spawns the CLI is not measurable
at all, and the original version of this file passed 31 tests while moving
`trial_commands` from 35% to **0%** as far as the report was concerned.

What an in-process harness cannot show: a broken interpreter, a missing console
script, or an uncaught crash's exit status. Those stay with the installed-wheel
smoke, which does run the real entrypoint.

### The doctor can now tell a fresh workspace from a gutted one

The self-run left one honest weakness, and it was closed rather than documented
as a limitation. The problem: `init_workspace` does not create a control store,
so "no store" is a normal state — and deleting a store leaves exactly the same
evidence. A workspace that lost its data was reported as merely unpopulated.

The fix is a lifecycle marker, `.control-store.json`, written beside the control
database the first time a store is created, plus a second signal covering the
case the marker cannot: `init_workspace` **always** creates the control
directory, so its absence is itself proof of removal. `restore` writes the marker
too, because the restore path bypasses `EventStore`'s create branch and would
otherwise leave a restored workspace unable to tell that its store was deleted
later.

| Workspace state | `control.store` | `healthy` |
| --- | --- | --- |
| Initialized, never appended | `skipped` / `not-yet-populated` | `true` |
| Database deleted, marker survives | `failed` / `removed` | `false` |
| Whole control directory removed | `failed` / `removed` | `false` |
| Restored, then database deleted | `failed` / `removed` | `false` |

The marker holds a kind, a version and a timestamp — no path, no project id,
nothing to redact. It is a local lifecycle artifact rather than a published
contract, on the same footing as `workspace.json`, and it is written
best-effort: a store that cannot also write a sibling marker has already failed
for a reason the caller will see, and refusing to open it would turn a
diagnostic aid into a hard dependency.

One limitation of the self-run remains, stated rather than smoothed over:
- The self-run confirms the product works when the commands are known. Whether
  the commands are *discoverable* is exactly what T1–T5 measure, and defects 1,
  3 and 4 were all discoverability failures that only a person following the task
  text would hit. Fixing them should change what a trial finds, which is a reason
  to run the trial, not a reason to skip it.

### A trial record is pending until the person confirms it

The contract already refused an implementer-authored measurement. It did not stop
an **observer** from filing every record on a participant's behalf, and an
observer-authored roll-up is not evidence that anyone took part — it is evidence
that someone watched. So confirmation is now a field with rules:

- `participantConfirmed` defaults to `false`, and `confirmedAt` must be present
  when it is set and absent when it is not.
- An implementer may not set it at all. Only the participant, or an observer who
  has the participant's confirmation, may.
- `confirmedParticipants`, `completedTasks` and `remoteJourneys` are all
  **confirmed-only**. `aggregate` reports `participants` and
  `observedParticipants` separately, plus `pendingConfirmation`, so a kit full of
  unconfirmed records shows both numbers rather than quietly counting as complete.
- `scaffold` writes `participantConfirmed: false` explicitly, so "not yet
  confirmed" is a recorded state rather than an absent field readable as an
  oversight.

A confirmed `REMOTE` record is the only thing that satisfies the authorized-remote
requirement, which is the one requirement that most clearly has to come from a
person rather than from the project's own records.

### Three decisions taken under maintainer delegation

On 2026-10-05 the maintainer delegated three review decisions to the implementer.
Each is recorded as an implementer decision under delegation, not as maintainer
acceptance, and none of them accepts a package.

| Decision | Choice | Reasoning |
| --- | --- | --- |
| May R15 close without replication, encryption, and downgrade support? | **Yes, with those three named as accepted limitations** | None is in the R15 acceptance criteria; the plan's R15 out-of-scope list already names publishing, garbage collection, and naive SQLite copying. Adding them would be new scope, and a backup tool that silently claims durability it does not provide is worse than one that names its limits. Recorded as limitations in the protocol and guide, and as BACKLOG-12. |
| What to do about the R10–R14 undefined anchors? | **Add a routing table; do not edit another package's record** | The anchors are broken, but filling them means writing evidence attributed to packages this one did not build. The table routes a reader to the authoritative PR instead. Whether each should be filled retroactively stays open as BACKLOG-04. |
| Should a fresh workspace materialize its EventStore at init (BACKLOG-06)? | **No. Keep the R02 contract; fix the error instead** | `ApplicationService.open` reporting `store-missing` on a fresh workspace is accepted R02 behaviour. Changing `init_workspace` to create the store would alter an accepted package's semantics to remove a rough edge, which is a scope change disguised as a convenience. The closed-code error above removes the actual harm. BACKLOG-06 stays open for a scoped decision. |

### What is not delivered, and cannot be from here

| Requirement | State |
| --- | --- |
| Two independent participants completing the core journeys | **Not performed** (TRIAL-01/02) |
| Interventions, confusion, and recovery recorded per task | **Not performed** |
| At least one authorized remote journey | **Not performed** — blocked on COMM-0004 access |
| Main-path defects fixed and paths re-run | Not applicable until a trial finds one |

No trial was simulated, rehearsed by an implementer, or inferred from local
results. A rehearsal by someone who built the system is not a trial, and the
plan states that unperformed live work remains pending-live and prevents
claiming the checkpoint complete.

### Next action / owner

Maintainer performs the invitations and authorization for TRIAL-01/02 and
supplies the access TRIAL-03 needs. The planning/review assistant reconciles the
draft closure record against real outcomes. The maintainer then reviews
Checkpoint D.



## R15 and R16 review supplement — 2026-10-06

Earlier candidate sections preserve the implementer's pre-push local record;
their statements that no CI exists are historical and are superseded here.
The maintainer authorized review, repair and integration of all submitted PRs.

- R15 repair head: `d50aff3b8caeb09b20e1fafbd1ae9e137c119a2c`, CI
  [37454556583](https://github.com/victorzhong0110/llm-research-os/actions/runs/37454556583).
  Private snapshot bytes are rebound to the verified manifest before opening;
  external restore layouts are refused, staging paths are unique and manifest
  reads are bounded. Local recovery checks: 101 passed, two root-only skips.
- R16 preserves those repairs, corrects trial task aggregation, closes the
  remaining SQLite initialization path leak and quotes demo command arguments.
  Combined local recovery/CLI/trial/native-SSH tests: 227 passed, two root-only
  skips; final contract and read-bound suites: 72 passed. Ruff, format, mypy,
  generated schemas, digest conformance and package build passed.
- Recovery and trial contracts now have explicit valid/invalid examples under
  `examples/recovery/` and `examples/trial/`; all are labeled simulation or
  unconfirmed contract fixtures, never human or live execution evidence.
- `trialTaskCoverageComplete` is derived from confirmed, completed T1–T5 records
  for each of two distinct participants and a completed REMOTE record. Fixed
  requirements cannot be omitted, and record IDs cannot clear them. Extra
  blockers remain open. `checkpointD` is always false until a separate maintainer
  acceptance process; independence, remote authorization and evidence require
  reviewer verification.
- Reviewed integration is limited to the submitted engineering slices. Full
  R11–R14, R16 and M3/Checkpoint B/C/D acceptance gaps remain unchanged. No
  independent human trial, selected-host/GPU evidence, release or deployment is
  manufactured by merging these PRs.

See [the review record](../../reviews/pr139-140-2026-10-06.md) and the final
[#139](https://github.com/victorzhong0110/llm-research-os/pull/139) /
[#140](https://github.com/victorzhong0110/llm-research-os/pull/140) metadata for
remote heads, final checks and exact integration SHAs.

R15 integration confirmed on 2026-10-06: #139 merged at `76e16d2aae2cc748e0e9c944794dc574cbc66937` after final-head CI 37454556583 passed all five Python, actual browser, Ray, native and OCI gates. Linux Python 3.12: 2328 passed, 15 deselected; coverage 86.13%, unrounded floor check passed. The integrated tree is `23f3c89caad63a9055eb8ee66358c5ae90d82750`, identical to the reviewed repair tree. #140 preserves that tree's recovery fixes and records this actual main as a parent; its final-head CI remains the gate for its own integration.


## R11 engineering continuation — 2026-10-07 candidate

Base: `a32493efb800a3c573ad49aef7077b006d6569ca`; branch
`work/20261007-r11-completion`. The maintainer explicitly assigned engineering
continuation while separately performing Mac and human work. See
[REVIEW-20261007-R11](../../collaboration-log.md#review-20261007-r11--assigned-engineering-continuation).

- Browser native inspection binds exact installed material; existing reviewed
  native start and checkpoint restore remain subject to authorization/grant,
  byte/platform/limit/lineage and cancellation checks. No UI-created authority.
- A durable Run reservation prevents duplicate dispatch after uncertain HTTP or
  receipt failure. Observation and reconnect use existing identity and facts.
- Backup verification/restore use confined names, a verified pinned manifest and
  new-root recovery. Restore appends nothing and never relaunches historical work.
- Automated CPU fixtures execute actual local processes. Source/target checkpoint
  tests verify independently authorized new work consuming the prior result.
  These are synthetic test inputs, not selected-host/GPU or participant evidence.
- Candidate checks, exact final head/CI and integration are recorded by the PR.
  The local browser download failed in this runtime; actual browser validation
  is required in the designated CI gate before integration.
- Full B/C/D acceptance, selected-host/GPU proof and independent human trials stay
  open. This candidate does not change historical acceptance or package meaning.


## R12 engineering continuation — 2026-10-07 candidate

Sequential base: `5a99c71e4ac61300e26c49fab8a9401c162d0585` (#141), whose final-head CI 37627514776 passed all applicable Python/browser/Ray/native/OCI gates. This candidate preserves #134 review fixes while adding [the browser research workflow](../../guides/m3-research-workflow.md).

- Operator-installed Mock/compatible profiles, inspected material binding, durable per-call reservation, first-fact caller-head CAS and observation-only recovery. Actual local HTTP contract tests require no paid model.
- Dedicated frozen inbox imports with versioned source, bounded extraction and distinct reading/training rights. Imported text and model output grant no tool or launch authority.
- Typed proposals bind actual base/candidate CAS specs and a recomputed semantic diff; unresolved citations, stale base, invalid/extra output and actor mismatch cannot become validated drafts. Human edits preserve generated CAS evidence and are human-attributed.
- Shared research facts support accept/reject/amendment, supplied questions, human answers and dissent. Rejection creates no Run; explicit dissent overrides and rationale survive refresh.
- Budget folds report approved/consumed/outstanding/open reservations; uncertain dispatch is not released or repeated and provider invoice cost remains unknown.

Local verification: 139 focused tests and a subsequent 49-test contract rerun passed; schema/catalog/digest, lint/type/format, frontend build and fresh installed-wheel checks passed. Full local suite retained 12 POSIX/process/socket failures (2412 passed, 21 skipped, 15 deselected); unrounded coverage was 31067/36360 = 85.442794%. Neither local full-suite success nor local browser success is claimed.

Validation is factual candidate evidence, with exact submitted head/final CI recorded in the PR and collaboration log. Local Chromium executable is absent, so no local browser pass is claimed. The synthetic offline demonstration stages zero calls/Runs and does not prove product or research improvement. **Full R12, real human workflow and Checkpoint C acceptance remain separate and open.** The canonical package meanings, accepted M1/M2 evidence, B/live and D/human gaps are unchanged.
