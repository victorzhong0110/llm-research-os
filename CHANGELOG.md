# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This tree has no tagged release yet. Milestone acceptance does not publish a
tag or package (ADR-0062). The version remains `0.0.0` until a separately
authorized release.

## Unreleased

### Added
- R15 installation, startup, backup, and recovery. `researchos backup create |
  verify | restore` produce a self-describing backup image of a **verified
  high-water prefix** of the EventStore plus the immutable CAS objects that
  prefix references. Four new published contracts
  (`backup-manifest`, `backup-report`, `restore-report`, `workspace-diagnostic`,
  all `researchos.dev/recovery/v0alpha1`) are generated from Pydantic and checked
  by `researchos schema --check-all`.

- R15 the SQLite copy is taken with the online backup API and then collapsed to
  one standalone file. `EventStore` opens every database in WAL mode, so
  reading a snapshot leaves committed pages in a `-wal` sidecar that the manifest
  digest does not cover — an image would have verified and then lost events on
  restore. The image is re-verified from a copy before it is published, and
  `backup verify` re-derives the snapshot digest, every object digest and size,
  and the event count from the image itself.

- R15 a restore copies facts and nothing else. It appends no event
  (`appendedEvents` is `0`), starts no Worker, dispatches no Run, and resumes no
  Attempt. A Run that was not terminal when the image was taken is returned in
  `reconciledRuns` as `unknown` with `reconcile-manually` (ADR-0054). A
  referenced object missing from the workspace aborts the backup rather than
  producing an image that restores to a broken project.

- R15 `researchos workspace doctor [--deep]` reports a redacted diagnostic:
  manifest, root isolation, control store, migration header, referenced-object
  coverage, packaged asset bundle, and platform runtime. Every value is a count,
  a boolean, or a caller-supplied identifier; nothing is a host path, a document
  body, or a credential, so a report is safe to paste into an issue. A missing
  workspace is a report, not a crash. `researchos workspace migrate` reports the
  supported version range; **downgrade is refused, not emulated**.

- R15 `researchos workspace demo` builds a working workspace in one command
  from a minimal research corpus packaged **inside the wheel**, then diagnoses
  it and prints the next backup and serve commands. The corpus is copied to a
  temporary directory first, so running the demonstration cannot mutate the
  installed artifact. This closes the "minimal examples and an offline
  demonstration" deliverable: the clean-install journey no longer borrows a
  corpus from a source checkout.

- R15 an interrupted restore no longer leaves a half-workspace. The restore is
  assembled in a sibling `.partial` directory and renamed into place, matching
  the backup path, so a failure is retryable instead of being refused as
  `workspace-exists`.

- R15 `verify` re-derives the image's object set from the events and requires it
  to equal the manifest's, compares the snapshot size, the last event digest, the
  schema version and digest, and the object size total, and requires every
  `storageKey` to equal the key derived from its digest. An earlier version
  re-hashed only the objects the manifest listed and trusted eight fields
  verbatim, so deleting one `objects[]` entry produced a `verified: true` image
  that restored a project referencing an object it did not hold.
- R15 the SQLite snapshot path is percent-encoded before it becomes a URI. `#`
  terminates a URI fragment and `?` a query, and both are legal POSIX filename
  characters, so a workspace under `ws#frag/` was previously backed up from a
  different database into an internally self-consistent image.
- R15 `backup restore` uses the exact manifest object its verification checked
  rather than re-reading the file, and refuses a `--project` rename that no event
  in the image carries instead of folding an empty ledger on both sides and
  reporting a match. A rename that leaves the manifest disagreeing with every
  stored event is now a closed `restore-ledger-mismatch`.
- R14 minimal extension mechanism and permission boundary: a versioned manifest
  contract with a closed permission set, a compatibility refusal, a bounded
  subprocess host for one reviewed same-user adapter, and explicit
  enable/disable/uninstall. Loading a manifest is inert — read with `O_NOFOLLOW`
  under a size bound, parsed as JSON, validated, with nothing imported, evaluated
  or fetched.
- R14 partial Python extension boundary: inert immutable manifests, registered
  JSON schemas, explicit reviewed dispatch, bounded subprocess streams/deadlines
  and owned-group cleanup. This is not a malicious-code sandbox or full R14/D
  acceptance; typed external integrations and an extensions CLI remain open.

- R13 partial evaluation mechanics and human conclusions: a deterministic
  evaluator over a fixed, synthetic 12-example CPU fixture, labelled
  `computed-fixture`; no real-model or Checkpoint C acceptance is claimed. Every evaluation records the
  dataset digest, evaluator version, split, seed and example count, stores the
  full per-example detail as one CAS artifact, and appends no per-sample event.
  Metrics are fixed-precision decimal strings and the aggregate is re-derivable
  from the stored detail, so a reported number is reproducible or it is not a
  result.

- R13 comparison refuses incompatible setups instead of averaging across them,
  naming the differing dataset, evaluator, version, split, seed or example count,
  and a comparison declares `supportsAConclusion` only with at least two
  required metrics — one improved score is an observation, not a finding.

- R13 `ResearchConclusion`: a versioned contract with exactly three human
  verdicts (`supported`, `unsupported`, `insufficient-evidence`), no partial
  member, a mandatory rationale and human actor, and `systemDerived: false` so a
  conclusion is never mistaken for a fact the control plane derived. A negative
  or inconclusive result is a legitimate recorded outcome.

- R12 research workflow in the browser: a read-only, bounded research ledger
  plus proposal validation and decision recording through the CLI's own shared
  services. A proposal may cite only evidence this project has actually
  recorded; an unresolved citation refuses the proposal on both the read-only
  validate path and the mutating submit path. A validated proposal is a draft
  that queues no Run and grants no permission, and `expectedRevision` binds it to
  the revision the caller read so a stale proposal cannot overwrite a newer one.

- R12 preserved disagreement: a decision records which dissent it overrides and
  the dissent remains in the ledger, rendered beside the decision with the
  rationale intact across refreshes. The ledger separately refuses to re-decide a
  closed proposal, so a rejection cannot be manufactured after the fact.

- R11 browser operations: `POST /api/v0alpha1/commands` dispatches caller-owned
  application commands through the same shared services the CLI uses, so browser,
  CLI and event replay cannot disagree. Three operations are exposed:
  `plan.preflight` (read-only plan identity, target, policy, declared resources and
  enforced limits, always `launchAllowed: false`), `run.cancel` (exactly one
  cancellation-request fact through RunControl CAS) and `authorization.revoke`.

- R11 idempotency by durable identity rather than debounce. The browser mints one
  command identity per operator intent and reuses it on retry, so the shared
  receipt log decides: the same identity and content replays the prior receipt,
  the same identity with different content is refused, a second window replays,
  and a 5xx or transport loss is reported as *uncertain* with the identity
  retained rather than as success or failure.

- R11 `authorization.revoke` records a control-plane `grant.revoked` fact through
  `WorkerControl` rather than `WorkerPlane`. `WorkerPlane` requires an HMAC key,
  and a browser must never hold a Worker credential, so revoking authority as a
  Worker action would have put one in the browser's path.


- R10 read-only research workbench: a React 19 + TypeScript + Vite surface over
  the verified EventStore folds and the CAS, with the built bundle committed and
  shipped in the wheel so no checkout or Node is needed. Eight views cover the
  project, immutable spec revisions, a read-only execution graph, the run index
  with expandable facts, paged events, project-scoped artifacts, the enforced
  server limits, and a state/provenance legend.

- R10 `llm_research_os.web.contracts`: the wire contract as frozen, alias-keyed
  Pydantic models, with `scripts/generate_web_types.py` rendering
  `web/src/generated/local-api.ts` from them. A drift test fails when the
  committed types stop matching the server, so a shape change breaks the type
  check instead of silently disagreeing with the client.

- R10 outcome honesty. A run's observation state is derived from the
  authoritative `RunControl` fold, not from event-type names: `cancelled` maps
  to an observed stop, a fold refusal reports `absent`, and only an observed
  successful outcome is styled as success. A run's provenance is read from the
  authorization event its `run.queued` fact cites, so an audit-only or
  not-executed authorization is labelled synthetic; anything the workbench cannot
  source stays `absent` and is never called a measurement.

- R10 `llm_research_os.web.assets`: descriptor-anchored static serving with
  `O_NOFOLLOW` on every path component, a closed content-type table, `nosniff`,
  hashed assets marked immutable, a non-cached index, and `304` on a matching
  `If-None-Match`. The bundle loads without a session so the operator can obtain
  one; every versioned API route stays behind the session check.

- R09 local workbench API: a read-only, loopback-bound surface over verified
  EventStore folds and the CAS, implemented as a standard-library WSGI
  application. Versioned JSON with a closed structured error set, one-time
  bootstrap secret delivered in a URL fragment, in-memory `HttpOnly;
  SameSite=Strict` sessions, exact-`Host` and matching-`Origin` enforcement, and
  double-submit CSRF. A browser session is never a Worker credential and no
  route accepts a grant, private TLS key or bearer token. Bounded body,
  concurrency, depth, node, page and extraction limits are enforced during
  parsing, not after; JSON/YAML reuse the existing alias-rejecting loader and
  PDF the bounded extractor. Project-scoped pages carry opaque cursors and a
  high-water mark; artifact access is proven from linked events because the
  content index is global. Resumable SSE with a polling fallback.

- R09 `EventStore.list_artifact_links_page`: a bounded, validated page of
  artifact links for one digest, so a browser read surface can prove project
  scope without scanning the whole link table.

- R08 optional Ray Jobs CPU project driver: fixed installed reviewed Worker
  entrypoint, private durable single-POST intent, original-request binding,
  backend-only status and native observation outside Ray. A separate real Ray
  project gate verifies output/replay, lost submit response and observed cancel.

- R08 native Worker CLI composition: explicit reviewed controller spec/registry,
  bounded private credentials, fresh `workers run-native` and observation-only
  `workers reconcile-native` using existing runtime, grants and outcome receipts.
  Real separate CLI CPU/replay tests extend the required native integration gate.

- R08 Worker-local reviewed native CPU executor over pinned TLS: private durable
  single-launch intent and identity, fixed pre-import barrier, bounded collection,
  verified output and restart-only outcome replay. Controller terminal records
  bind authenticated Worker exit reports to the original start and Work facts.
  A designated real POSIX execution gate covers CPU execution and cancellation;
  Ray project jobs, GPU/Kaggle and two-host acceptance remain open.

- R08 remote native start recording: pinned TLS, consumed-lease and real-plan binding, immutable controller journals and exact interrupted-response replay. Receipts stay non-launch credentials; remote execution and process observation remain open.

- R08 optional Ray Jobs 2.59.0 resource-probe bridge: fixed CPU/CUDA jobs,
  bounded local token-authenticated vendor API, durable single-submission intent
  and query-only reconnect. A separate real CPU integration gate and compute-host
  extra evaluate the open-source backend without adding Ray to the controller.
  GPU/Kaggle and project-task execution/recovery remain unaccepted.

- R08 controller-side remote native claim binding: actual spec/registry plan
  reconstruction, single-attempt Run queueing, exact-bound journal replay and
  conservative resumed leases after controller/claim interruption. Native HTTP
  polling without TLS or trusted controller context refuses. Remote process
  launch/recovery and new two-host/GPU evidence remain open.

- R08 remote material metadata and Worker-local durable preparation: pinned,
  grant-scoped bundle members and bound environment/configuration documents,
  bounded persistent staging, actual host identity checks and atomic private
  workspace publication. The existing preparation receipt remains non-launching;
  remote executor/recovery and new authorized two-host/GPU acceptance remain open.

### Fixed

- The local API server raised an unhandled `OSError` when its port was already
  bound, so an operator with a port conflict got a traceback instead of a cause.
  It now exits `2` with `{"code":"port-unavailable", ...}` naming the port, which
  is one of the R15 clean-install acceptance cases.

- A backup snapshot was not self-contained. `EventStore` enables WAL on every
  open, so reading the snapshot left committed events in an `-wal` sidecar that
  the manifest digest did not cover; the image would have verified and then lost
  those events on a restore that copied the single file. The snapshot is now
  collapsed to one standalone file before its digest is taken.

- The local workbench client never sent the double-submit CSRF token, so every
  browser write was refused. Found by running the real page; the unit tests set
  the header directly and could not see it.
- A page reload lost the CSRF value, so every write after a refresh would have
  been refused. The session is now re-read on every load.
- The local API server was single-threaded, so one held connection blocked every
  other request and the bounded concurrency gate could never refuse anything in
  the deployed server. It is now threaded, with a test that holds one request open
  while asserting a second is answered.

### Milestones

- M1 offline checkpoint and M2 local/two-host scope accepted under ADR-0062.
  #77/#78 integrated; NativeProcessRuntime remains M3 work in #53. No release
  or paid-cloud acceptance is implied.
- M3 SSH/non-OCI work has started as slice 1 (ADR-0063, Issue #53): a local
  restricted helper plus a pending-live SSH onboarding pack. SSH execution,
  paid cloud, and public MVP remain out of scope.
- R01 integrated by PR #84 establishes the post-`#81` [M3 task baseline](docs/plans/m3-development-plan.md)
  and [acceptance matrix](docs/evidence/m3/acceptance-matrix.md): real native
  execution before Web, stable R01–R16 definitions, and checkpoints A/B/C/D.
  Historical M1/M2 acceptance retains its original platform and evidence SHA.
  [Development governance](docs/development-governance.md) and ADR-0064 assign
  global normative guidance to the planning/review assistant and in-scope
  implementation/evidence to implementers. R01 does not implement R02–R16,
  close #53, or publish a release.
- R02 adds shared application services (`researchos app`,
  `llm_research_os.application`). Commands are identity-bound and return
  durable receipts linked to existing facts. This is candidate behavior, not
  maintainer acceptance, native launch, or Issue #53 closure.
- R03 adds the reviewed-native request/report contract
  (`native-reviewed-python/v0alpha1`, `execute.native`) and a validator that
  does not import an entrypoint or start a process. `launchAllowed` stays
  false. This is candidate behavior, not real execution, and does not close
  Issue #53.
- R04 adds reviewed-native preparation and doctor diagnostics. They
  materialize digest-bound code, config, inputs, and interpreter identity
  into a private workspace and refuse a mismatched tree. They do not import
  an entrypoint or start user code. `launchAllowed` stays false. This is
  candidate behavior and does not close Issue #53.
- R08 adds local manifest-scoped input and output transfer
  (`researchos native transfer`, `native-scoped-transfer/v0alpha1`). Copies
  are limited to named paths and digests, with atomic file publication,
  serialized durable journals and no-follow directory descriptors. Local
  fault classification retains `unknown` and `cancel-requested`. Remote
  transport and grant enforcement remain unimplemented; two-host and GPU
  evidence remain pending-live. This slice does not close Issue #53.
- Optimize the common ASCII CloudEvents identity check while preserving the
  existing Unicode rejection rules; the 100k M2 append benchmark keeps its
  original threshold.

### Added

- M3 slice 1 local restricted `NativeProcessRuntime` (`ADR-0063`): sealed
  preflight recompute plus this-store human `{eventId, sequence}` consume
  before spawn, fixed noop helper with bounded capture, empty environment
  allowlist, isolated temporary cwd, and process-group supervision. The
  manifest entrypoint is never imported and no lifecycle fact is appended.
  `transport=ssh` is validated past authorization then refused
  (`ssh-transport-not-implemented`) without opening a socket.
- M3 slice 1 SSH onboarding scaffold (`ADR-0063`): `researchos native
  ssh-onboard` validates a restricted target (pinned host key, non-root, no
  password/agent-forwarding/private-key) and writes a `pending-live` pack
  with an onboarding checklist, `ssh_config` fragment, and restricted
  `authorized_keys` prefix. The pack never dials SSH.
- Detached Ed25519 authorization attestations with explicit keygen/sign/verify
  commands, pinned public-key scope, validity and revocation checks. These prove
  audit facts and never replace a Worker grant (ADR-0061).
- R02 shared application command and receipt
  ([protocol](docs/protocols/application-command-v0alpha1.md),
  [guide](docs/guides/m3-application-services.md)). `researchos app init` binds
  a project EventStore, CAS root, and Worker root. `researchos app execute`
  and `ApplicationService.execute` share one result document.

### Fixed

- R02 decision append uses the caller's `expectedHead` as the EventStore CAS
  token, recovers a duplicate event id only when the stored fact has the same
  type and semantic content, and digests, validates, and executes spec,
  decision, simulation-request, and registry inputs from one frozen snapshot.
  `run.simulate` carries that same head into the first simulation write.
- Native cancel uses the authorized `terminationGraceSeconds` (SIGTERM,
  wait, then SIGKILL), matching the timeout path. Scoped IPv6 `HostName`
  values escape `%` as `%%` so OpenSSH can parse the onboarding fragment.
- Loopback Worker TLS material is minted for 14 days. A 1-day cert
  expired on the live control plane (notAfter 2026-09-10) and made
  `workers run` report `http-disconnect` before claim.
- GPU output prepare grants UID/GID `65534:65534` ownership or a
  controlled ACL on the dedicated output root, `tmp`, and `.researchos`.
  Mode `775` alone is not a write grant. The Worker then runs a short
  file-ops probe in the pinned image (`--user 65534:65534`, `--read-only`,
  same data/model/output mounts) before `work/poll`. The probe creates,
  writes, renames, and deletes only `.researchos-perm-probe` files and
  reads `checkpoint-*` without touching `args.json`. Failure is
  `gpu-output-unwritable` / `gpu-checkpoint-unreadable` and does not
  claim. Training stays non-root and does not use mode `0777`. The
  probe interpreter is `python3` so the CUDA image (no `python`) and
  the Linux OCI brick image both run it.
- GPU `--read-only` launch sets closed `HOME` / `HF_HOME` /
  `HF_DATASETS_CACHE` on the existing `/tmp` tmpfs so UID 65534 can mkdir
  a HuggingFace datasets cache (passwd `HOME` is `/nonexistent`). GPU
  `/tmp` tmpfs allows exec so Triton can load a JIT `.so`; the CUDA image
  installs `python3-dev` for `Python.h`.
- WSL CUDA reports no longer treat checkpoint file presence as a restore,
  and a single checkpoint no longer sets `parametersUpdated: true`.
  Restore records split `requestedLoads` from `observedLoads`; leftover
  checkpoints in the pre-docker snapshot are not this-run products.
  optimizer / scheduler / rng need a Trainer load-hook JSONL
  (`phase=loaded`, source digest, post-load summary); a “Loading
  optimizer” substring is not verified. `run_gpu_training` applies a
  grant `resume` overlay when `commandDigest` matches. Live serve reads
  `RESEARCHOS_LEASE_SECONDS` (20-step needs 1800). Invalid GPU launch
  config returns `SandboxDisposition.FAILED` so the Worker can fail the
  lease instead of leaving a claimed grant dangling.
- `_reap_process_group` does not `killpg` the caller's process group.
  A MPS unit test spawned `/bin/sleep` in pytest's group; Linux CI then
  SIGKILLed the runner and the job sat until the cap. Worker HTTPS GET
  no longer calls ``read(256MiB+1)``. Required pytest uses
  `-m "not oci_live and not slow"`. Worker HTTP sockets default to 10s.
- Static run reports render Evaluation and System as their own sections.
  Training no longer lists `evaluation.metric` facts.

### Added

- Closed WSL CUDA restore plan pair `maxSteps=12` / `saveSteps=2` and a
  container Trainer load hook (`gpu_restore_observe`) that records
  optimizer / scheduler / rng source digests after a successful load.
  GPU launch sets closed `PYTHONPATH=/work/output/.researchos`.
- ADR-0059 WSL2 CUDA laptop profile (`wsl2-cuda-laptop-8g`) and
  `run_gpu_training` as the authorized container start. Plan/bind and
  `execute_gpu_training` stay `gpu-not-run`. Live two-host/CUDA evidence
  is not claimed until recorded on Windows/WSL2 + Docker Engine.
- M0 kernel architecture diagram source and HTML under
  `docs/architecture/` (visual-check review still pending).
- Charter §14.4 closure matrix for the WSL live pack (not M2 complete).

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
- Independent macOS/MPS training profile: `macos-mps-process` /
  `execute.mps`, closed `MacMpsTrainingPlan`, process-group isolation,
  `researchos m2 mps` Worker loop, 256 MiB checkpoint collect
  ([ADR-0058](docs/adr/0058-macos-mps-training-profile.md)). Live Apple M4
  evidence: [`examples/m2-mps-checkpoint/live-evidence.json`](examples/m2-mps-checkpoint/live-evidence.json)
  (train / cancel-observed / full resume 10→20 with optimizer and scheduler
  byte change / CAS verify). Environment artifact includes
  `sitecustomizeDigest`. Worker RSS is not MPS allocation. Not CUDA, not
  NativeProcessRuntime, not Issue #38 close.

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
