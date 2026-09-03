# Engineering standards

Canonical process for this repository. Changed by a pull request that updates this
file and, when the change is a constraint, a new ADR. [ADR-0040](adr/0040-english-primary-and-engineering-standards.md)
is the constraint record for language and comment policy.

The [project charter](charter-v0.1.md) stays the accepted research baseline. This
file is how code, docs, and CI are written day to day.

## Language

English is the working language of the repository:

| Surface | Language |
|---|---|
| Source, comments, identifiers, CLI copy, test names | English |
| Commit messages | English, Conventional Commits |
| ADRs, protocols, guides, threat model, issue and PR templates | English |
| `README.md`, `CONTRIBUTING.md` | English (canonical) |
| `README.zh-CN.md`, `CONTRIBUTING.zh-CN.md` | Chinese translations, updated in the same pull request as the English file |
| Charter v0.1 and chapter 18 | Chinese original (accepted 2026-08-21). Errata stay in §23. v0.2, after M1, may be authored in English |

Do not maintain a second full copy of ADRs, protocols, guides, or the threat model.
A translation is a maintenance surface; only the shop-window files above carry one.
Issues and pull-request discussion may be written in Chinese or English.

## Comments

There is no comment-ratio target. Padding a file with restated code is a defect.

Write a comment when it records something the next reader cannot recover from the
code or the type signature:

- a fail-closed invariant and why it is fail-closed;
- a threat-model identifier (`TM-0xx`) that the code is enforcing;
- a non-local coupling (this branch exists because another module assumes X);
- a reason an `assert` was replaced with a hard `raise` (it must survive `python -O`).

Do not write comments that restate the function name, repeat the types, or narrate
the next line. Public modules keep a one-line module docstring. Why a protocol
object exists belongs in `docs/protocols/` and `docs/guides/`, not in a block
comment above the Pydantic model.

## Tests

- CI coverage floor is 85% of `llm_research_os` (`--cov-fail-under=85`). The M0
  tree sits in the high 80s with branch coverage; do not treat 90% as a gate.
- Prefer a property or a table of fixtures over a story-shaped test. Hypothesis
  covers JCS stability, Run/Attempt folds that ignore foreign runs, and Pydantic
  round-trips of valid spec/event examples. Add properties when those modules
  change; do not add unused Hypothesis tests for coverage theatre.
- Do not wrap an expected exception in a bare `pytest.raises(ValueError)` when a
  narrower type or `match=` would pin the contract (`PT011`).
- `assert` in tests is fine. `assert` in `src/` is not: it disappears under
  `python -O`. Use `raise` for invariants that must hold in optimized runs.

## Authorship

Every commit is authored and committed as a human identity. Editor or agent
`Co-authored-by` trailers for Cursor, bots, or machine accounts are stripped.

Activate the hook once per clone (this is a local git setting, not a repository
config checked in):

```bash
./scripts/install-git-hooks.sh
```

The hook in `scripts/git-hooks/commit-msg` drops matching trailers. CI job
`Human authorship` rejects the same trailers on every pull request, so a missing
local hook cannot land a machine identity. Maintainers also set squash-merge on
GitHub to `PR_TITLE` / `PR_BODY` so historical commit bodies do not become the
squash message.

Fork pull requests additionally carry a DCO 1.1 `Signed-off-by` on every commit
(`git commit -s`). CI enforces that only for forks. There is no CLA.

## Slices, ADRs, protocols

One pull request is one slice, with an explicit non-goal list.

A new ADR is for a constraint or a trade-off (charter §23 E10). A new command,
report, or CLI surface is a protocol document plus a guide. Published JSON Schema
under `schemas/` is the external contract: regenerate from Pydantic, never edit by
hand, register new contracts in `src/llm_research_os/cli/contracts.py`.

Any new executable capability (process, plugin, network, model call, paid action)
updates the [living threat model](security/threat-model.md) in the same pull
request. Rows marked `planned` are not current security properties.

`ready`, `authorized`, a successful preflight, and a simulated `completed` are not
launch credentials or scientific conclusions.

## Packaging and typing

- `src/llm_research_os/py.typed` marks the package as typed for downstream mypy.
- Version stays `0.0.0` until M1 closes; the first tag is then `v0.1.0-m1`.
  [CHANGELOG.md](../CHANGELOG.md) records Unreleased work; do not invent a
  version bump in an engineering-standards pull request.
- Ruff `S` (bandit) runs on `src/`. Tests and `conformance/` ignore it because they
  contain intentional `assert`, secret-named fixtures, and `shell=True` tripwires.
- Ruff `PT011` / `PT012` pin pytest.raises contracts.

## Required checks

Pull requests must pass ruff, ruff format, mypy, pytest (with the coverage floor),
schema `--check-all`, digest conformance, and `uv build`. CI runs that matrix on
Python 3.12 and 3.13 on Ubuntu and macOS; 3.14 on Ubuntu is allowed to fail.

The GitHub ruleset on `main` requires a pull request and the Ubuntu 3.12 / 3.13
jobs. macOS is extra signal, not a required check, so a queued macOS runner cannot
block a merge.
