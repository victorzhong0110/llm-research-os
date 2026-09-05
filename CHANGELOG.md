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
  require `SecretRef`, `read.external_api`, HTTPS, and a positive CNY cap and
  reserve. First runtime-enforced CNY caps: `budget.reserved` / `consumed` /
  `exceeded` / `released`.
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
  reserve. Transport failure after start writes `budget.released` and
  `ai.call.failed`. Consume/release must match the reservation (`callId`,
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
