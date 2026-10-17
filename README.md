# LLM Research OS

A personal workspace for LLM research, organized around one interactive map.
Bring research questions, experiments, your Agent, compute, service health and
evidence into the same view. Open a component to inspect the details behind it.

[中文](README.zh-CN.md) · [Dashboard guide](docs/guides/research-dashboard.md) ·
[Current work](https://github.com/victorzhong0110/llm-research-os/issues/159)

## The workspace

The Dashboard is a map with meaningful groups and relationships. Browse to read,
Edit to arrange components, or use AI mode to ask your own Agent to help maintain
it. Hover for a summary; select a component for its source data, charts and
attributed interpretation. Search, zoom, collapse and the minimap help with
larger workspaces.

| On the map | What you can inspect |
| --- | --- |
| Research and experiments | Questions, planning notes, recorded Runs, results and evidence |
| Compute and execution | Connected source observations, Worker information and recorded task activity |
| Serving and reliability | Provider reports, imported service observations and their freshness |
| Decisions and stewardship | Human decisions, disagreement, costs/budget sources and recovery information |

Arrange related work with containment, peers, pins and optional arrows. Moving a
card changes your view; execution dependencies and permissions use their own
reviewed operations. Choose Graphite, Warm paper or a custom theme.

The map provides reusable presets and configurable components. Data appears only
when its source exists: missing load, utilization, cost or Agent activity stays
missing. Official provider status and your own request health are separate.

## Try it from this repository

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). The built browser bundle
is committed; these steps do not require Node, a model key or a GPU.

```bash
git clone https://github.com/victorzhong0110/llm-research-os.git
cd llm-research-os
uv sync --locked --all-groups
uv run researchos app init \
  --root ./research-workspace \
  --project my-research \
  --control-db control/events.sqlite \
  --cas-root cas \
  --worker-root worker
uv run researchos web serve --root ./research-workspace --port 8787
```

Open the bootstrap URL printed by the server. It opens the local Dashboard and
establishes a browser session. Keep that URL private.

1. Choose **Create my first brief** and describe a research question and what
   would count as progress. Materials and resources can remain undecided.
2. Review and save. Your goal and preparation notes become an editable region
   on the map. Save the map before reloading.
3. Browse the notes, try Edit, and switch themes. Add an **OpenAI official
   status** or **Claude official status** component and explicitly refresh it
   when public internet access is available.

A brief records planning notes. Guided setup from those notes to an executable
experiment is still being developed. Advanced research and execution operations
already exist, but some require operator-prepared profiles and identifiers.

For a separate offline demonstration with existing recorded research data:

```bash
uv run researchos workspace demo --root ./research-demo
uv run researchos web serve --root ./research-demo --port 8788
```

The demo uses a deterministic Mock model and a simulated Run. It is labeled
example data, not a real training result. An installed wheel also includes the
browser bundle and offline corpus; see [installation and recovery](docs/guides/r15-installation-and-recovery.md)
for installation from a locally built or supplied wheel. The project is pre-release.

## Work with your own Agent

AI mode creates a durable, scoped request in the workspace inbox. Your Agent
reads it with `researchos dashboard inbox`, replies with
`researchos dashboard reply`, and may propose a revision-bound map change.
Human pins, selected scope and conflicting edits are checked. The application
does not automatically start an LLM or an Agent when you open AI mode.

See the [Agent workflow](docs/guides/research-dashboard.md#connect-your-own-agent)
and [component contracts](docs/protocols/dashboard-document-v0alpha1.md).

## Implementation and evidence

<!-- generated-status:start -->

| Scope | Status |
| --- | --- |
| Dashboard | Map, Browse/Edit/AI, persistent arrangement and themes integrated (#156) |
| First use | Guided brief available (#157); material/resource/executable-plan setup remains in progress |
| Agent | Durable scoped inbox and map proposals; your own Agent supplies replies |
| Provider status | Manual OpenAI/Claude public reports (#158); source/expiry shown; direct development-host connectivity unverified |
| Execution and evaluation | Reviewed native CPU and remote Worker paths, real CPU evaluation and durable reports implemented; package/live acceptance gaps remain |
| Human / real-host acceptance | dashboard-v1 tasks specified; no independent current-map trial; old checkpoint campaign paused |
| Historical M1/M2 | Offline research and scoped local/two-host CPU, CUDA and MPS evidence accepted under ADR-0062 at recorded identities |
| Release | Pre-release 0.0.0; no public release or paid-cloud certification |

[Current M3 evidence and gaps](docs/evidence/m3/acceptance-matrix.md) · [Historical M1/M2 scope](docs/adr/0062-m1-m2-acceptance-and-m3-boundary.md).
Implementation snapshot: `6b49255`; historical accepted evidence: `57ffdae`.

<!-- generated-status:end -->

Current priorities are guided execution preparation, more source-backed
components and independent first-use evaluation. See [#159](https://github.com/victorzhong0110/llm-research-os/issues/159)
and the [Dashboard delivery plan](docs/plans/research-dashboard.md).

Known limits include manual provider refresh, no bundled host utilization
exporter, and separate export of saved map state because older workspace backup
formats omit `dashboard.sqlite`. A resource note is not a connected machine or
allocated budget. Browser tests and screenshots do not establish human usability.

## Research and execution foundations

The map sits on a shared research control plane: versioned specifications,
append-only events, content-addressed artifacts, human decisions and preserved AI
disagreement. CLI, Python and browser callers share domain services and receipts.
Reviewed execution binds the plan, materials, environment and Worker authority.

A cancellation request is distinct from an observed stop. An unconfirmed outcome
stays unknown and cannot automatically launch a replacement task. Reviewed native
code runs with its documented host limits; required isolation that a profile
cannot enforce is refused. See the [security policy](SECURITY.md),
[threat model](docs/security/threat-model.md) and
[native execution guide](docs/guides/m3-native-reviewed-execution.md).

## Documentation

- [Dashboard use and composition](docs/guides/research-dashboard.md)
- [Installation, diagnostics, backup and restore](docs/guides/r15-installation-and-recovery.md)
- [Dashboard acceptance tasks and real-host checks](docs/guides/dashboard-acceptance.md)
- [M3 plan](docs/plans/m3-development-plan.md) and [evidence matrix](docs/evidence/m3/acceptance-matrix.md)
- [All guides](docs/guides), [protocols](docs/protocols) and [architecture decisions](docs/adr/README.md)
- [Contributing](CONTRIBUTING.md), [engineering standards](docs/engineering-standards.md) and [changelog](CHANGELOG.md)

## Development

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not oci_live and not slow and not ray_native_live" \
  --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
python scripts/project_status.py --check
node conformance/digest/verify.mjs
uv build
```

Frontend source lives in `web/`; rebuilding it requires the pinned Node/npm
workflow described in [the workbench guide](docs/guides/m3-workbench.md).
Published JSON Schema is the external contract; regenerate it from its registered
model instead of editing generated files by hand.

## License

Copyright 2026 victorzhong0110. [Apache-2.0](LICENSE); see [NOTICE](NOTICE).
The project name is a working title. Releases, tags and publication are separate
decisions.
