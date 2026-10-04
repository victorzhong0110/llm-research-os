# Real evaluation, comparison and conclusions (R13)

Status: **Implemented on branch `r13-evaluation`; candidate evidence only. Not merged,
not accepted.** Checkpoint C is not accepted.
Requirements: [M3 plan R13](../plans/m3-development-plan.md#r13-real-evaluation-comparison-and-conclusions).

## What "real" means here

The evaluation is actually computed from a committed, synthetic 12-example
CPU fixture. It is labelled `computed-fixture` and is not trained-model or live-run evidence. A
deterministic evaluator scores a fixed, committed held-out set of labelled
examples, and the per-example detail is stored alongside the aggregate. Nothing
is drawn at random and no number is asserted that was not computed.

This is a CPU evaluation path, as the plan allows ("one supported real
model/evaluation path for acceptance; no second large training framework"). It
is **not** a claim that a trained model was evaluated: the predictors here are a
majority baseline and a threshold rule, and a majority baseline that scores
perfectly would not be a baseline worth comparing to, which the tests assert.

## Provenance

Every evaluation records the dataset digest, evaluator name and version, split,
seed and example count. Two results may be compared only when that provenance
fingerprints identically; a differing seed, split, dataset, evaluator or version
produces numbers that look comparable and are not, so the comparison is refused
and the mismatch is named.

## A result is reproducible from its own detail

`recompute()` re-derives the aggregate from the stored per-example detail. If a
report cannot be reproduced from the artifact it ships with, it is not a result.
Metrics are fixed-precision decimal strings, never floats, so a comparison
cannot depend on binary rounding.

## Incompatible comparisons are refused, not averaged

`compare()` returns `incomparable` with a refusal that names the differing
field, no deltas, and a stated limitation. It never averages across setups or
reports a delta it cannot justify.

## One improved score is not a conclusion

A comparison declares `supportsAConclusion` only when it is comparable, has no
missing required metrics, and carries at least two required metrics. A
comparison with a single moved metric reports the observation and refuses to
support a conclusion.

## Conclusions are human judgements

`ResearchConclusion` is a versioned contract (`contractVersion: v0alpha1`) with
exactly three verdicts: `supported`, `unsupported`, `insufficient-evidence`.
There is deliberately no partial member. The system supplies **no** judgement:
the verdict and rationale are the caller's, the actor must be non-empty, and the
recorded result carries `systemDerived: false` so a conclusion can never be
mistaken for a fact the control plane derived.

`insufficient-evidence` is always recordable, including over a refused
comparison — saying the evidence is insufficient is itself a finding. A
`supported` or `unsupported` verdict over evidence that cannot carry one is
refused.

**A negative result is a valid outcome.** The tests record both a regression
conclusion and an inconclusive one.

## Metrics do not fill the event log

An evaluation writes one CAS detail artifact and appends **no** events. A metric
series belongs in bounded CAS chunks, and an event per sample would be exactly
the failure the existing `metrics/chunk.py` module exists to prevent.

## Two digest namespaces

The CAS keys objects by raw SHA-256; an evaluation result carries a JCS semantic
digest. They are different namespaces on purpose. What must round-trip is the
content, and the test asserts exactly that.

## What is not delivered

- **The editable evidence-linked report is not generated.** The conclusion
  contract and the comparison document exist and are served, but no renderer
  produces a human-editable report file. Recorded as a gap.
- **No repeat-variance estimate.** A single held-out set cannot support a
  significance claim, and every comparison says so in `limitations`.
- **Only two registered predictors** (majority and threshold). A real model
  would need an adapter registration this slice does not add.
- **Checkpoint C's end-to-end browser demonstration is not claimed.** The loop is
  exercised through the shared command path — evaluate, compare, conclude — in
  tests, but the R12 browser toolchain limit recorded in COMM-0009 still applies.

MAE is the mean absolute difference between the binary prediction and the label.
Comparison deltas use decimal arithmetic. Stored details must reproduce their
aggregate and have consistent IDs, binary labels and prediction errors. Human
conclusions bind the complete comparison digest, including both evidence artifacts.
