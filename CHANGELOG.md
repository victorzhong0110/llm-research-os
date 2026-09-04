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

### Changed

- `src/` fail-closed checks use `raise`, not `assert` (they must survive
  `python -O`).
