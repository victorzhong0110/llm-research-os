# ADR-0040: English as the working language; comments record invariants

- Status: Accepted
- Date: 2026-09-03

## Context

After M0 closed, an audit of development hygiene found three process gaps that
were being treated as missing features:

1. Charter §16.2 still said “中英文文档可逐步建设”. The repository had no
   chosen primary language. Protocols, ADRs, and CLI copy were already English;
   README and CONTRIBUTING were Chinese; issue templates mixed both. A full
   bilingual tree would double the review surface for every protocol change.
2. Comment density in `src/` is low. Raising a comment-to-code ratio would add
   restated code without adding invariants, and would fight the protocol/guide
   layer that already carries “why this object exists”.
3. Several fail-closed checks used `assert`, which `python -O` strips; the
   package had no `py.typed`; CI had no coverage floor; Dependabot had no
   checked-in config; agent `Co-authored-by` trailers could still land locally.

ADR-0038 E10 says a new ADR is for a constraint, not for a command. Language and
comment policy are constraints. The operational checklist lives in
[engineering-standards.md](../engineering-standards.md).

## Decision

### D1 — English is canonical

Code, comments, identifiers, CLI copy, commit messages, ADRs, protocols, guides,
the threat model, and GitHub templates are written in English.

`README.md` and `CONTRIBUTING.md` are the canonical shop-window files.
`README.zh-CN.md` and `CONTRIBUTING.zh-CN.md` are translations, updated in the
same pull request.

Charter v0.1 and chapter 18 remain the Chinese originals accepted on 2026-08-21.
They are not rewritten for language. Errata continue to land in §23. Charter v0.2,
after M1, may be authored in English.

ADRs, protocols, guides, and the threat model are **not** dual-language. A second
copy is a drift surface; it is cheaper to keep one language than two stale ones.
Issue and pull-request discussion may be Chinese or English.

This supersedes the “中英文文档可逐步建设” bullet in charter §16.2 (erratum E16).

### D2 — Comments record what the code cannot

There is no comment-ratio target. A comment is required only when it records a
fail-closed invariant, a threat-model identifier, a non-local coupling, or a
reason a check must survive `python -O`. Module docstrings stay. Protocol “why”
stays in `docs/protocols/` and `docs/guides/`.

### D3 — Hard checks, typed package, coverage floor, hook

- Invariants in `src/` use `raise`, not `assert`.
- `src/llm_research_os/py.typed` is present.
- CI fails the tree below 85% coverage of `llm_research_os`. That is a floor, not
  a 90% target.
- Hypothesis properties cover JCS stability, foreign-run folds, and spec/event
  round-trips.
- `scripts/git-hooks/commit-msg` strips Cursor/bot `Co-authored-by` trailers.
  `scripts/install-git-hooks.sh` is the one-shot local setup. CI job `Human
  authorship` rejects the same trailers on every pull request.
- `.github/dependabot.yml` updates GitHub Actions pins and the uv lock weekly.
- `.github/CODEOWNERS` names `victorzhong0110`. Code-owner review is not a
  required check (solo maintainer).

## Consequences

- Future protocol edits are reviewed once, in English.
- Chinese-speaking contributors still have README, CONTRIBUTING, and the charter.
- Comment-only pull requests that inflate ratio without adding an invariant are
  out of scope.
- Hypothesis is used on JCS, the Run/Attempt fold, and spec/event round-trips.
  Further properties land with the slice that owns the module.
- Version remains `0.0.0` until M1 close (`v0.1.0-m1`).

## Validation

1. `README.md` and `CONTRIBUTING.md` exist in English and point at the `.zh-CN`
   translations.
2. `docs/engineering-standards.md` exists and is linked from both CONTRIBUTING
   files and the ADR index.
3. Charter §23 has row E16; §16.2 has a one-line pointer.
4. `src/llm_research_os/py.typed` is in the tree; `uv build` still produces a
   wheel that contains it.
5. `.github/workflows/ci.yml` passes `--cov-fail-under=85` and has a Human
   authorship job on pull requests.
6. ruff (including `S` on `src/` and `PT011`/`PT012`), mypy, pytest, schema
   `--check-all`, and `uv build` still pass.

## References

- [Engineering standards](../engineering-standards.md)
- [Charter v0.1 §16.2](../charter-v0.1.md)
- [ADR-0011 Apache-2.0](0011-apache-2-license.md)
- [ADR-0012 Python and dependencies](0012-python-and-dependencies.md)
- [ADR-0038 E10 / E11](0038-charter-errata-after-m0.md)
