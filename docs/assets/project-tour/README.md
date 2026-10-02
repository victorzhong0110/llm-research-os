# Three-minute project tour: provenance

These are frozen evidence numbers, not live badges or claims that M3 is accepted.

| README number | Evidence and scope |
| --- | --- |
| 1,661 tests passed | PR #118 Linux Python 3.12, [CI run 36983679149](https://github.com/victorzhong0110/llm-research-os/actions/runs/36983679149), candidate `1aaa6e8c182fd4a5d9a48a0b45fb8f5819f3dc8e`; 12 OCI-only deselected, zero failures/skips |
| 85.38% coverage | Same run, statement-plus-branch coverage; unrounded 85.381944%, unchanged 85% gate |
| 2 real hosts | Historical accepted M2 evidence: [closure matrix](../../evidence/m2-wsl2-cuda-live/m2-closure-matrix.md), CPU/CUDA, reconnect/cancel and checkpoint restore. This is not R08 native live acceptance |

## Architecture

[Interactive HTML](architecture.html), [source specification](architecture.json),
[static PNG](architecture.png), [SVG](architecture.svg), and
[artifact-bound evidence](architecture-evidence.json).

Generated with [Archify v3.0.1](https://github.com/tt-a1i/archify/tree/v3.0.1),
commit `2ab3cae7ac2c2a55d7386ca789d03c4fcd31816c`, from repository source pinned to
`65304b0659168d9661dde010ae751c35dedc81b5`. Each component carries source ranges.
Validation, delivery, strict checks and real-browser checks passed. The interactive
HTML has no perceptual-review claim. The separate PNG was visually inspected;
its SVG export inlines the checked HTML's CSS and enlarges text for README use.
The upstream [MIT license](ARCHIFY-LICENSE.txt) is preserved separately.

To regenerate, use the pinned Archify checkout, a Chrome executable, and a clean
source checkout at the pinned repository revision:

```bash
ARCHIFY_CHROME=/absolute/path/to/chrome node /path/to/archify/archify/bin/archify.mjs \
  finalize architecture docs/assets/project-tour/architecture.json \
  .archify/architecture-project-tour-20261002/architecture.html \
  --repo-root . --quality showcase --out-dir .archify/tour-reproduction --json
```

## CLI recording

[MP4](research-loop.mp4), [GIF](research-loop.gif), [terminal transcript](research-loop.cast),
[captured stdout, timings and source identity](recording.json).

Five real CLI commands ran successfully in a fresh locked environment. The 80-second
recording displays terminal snapshots with reading pauses. Long output is shortened
on screen; the complete stdout is retained in the transcript and JSON. This is an
offline deterministic Mock model and simulated Run, with no GPU. Rejection records
`queued: false`; acceptance records `queued: true`; verification checks 14 events.
Temporary databases are isolated and deleted after capture.

Reproduction (Pillow and ffmpeg are optional authoring tools, not project dependencies):

```bash
uv sync --locked --all-groups
python scripts/record_project_tour.py --font /absolute/path/to/monospace.ttf
```

Checkpoint B remains open: remote staging/executor/recovery integration and authorized
R07/R08 two-host/GPU evidence remain incomplete. After explicit B acceptance, freeze;
do not start R09 without a later maintainer decision.
