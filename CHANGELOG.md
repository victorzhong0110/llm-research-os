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
- M1-0: SQLite schema v2 verified high-water cache and rebuildable query tables
  ([ADR-0041](docs/adr/0041-verified-high-water-cache-and-query-tables.md);
  Issues #39 / #40). Typed [`SecretRef`](docs/protocols/secret-ref-v0alpha1.md)
  and redaction. Optional ResearchEvent actor `kind` / `modelId`. SimulatedRuntime
  emits `attempt.cancelled` / `run.cancelled` from a recorded cancel request.
- M1-1: `proposal.submitted`, `dissent.recorded`, `decision.recorded`, rebuildable
  [`ResearchLedger`](docs/protocols/research-decision-objects-v0alpha1.md), and CLI
  `proposals submit` / `dissents record` / `decisions record` / `research ledger`
  (Issue #41). Question channel remains Issue #42.

### Changed

- `src/` fail-closed checks use `raise`, not `assert` (they must survive
  `python -O`).
- M1-0: a missing `integrity_checkpoint` row is an invalid cache (full verify,
  recreate when writable). `RunControl` always folds the frozen prefix from
  sequence 0; the snapshot cache is not fold authority. A cache-write failure
  after a committed lifecycle fact does not fail the append.
- M1-1: `ResearchControl` validates the complete prospective ledger before the
  CAS append. The 33rd override of one dissent is rejected before commit.
  Dissent/decision `targetKind` values `conclusion` and `question` are reserved
  until those aggregates exist (Issue #42 for questions).
