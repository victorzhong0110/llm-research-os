# Contributing

> 中文摘要与完整中文版见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)。工程细则见
> [engineering standards](docs/engineering-standards.md)（English）。

This repository is a pre-release research control plane. The M0 kernel proof is
closed ([ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)). The current phase
is the M1 research-assistant loop; slice order, security gates, and the checkpoint
are in [ADR-0038](docs/adr/0038-charter-errata-after-m0.md) and charter §23. Read
the open issues before starting; every M1 slice has one.

## Development environment

Python 3.12+ and [uv](https://docs.astral.sh/uv/). Training backends are not
installed into the control-plane environment.

```bash
uv sync --locked --all-groups
```

Run the same checks CI runs before opening a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
node conformance/digest/verify.mjs
uv build
```

CI requires Python 3.12 and 3.13 on Ubuntu and macOS. 3.14 is an allowed-to-fail
forward-compat job. Coverage below 85% of `llm_research_os` fails the build.

## How to slice

- One pull request, one slice. The slice names what it does and what it does not
  do; the non-goal list goes in the pull request body and the matching guide.
- Write an ADR only when the change introduces a constraint or a trade-off
  (charter §23 E10). A new command, report, or CLI surface is a protocol document
  (`docs/protocols/`) plus a guide (`docs/guides/`).
- Published JSON Schema is the external contract. Do not edit `schemas/` by hand.
  After changing a Pydantic model, regenerate with `researchos schema --output ...`
  and review the schema diff as a protocol change. Register new contracts in
  `src/llm_research_os/cli/contracts.py`.
- Every protocol object ships with valid and invalid examples under `examples/`.
  Invalid examples must say why they are invalid.
- Any new executable capability (process, plugin, network, model call, paid
  action) updates the [living threat model](docs/security/threat-model.md) and
  passes its gate before merge. Rows marked `planned` are not current security
  properties.
- `ready`, `authorized`, a successful preflight, and a simulated `completed` are
  not launch credentials or scientific conclusions. Do not write them as such.

## Language, comments, authorship

- English is the working language (code, comments, CLI copy, ADRs, protocols,
  guides, threat model, templates). README and CONTRIBUTING keep a Chinese
  translation. Charter v0.1 stays Chinese until v0.2. See
  [ADR-0040](docs/adr/0040-english-primary-and-engineering-standards.md).
- There is no comment-ratio target. Comments record fail-closed invariants and
  non-local couplings; they do not restate the next line.
- Commit messages use Conventional Commits prefixes (`feat:`, `fix:`, `docs:`,
  `refactor:`, `ci:`, `chore:`).
- The author is your own identity and usual email. Editor-injected
  `Co-authored-by` machine identities are not accepted. Maintainers can run
  `git config core.hooksPath scripts/git-hooks` once per clone to strip them.
- Pull requests from forks: every commit carries a
  [Developer Certificate of Origin 1.1](https://developercertificate.org/)
  sign-off (`git commit -s` → `Signed-off-by: Name <email>`). CI enforces this
  only on fork pull requests. There is no CLA.
- Keep `uv.lock` in sync with `pyproject.toml`. Explain lockfile diffs in the
  pull request.

## License

Code and original documentation are released under [Apache-2.0](LICENSE).
Submitting a contribution is agreement to submit under section 5 of that license.
Datasets, papers, model weights, and third-party notes do not inherit that
license; origin and rights are recorded separately (charter §10, ADR-0019).

## Security

Do not file vulnerabilities as public issues. Follow [SECURITY.md](SECURITY.md).
