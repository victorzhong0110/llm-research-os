# Real CPU evaluation and editable reports

Use a native profile reviewed by your operator to run the packaged
`llm_research_os/evaluation/iris.py` source as `brick.task:main`. Its one-file
bundle embeds attributed public data, makes no network request and needs only
the standard library. Pin the actual source, interpreter, inventory and code
review in the existing native material/Worker authorization workflow. The output
contains training data, fitted parameters and all held-out predictions; use a
reviewed stdout ceiling of 65536 bytes and artifact ceiling of 1048576 bytes.
This is the existing reviewed same-user adapter, not hostile-code isolation.

## Runnable Checkpoint C engineering demonstration

From a source checkout with locked developer dependencies:

```bash
uv sync --locked --all-groups
PYTHONPATH=src:tests uv run python examples/trained-evaluation/stage-demo.py \
  /tmp/researchos-trained-demo --authorize-reviewed-cpu-demo
uv run researchos web serve --root /tmp/researchos-trained-demo/controller
```

The source-checkout stager deliberately reuses **test material/actors and a
synthetic one-use grant**; it is an engineering demonstration, not a production
grant provisioner or an installed-wheel command. It refuses an existing target,
stages zero calls and starts zero Runs. The output identifies the exact workspace.
No paid model, user credential or private dataset is used. The UI server prints a
local bootstrap URL. The installed control plane remains free of training extras.

1. Open **Research**. Inspect model profile `mock`, generate its visibly synthetic
   proposal, review the actual base-1/candidate-2 difference, record it, and record
   an explicit accepted decision with a reason. Keep the returned decision ID.
2. In **Real evaluation and human report**, set training revision **2** and native
   profile `cpu`. Inspect material, then explicitly start authorized training.
   These are separate human actions; the research decision does not launch it.
3. Keep the completed output artifact. Supply the accepted decision ID and choose
   **Recompute completed baseline and candidate**. The server checks the actual
   Run and exact accepted spec, then records two typed detail artifacts.
4. Preview the evidence-linked report. Inspect failure cases and limitations,
   edit the narrative, explicitly choose a verdict and write the rationale, then
   record the report. A numeric improvement does not pre-select a conclusion.
5. After refresh/restart, list recorded reports and read the saved report artifact.
   Exact retry preserves the original command and judgement. For a lost training
   response, retry that exact intent or observe the Run; do not dispatch a new Run.

The standard fixed task produces baseline accuracy 10/20 and candidate accuracy
19/20. These are development observations, not independent scientific evidence.
Both models are fitted in one real reviewed Run and evaluated over the same fixed
held-out rows; they are not represented as independent experiments or trials.

For CLI use, put a normal typed command in a local JSON file and execute:

```bash
uv run researchos app execute command.json --root /path/to/workspace
```

Use `evaluation.collect` with the installed profile and actual output CAS ID;
`evaluation.report` with its baseline/candidate IDs; `conclusion.publish` with
the exact preview digest and explicit human fields. Read the versioned
[protocol](../protocols/trained-evaluation-v0alpha2.md) and
[examples](../../examples/trained-evaluation/README.md). CAS artifact IDs are
not arbitrary host paths. Unsupported training code/data, uncompleted Runs,
forged/missing metrics and unresolved citations are refused.

The committed-bundle CI drives the full proposal → accepted decision → exact-spec
CPU training → comparison → edited conclusion chain, loses a report response,
retries the exact command and reads the preserved report after server restart.
All automated actors/decisions are synthetic; real human Checkpoint C acceptance,
private-provider use and selected-host/GPU evidence remain separate.
