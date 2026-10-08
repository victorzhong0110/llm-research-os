# Trained evaluation and human reports v0alpha2

This R13 continuation preserves `evaluation-document/v0alpha1` and the synthetic
12-row `evaluation.run` contract. New typed detail, comparison and human reports
are published through `trained-evaluation-document/v0alpha1.schema.json` with
evaluation/conclusion **v0alpha2** document identifiers. No unrelated decision or
Run enum changes. EventStore remains schema v2.

## Supported model and data

The reviewed standard-library task `evaluation/iris.py` fits a nearest-class
centroid classifier and a training-majority baseline on 80 observations. The
four raw numerical features are not normalized; squared Euclidean distance and
ties favouring class 0 are fixed. Decimal precision is locally set to 28. Both
fits use training labels only. There are no optimization/search hyperparameters
or random draws; seed 0 and configuration v0alpha1 are explicit.

Data: Fisher, R. (1936), Iris, UCI, <https://doi.org/10.24432/C56C76>, CC BY 4.0.
The unchanged `iris.data` bytes have SHA-256
`6f608b71a7317216319b4d27b4d9bc84e6abd734eda7872b71a458569e2656c0`.
Source rows 51–150 are the versicolor/virginica binary subset (labels 0/1).
Zero-based original source indices divisible by five form the 20-row held-out
partition; the other 80 rows form training. Source IDs, features, labels and
split are retained. Training and held-out IDs are disjoint. No runtime download
or library/framework installation is required.

This is a **public development benchmark**, observed during development; it is
not an untouched validation set or independent confirmation. The fixed single
split supplies no repeat-variance, significance or generalization claim. Real
CPU training establishes executable integration, not LLM or scientific progress.

## Commands and evidence

All commands use `researchos app execute` / the shared browser command endpoint.

| Operation | Inputs and behavior |
| --- | --- |
| `evaluation.collect` | Installed `profileId`, completed `outputArtifact`, expected revision; optional accepted `decisionId`. Never dispatches. |
| `evaluation.report` | Baseline/candidate trained artifact IDs and expected candidate revision. Replays both models and emits editable narrative with **null verdict**. |
| `conclusion.publish` | Exact preview `comparisonDigest`, baseline/candidate IDs, `reportId`, edited narrative, explicit verdict/rationale and optional imported evidence IDs. Requires caller head/revision. |
| `conclusion.list` | Latest ten recorded report summaries, with an explicit withheld count. Workspace-local durable receipt discovery. |
| `conclusion.inspect` | Recorded report artifact; checks typed bytes, project, receipt and result digest. Reads historical human judgement without recomputing a new judgement or dispatching. |

Collection pins the full native request in CAS without token/key files. It
verifies the existing native output envelope's request/task/Run/Attempt identity,
pinned reviewed source bytes, actual typed Worker queue and unique completed
lease/result digest, completed Run and successful Attempt, and completion fact
revision. It re-fits both models and compares all parameters, predictions and
retained data to the output. Caller-asserted completion or numbers do not count.
No model/provider entrypoint is imported from an artifact.

When `decisionId` is supplied, its recorded accepted proposal must identify the
exact Run spec digest and adjacent candidate revision, and the decision must
precede `run.queued`. The optional link preserves research lineage; it does not
replace a separate Worker grant or authorization fact. Missing/rejected/foreign
or wrong-spec decisions refuse rather than fabricating a link.

Each typed trained detail contains project/revision/Run/Attempt/task, CAS native
request/output IDs, reviewed source/config/training-dataset/model digests,
completion event/sequence, optional proposal/decision, fixed evaluator/split/seed,
all 20 predictions, aggregate metrics and failure IDs. Comparison binds the
**whole** typed detail digests; dataset/evaluator/split/seed/config/training data
and revision mismatches refuse comparability. Unknown versions, missing metrics
and altered provenance fail validation. Synthetic and trained contracts cannot
be silently mixed.

Accuracy = correct/count. Macro F1 averages the two binary class F1 scores,
with zero for a class whose `2TP+FP+FN` is zero. MAE averages absolute binary label
errors. Values use six decimal strings and existing recomputation rules. Accuracy
and binary MAE are complementary, **not independent evidence**. A numeric
comparison can indicate direction/eligibility; it supplies no human conclusion.

Reports are immutable CAS documents referenced by append-only operation receipts,
not new EventStore lifecycle facts. The system fixes metrics/provenance/limitations;
only narrative, verdict, rationale and additional citations are human inputs.
Every citation resolves in the same project. Human attribution is a caller claim
under the local operator trust boundary, not proof that a real participant acted.
`supported`, `unsupported`, and `insufficient-evidence` are legitimate explicit
choices; incomparable/incomplete evidence permits insufficient-evidence only.
An improved score never chooses a verdict. Report IDs are descriptive labels;
command identity and content digest bind exact replay and immutable versions.

There is no automatic training, redispatch, human acceptance, publication to a
remote service, new training framework, leaderboard or model-judge service.
Unknown execution outcomes retain the R11 observation-only boundary.
