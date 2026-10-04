"""Baseline versus candidate comparison (R13).

Two results may only be compared when they were produced the same way. A
different dataset, evaluator version, split or seed produces numbers that look
comparable and are not, so this module refuses the comparison and names the
mismatch instead of reporting a delta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from llm_research_os.evaluation.evaluator import EvaluationError, EvaluationResult

REQUIRED_METRICS: Final = ("accuracy", "macro_f1", "mean_absolute_error")

# A single better number is not a conclusion. This is the minimum number of
# independently-required metrics before a comparison may be described as
# supporting anything at all.
MIN_METRICS_FOR_SUPPORT: Final = 2

ComparisonOutcome = Literal["improved", "regressed", "unchanged", "incomparable"]
Direction = Literal["better", "same", "worse", "incomparable"]


class ComparisonError(ValueError):
    """One comparison fault with a closed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    baseline: str
    candidate: str
    change: str
    direction: Direction

    def document(self) -> dict[str, str]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "change": self.change,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """A comparison, or the reason one was refused."""

    outcome: ComparisonOutcome
    baseline_detail_digest: str
    candidate_detail_digest: str
    deltas: tuple[MetricDelta, ...]
    missing_metrics: tuple[str, ...]
    refusal: str | None = None
    limitations: tuple[str, ...] = ()

    @property
    def comparable(self) -> bool:
        return self.outcome != "incomparable"

    @property
    def supports_a_conclusion(self) -> bool:
        """Whether this comparison may ever support a conclusion.

        A refusal never can. Neither can a comparison with too few metrics: one
        improved score is an observation, not a finding.
        """

        return (
            self.comparable
            and len(self.missing_metrics) == 0
            and len(self.deltas) >= (MIN_METRICS_FOR_SUPPORT)
        )

    def document(self) -> dict[str, object]:
        return {
            "apiVersion": "researchos.dev/evaluation/v0alpha1",
            "kind": "EvaluationComparison",
            "outcome": self.outcome,
            "baselineDetailDigest": self.baseline_detail_digest,
            "candidateDetailDigest": self.candidate_detail_digest,
            "requiredMetrics": list(REQUIRED_METRICS),
            "deltas": [item.document() for item in self.deltas],
            "missingMetrics": list(self.missing_metrics),
            "supportsAConclusion": self.supports_a_conclusion,
            "refusal": self.refusal,
            "limitations": list(self.limitations),
        }


def compare(baseline: EvaluationResult, candidate: EvaluationResult) -> Comparison:
    """Compare two results, refusing rather than averaging across setups."""

    if baseline.provenance.fingerprint() != candidate.provenance.fingerprint():
        mismatched = _mismatches(baseline, candidate)
        return Comparison(
            outcome="incomparable",
            baseline_detail_digest=baseline.digest(),
            candidate_detail_digest=candidate.digest(),
            deltas=(),
            missing_metrics=tuple(
                metric
                for metric in REQUIRED_METRICS
                if metric not in baseline.metrics or metric not in candidate.metrics
            ),
            refusal="evaluation setups differ: " + ", ".join(mismatched),
            limitations=(
                "No delta is reported because the two evaluations were not produced the same way.",
            ),
        )

    deltas: list[MetricDelta] = []
    improved = 0
    regressed = 0
    for metric in REQUIRED_METRICS:
        left = baseline.metrics.get(metric)
        right = candidate.metrics.get(metric)
        if left is None or right is None:
            continue
        # accuracy and macro_f1 are higher-is-better; the error is lower-is-better.
        higher_is_better = metric != "mean_absolute_error"
        change = float(right) - float(left)
        gained = change > 0 if higher_is_better else change < 0
        lost = change < 0 if higher_is_better else change > 0
        direction: Direction = "better" if gained else ("worse" if lost else "same")
        if direction == "better":
            improved += 1
        elif direction == "worse":
            regressed += 1
        deltas.append(
            MetricDelta(
                metric=metric,
                baseline=left,
                candidate=right,
                change=f"{change:+.6f}",
                direction=direction,
            )
        )

    if regressed and not improved:
        outcome: ComparisonOutcome = "regressed"
    elif improved and not regressed:
        outcome = "improved"
    elif improved == 0 and regressed == 0:
        outcome = "unchanged"
    else:
        outcome = "unchanged"

    return Comparison(
        outcome=outcome,
        baseline_detail_digest=baseline.digest(),
        candidate_detail_digest=candidate.digest(),
        deltas=tuple(deltas),
        missing_metrics=tuple(
            metric
            for metric in REQUIRED_METRICS
            if metric not in baseline.metrics or metric not in candidate.metrics
        ),
        limitations=(
            "A single held-out set carries no repeat-variance estimate; a difference "
            "at this sample size is not a significance claim.",
        ),
    )


def _mismatches(baseline: EvaluationResult, candidate: EvaluationResult) -> list[str]:
    fields = (
        ("dataset_digest", "dataset digest"),
        ("evaluator_name", "evaluator"),
        ("evaluator_version", "evaluator version"),
        ("split", "split"),
        ("seed", "seed"),
        ("example_count", "example count"),
    )
    differing = [
        label
        for attribute, label in fields
        if getattr(baseline.provenance, attribute) != getattr(candidate.provenance, attribute)
    ]
    return differing or ["provenance"]


__all__ = [
    "MIN_METRICS_FOR_SUPPORT",
    "REQUIRED_METRICS",
    "Comparison",
    "ComparisonError",
    "ComparisonOutcome",
    "EvaluationError",
    "MetricDelta",
    "compare",
]
