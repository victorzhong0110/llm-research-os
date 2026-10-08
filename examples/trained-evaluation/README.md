# Trained evaluation contracts and source-checkout demonstration

Valid detail/comparison/report documents illustrate the published v0alpha2
contracts. They use synthetic research actors with a real reviewed public CPU
training task. Their CAS IDs are example identities, not launch credentials or
artifacts guaranteed to exist in a reader's workspace. Invalid examples each
name their reason; they are not repaired or silently coerced.

`stage-demo.py` requires `--authorize-reviewed-cpu-demo`, a new target and the
source checkout's `src:tests` path. It stages test-only authorization/material
without dispatching. See the [guide](../../docs/guides/trained-evaluation.md).

Data attribution: Fisher, R. (1936). Iris [Dataset]. UCI Machine Learning
Repository. <https://doi.org/10.24432/C56C76>. CC BY 4.0
(<https://creativecommons.org/licenses/by/4.0/>). Raw `iris.data` bytes are embedded
unchanged in the reviewed task; only the versicolor/virginica rows are selected.
Source: <https://archive.ics.uci.edu/ml/machine-learning-databases/iris/iris.data>.
Source SHA-256: `6f608b71a7317216319b4d27b4d9bc84e6abd734eda7872b71a458569e2656c0`.
The public development partition and fitted models are engineering evidence;
no generalization, novelty, statistical significance or phase acceptance follows.

Invalid cases: `detail.invalid-missing-metric.json` omits required macro F1;
`report.invalid-automatic-verdict.json` claims system-derived judgement;
`report.invalid-extra-authority.json` adds execution permission not in the contract.
