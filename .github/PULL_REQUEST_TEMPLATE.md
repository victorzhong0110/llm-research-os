## Slice

<!-- One pull request, one slice. Cite the matching issue or the M1-n from ADR-0038 E4. -->

## Changes

-

## Non-goals

<!--
What this slice explicitly does not do.
Does it add an executable capability (process, plugin, network, model call, paid action)? If so, which threat-model row was updated?
Does it change a published schema? If so, what is the protocol diff?
-->

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest --cov=llm_research_os --cov-fail-under=85`
- [ ] `uv run researchos schema --check-all`
- [ ] `node conformance/digest/verify.mjs` (when digest code changed)
- [ ] Protocol docs / guides / threat model / ADR index updated as needed
- [ ] English README / CONTRIBUTING stay in sync with `.zh-CN` translations when either changed
- [ ] Fork pull requests: every commit is `git commit -s` (DCO 1.1)
