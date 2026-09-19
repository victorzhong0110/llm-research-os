# Repository working instructions

Read [CONTRIBUTING.md](CONTRIBUTING.md), [engineering standards](docs/engineering-standards.md),
and [development governance](docs/development-governance.md) before changes.
For M3 use the single [R01–R16 plan](docs/plans/m3-development-plan.md) and
[acceptance matrix](docs/evidence/m3/acceptance-matrix.md). Older #80/#84 draft
mappings do not override the corrected plan or explicit maintainer instructions.

## Responsibilities

- Global plans, normative guidance, package boundaries, and acceptance criteria
  are authored/maintained by the designated planning/review assistant (currently
  ChatGPT/Codex), under the maintainer's direction.
- Assigned implementers make routine technical choices and deliver in-scope code,
  tests, package documentation, and factual candidate evidence autonomously.
- Propose material scope/authority/acceptance changes explicitly for review;
  never rewrite a rule merely to make an implementation pass. Continue unaffected
  authorized work while a material decision is pending.
- The maintainer controls merges and publication. Existing explicit authorization
  remains valid; this file does not create repeated approval requirements.

## Execution and reporting

- Work sequentially, with independently reviewable package/slice PRs based on
  verified main. Do not silently renumber R packages or create parallel R work.
- Report exact head, checks, evidence, gaps, and proposed normative changes.
- Preserve historical acceptance at its original platform/SHA. Separate candidate
  evidence, integration, verification, and acceptance; an open PR is not merged.
- Live machine/credential/paid work uses existing explicit authorization only.
  Missing live evidence remains pending-live; Mock or skipped tests cannot replace it.
- Preserve existing EventStore/CAS, Run/Attempt, Worker grants, and observation
  semantics. Audit signatures are not launch credentials; unknown is not rerun.
- Follow existing language, generated-schema, threat-model, and CI rules.
  Keep README/CONTRIBUTING translations synchronized when changing them.
