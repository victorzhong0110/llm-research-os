# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This tree has no tagged release yet. The first tag is `v0.1.0-m1`, cut when M1
closes. Until then the version in `pyproject.toml` stays `0.0.0`.

## Unreleased

### Added

- M0 kernel proof (closed 2026-09-03; [ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)).
- Post-M0 governance: [ADR-0038](docs/adr/0038-charter-errata-after-m0.md),
  [ADR-0039](docs/adr/0039-human-help-period-purpose.md),
  [ADR-0040](docs/adr/0040-english-primary-and-engineering-standards.md).
- [Engineering standards](docs/engineering-standards.md). English is the working
  language; `README.zh-CN.md` and `CONTRIBUTING.zh-CN.md` are the shop-window
  translations.
- CI coverage floor 85%, ruff `S` on `src/`, Python 3.14 allow-fail job, macOS
  matrix, fork-only DCO, Human authorship check, Dependabot.
- `src/llm_research_os/py.typed`.
- Hypothesis properties for JCS stability, Run/Attempt folds that ignore foreign
  runs, and Pydantic round-trips of valid spec/event examples.
- [NOTICE](NOTICE) names copyright owner `victorzhong0110`. `LICENSE` stays the
  unmodified Apache-2.0 text.
- M1-0: SQLite schema v2 verified high-water cache and rebuildable query tables
  ([ADR-0041](docs/adr/0041-verified-high-water-cache-and-query-tables.md);
  Issues #39 / #40). Typed [`SecretRef`](docs/protocols/secret-ref-v0alpha1.md)
  and redaction. Optional ResearchEvent actor `kind` / `modelId`. SimulatedRuntime
  emits `attempt.cancelled` / `run.cancelled` from a recorded cancel request.
- M1-1: `proposal.submitted`, `dissent.recorded`, `decision.recorded`, rebuildable
  [`ResearchLedger`](docs/protocols/research-decision-objects-v0alpha1.md), and CLI
  `proposals submit` / `dissents record` / `decisions record` / `research ledger`
  (Issue #41).
- M1-2: `ModelProvider` with declared/measured/allowed capabilities,
  `DeterministicMockProvider` from fixtures, and `ai.call.*` facts that store
  prompt/output digests (optional artifact refs), never inline text
  ([ADR-0017](docs/adr/0017-minimal-model-interface.md)). Zero network.
- M1-3: local Markdown/PDF import to artifact CAS and `evidence.imported`
  with default `LicenseRef-Unknown` ([ADR-0019](docs/adr/0019-evidence-rights-by-use.md)).
  Adversarial notes cannot enable mock tools (TM-006). PDF extraction is
  subprocess-isolated with page, character, wall-clock, and best-effort
  memory limits (TM-041). The parser subprocess receives a minimal environment
  and does not inherit process secrets.
- M1-4: OpenAI-compatible HTTP adapter (loopback default). Remote endpoints
  require `SecretRef`, `read.external_api`, HTTPS, a recorded project CNY
  limit, and a matching request cap. First runtime-enforced CNY caps:
  `budget.limit.recorded` / `reserved` / `consumed` / `exceeded` / `released`.
- `budget.limit.recorded` as a human-only project CNY cap. Positive reservations
  must repeat that cap; a request cannot raise it by itself.
- M1-5: seeded synthetic `training.step` / `evaluation.metric` from
  SimulatedRuntime and `researchos report RUN` static HTML/Markdown with
  research, training, cost, and lineage sections linked to `eventId`.
- M1-6: SimulatedRuntime consumes one local `{eventId, sequence}` citation of
  `plan.authorization.evaluated` before lifecycle writes
  ([ADR-0042](docs/adr/0042-m1-local-authorization-consume-and-closure.md)).
  Issue #19 local consume is delivered; signatures, expiry, and revocation are
  Issue #53. `v0.1.0-m1` remains not-delivered. Numbered slices are not
  the M1 checkpoint (#38).
- Question channel: `question.asked` / `question.answered`, CLI
  `questions ask` / `questions answer`, ledger question entries and counters,
  and report attention cost (Issue #42). Answers are data with rights, not
  instructions. `QuestionLedgerEntry` is a status discriminant: `open` forbids
  answer fields; `answered` requires them.
- `researchos m1 prove`: one offline corpus chain (Mock proposal through
  simulated report, or reject without `run.queued`). Issue #38 stays open.
- M2-0 loopback Worker plane, HMAC grants (expiry/revoke/consume), CPU
  helper over a CAS-pinned brick bound to an authorized `execute.local`
  plan, and `researchos m2 prove`
  ([ADR-0043](docs/adr/0043-m2-loopback-worker-and-hmac-grants.md)). Not a
  paid GPU run, not NativeProcessRuntime, and not a kernel sandbox.
- Isolated control plane and Worker processes with private CAS, pinned
  loopback HTTPS/JSON, credential files, and reconnect
  ([ADR-0044](docs/adr/0044-isolated-control-plane-and-loopback-https.md)).
  Not a cross-machine proof.
- CPU `OCIContainerRuntime` with digest-pinned docker, `execute.oci`, and
  a CAS python brick inside the container
  ([ADR-0045](docs/adr/0045-cpu-oci-container-runtime.md)). Host Python
  stays the trusted helper. A missing engine fails closed and is not a
  mocked container success. Not GPU.
- Non-root OCI `/in` bind (0755/0444 for UID 65534) and designated Linux
  OCI CI that must not skip ([ADR-0049](docs/adr/0049-oci-nobody-bind-and-required-linux-ci.md)).
- Worker stop/fault recovery: cancel request is not observed stop;
  `work.completed` reconciles Run/Attempt; unknown cannot auto-succeed or
  rerun; CPU checkpoint JSON is inspectable
  ([ADR-0046](docs/adr/0046-worker-stop-fault-recovery.md)).
- EventStore 10k/100k append/replay/claim/report baseline and CAS metric
  chunks (`researchos m2 bench`); receipts are not SLA
  ([ADR-0047](docs/adr/0047-eventstore-performance-and-metric-sampling.md)).
- Pinned `ms-swift==4.5.2` parse/plan adapter (`researchos training plan`);
  argv only, no GPU execution
  ([ADR-0048](docs/adr/0048-pinned-ms-swift-adapter.md)).
- Observed execution identity and cancel supervision: resumed
  `cancelRequested` is not `cancel-observed`; host process groups and OCI
  containers are stopped then confirmed; cloud instance stop is forbidden
  ([ADR-0050](docs/adr/0050-observed-execution-identity.md)).
- Live CPU fault acceptance: cancel, timeout, Worker kill, control-plane
  restart, and disconnect-after-upload assert real process state;
  `plane.fail` is not observed stop; pending complete retries without
  rerun ([ADR-0051](docs/adr/0051-live-cpu-fault-acceptance.md)).
- Worker/RunControl usage evidence: mixed research/budget/Worker append,
  claim, cancel, and coordinate; isolated Worker plus cited report;
  `m2 bench` fill is not this path; ordinary hosts label
  `skipped-no-runtime` / `skipped-no-image`
  ([ADR-0052](docs/adr/0052-control-path-usage-evidence.md)).
- GPU experiment sheet: AutoDL RTX 4090, 45 minute wall, proposed ¥20 cap,
  CUDA image method, instance 关机 ≠ container stop; `gpu: not-run`
  ([ADR-0053](docs/adr/0053-gpu-experiment-sheet.md)).
- Process observation is running/exited/unknown; a failed `ps` or `/proc`
  probe is not exited; stop waits for the process group
  ([ADR-0054](docs/adr/0054-process-observation-tristate.md)).
- Live OCI fault acceptance: cancel, timeout, Worker kill, control-plane
  restart, external stop, and inspect failure assert real container
  state; designated CI runs `-m oci_live` and must not skip
  ([ADR-0055](docs/adr/0055-live-oci-fault-acceptance.md)).
- Independent GPU training execution profile: `gpu-oci-container` /
  `execute.gpu`, closed device and mounts, pinned ms-swift argv bound;
  `researchos training bind` does not execute
  ([ADR-0056](docs/adr/0056-gpu-training-execution-profile.md)).
- GPU data snapshot and checkpoint loop: pinned Hub revision, offline
  `training snapshot`, overlay `--resume_from_checkpoint` vs `--adapters`,
  bounded CAS collect of `/work/output`; receipts stay `gpu-not-run`
  ([ADR-0057](docs/adr/0057-gpu-data-checkpoint.md)).
- Remote Worker pack: TLS SAN bind policy, independent EventStore/CAS
  workdirs, environment inventory and live step list; `secondHost` is
  `not-provisioned`; STATUS is `pending-live`. A loopback URL is not a
  cross-machine proof ([ADR-0021](docs/adr/0021-remote-worker-transport.md)).
- GPU execution-chain acceptance checklist: PR stack, stop/resume/artifact
  matrix, Linux OCI live evidence, pending-live two-host, unpaid experiment
  sheet ([docs/guides/m2-gpu-chain-acceptance.md](docs/guides/m2-gpu-chain-acceptance.md)).

### Changed

- `src/` fail-closed checks use `raise`, not `assert` (they must survive
  `python -O`).
- M1-0: a missing `integrity_checkpoint` row is an invalid cache (full verify,
  recreate when writable). `RunControl` always folds the frozen prefix from
  sequence 0; the snapshot cache is not fold authority. A cache-write failure
  after a committed lifecycle fact does not fail the append.
- M1-1: `ResearchControl` validates the complete prospective ledger before the
  CAS append. The 33rd override of one dissent is rejected before commit.
  Dissent `targetKind` `conclusion` remains reserved. Decision `targetKind`
  `question` is valid once a `question.asked` fact exists (Issue #42). Ledger
  `run_ids` come only from `run.queued`; a run-targeted `decision.recorded`
  cannot create the Run it cites.
- M1-3: PDF text extraction no longer parses every page in-process before
  applying the character cap. A compressed PDF that expands past the work
  bounds fails closed without echoing extracted text. The worker environment is
  an allowlist (TM-041).
- M1-4: HTTP generate decides reserve-or-exceed on one frozen budget head
  (`BudgetControl.reserve_or_exceed`) and CAS-appends `budget.reserved` or
  `budget.exceeded` before opening a socket. `_apply_reserved` itself rejects a
  reservation that would break `consumed + outstanding + requested <= cap`.
  Outstanding reservations hold the cap. Loopback consumes only when cost is
  known; remote leaves the reservation open and must declare a positive cap and
  reserve. Transport failure after start keeps the reservation when the request
  may already have left this process (`dispatched=true`; timeout, oversized, or
  malformed responses). `budget.released` is only appended when the adapter can
  prove the request was not dispatched, or when `ai.call.started` itself failed
  to commit. Consume/release must match the reservation (`callId`,
  currency, cap, amount). Endpoints reject query/fragment/userinfo; transport
  pins DNS and refuses private, link-local, metadata, and mixed answers (TM-042).
- M1-5: `researchos report` folds research, budget, lineage, and consumed
  authorization from one frozen prefix. `--project` selects `(projectId, runId)`
  before treating a colliding `runId` as ambiguous. Synthetic metric resume
  compares the canonical caller document, not only id+type. Markdown/HTML event
  links use HTML `<code>` so punctuation in an id cannot break a code span.
- M1-6: `SimulationRequest` requires `authorization: {eventId, sequence}`.
  Committed M0 request files without that field no longer validate.
  SimulatedRuntime resume of a Run that omitted the citation fails closed
  (`authorization-citation-missing`).
- M2-0: Worker grants cite a recorded `execute.local` authorization and the
  CAS execution object (image, config, inputs, runtime). Grant recording
  rebuilds that plan from spec+registry and binds project, revision,
  workflow, planned task, and execution object. `simulate` cannot start a
  brick. Script A's authorization cannot grant script B. complete/fail bind
  token, grant, and lease (project, worker, grant, task, run, attempt,
  nonce, expiry). Revoked or expired grants reject new results; matching
  terminal complete/fail stays idempotent. Stdout/stderr limits apply while
  pipes are read. POSIX process groups are killed after the parent exits so
  inherited-pipe children cannot outlive the helper.
- Worker claim-path rebuild folds only Worker event types after a verified
  high-water. Static reports stream the frozen prefix and keep lineage on
  the matching Run; they cite spec/runtime/image/config/output digests.
  High-frequency metrics go to CAS chunks, not one EventStore fact per
  step ([ADR-0047](docs/adr/0047-eventstore-performance-and-metric-sampling.md)).
