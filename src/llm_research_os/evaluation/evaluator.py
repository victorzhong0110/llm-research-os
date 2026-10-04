"""One deterministic evaluator over fixed held-out data (R13).

The point of this module is that a reported number is *reproducible from its
detail artifact*. Every evaluation names the dataset digest, the evaluator
version, the seed and the split it was computed on, and the per-example detail
is stored alongside the aggregate. Nothing here is sampled at random, and
nothing here reports a result it did not actually compute.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.evaluation.contracts import EvaluationDetailDocument

EVALUATOR_NAME: Final = "heldout-majority-and-threshold"
EVALUATOR_VERSION: Final = "v0alpha1"
SPLIT_NAME: Final = "held-out"
DEFAULT_SEED: Final = 0

# A metric value is a fixed-precision decimal string, never a float, so a
# comparison cannot depend on binary rounding.
_RATIO_PATTERN: Final = re.compile(r"^(?:0|1)(?:\.[0-9]{6})$")

MetricName = Literal["accuracy", "macro_f1", "mean_absolute_error"]


class EvaluationError(ValueError):
    """One evaluation fault with a closed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Example:
    """One held-out item: a feature vector and its label."""

    example_id: str
    features: tuple[float, ...]
    label: int


@dataclass(frozen=True, slots=True)
class Detail:
    """Per-example outcome. This is what makes an aggregate reproducible."""

    example_id: str
    predicted: int
    expected: int
    correct: bool
    absolute_error: float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to re-run the evaluation and get the same numbers."""

    dataset_digest: str
    evaluator_name: str
    evaluator_version: str
    split: str
    seed: int
    example_count: int

    def document(self) -> dict[str, object]:
        return {
            "datasetDigest": self.dataset_digest,
            "evaluatorName": self.evaluator_name,
            "evaluatorVersion": self.evaluator_version,
            "split": self.split,
            "seed": self.seed,
            "exampleCount": self.example_count,
        }

    def fingerprint(self) -> str:
        """Identity of the evaluation setup, for refusing incomparable runs."""

        return content_digest(self.document())


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """An aggregate plus the detail it was computed from."""

    provenance: Provenance
    metrics: dict[str, str]
    details: tuple[Detail, ...]

    def detail_document(self) -> dict[str, object]:
        return {
            "apiVersion": "researchos.dev/evaluation/v0alpha1",
            "kind": "EvaluationDetail",
            **self.provenance.document(),
            "metrics": dict(sorted(self.metrics.items())),
            "examples": [
                {
                    "exampleId": item.example_id,
                    "predicted": item.predicted,
                    "expected": item.expected,
                    "correct": item.correct,
                    "absoluteError": f"{item.absolute_error:.6f}",
                }
                for item in self.details
            ],
        }

    def digest(self) -> str:
        return content_digest(self.detail_document())


def held_out_dataset() -> tuple[Example, ...]:
    """The fixed held-out set. Committed, tiny, and never regenerated at runtime.

    Deliberately not random: a dataset that changed per run would make every
    reported number incomparable with the last one.
    """

    rows: tuple[tuple[str, tuple[float, ...], int], ...] = (
        ("ex-01", (0.10, 0.20), 0),
        ("ex-02", (0.12, 0.24), 0),
        ("ex-03", (0.08, 0.15), 0),
        ("ex-04", (0.30, 0.35), 0),
        ("ex-05", (0.28, 0.40), 0),
        ("ex-06", (0.55, 0.60), 1),
        ("ex-07", (0.62, 0.66), 1),
        ("ex-08", (0.58, 0.71), 1),
        ("ex-09", (0.70, 0.75), 1),
        ("ex-10", (0.66, 0.80), 1),
        ("ex-11", (0.05, 0.09), 0),
        ("ex-12", (0.90, 0.95), 1),
    )
    return tuple(Example(name, features, label) for name, features, label in rows)


def dataset_digest(examples: tuple[Example, ...] | None = None) -> str:
    """Content digest of the dataset, so a changed split is a different dataset."""

    rows = examples if examples is not None else held_out_dataset()
    return content_digest(
        [
            [item.example_id, [f"{value:.6f}" for value in item.features], item.label]
            for item in rows
        ]
    )


def majority_baseline(examples: tuple[Example, ...] | None = None) -> int:
    """The baseline predictor: always answer the most common label.

    A real, deterministic, and deliberately weak baseline. Comparing a candidate
    against it says something true; comparing against a hand-picked number says
    nothing.
    """

    rows = examples if examples is not None else held_out_dataset()
    if not rows:
        raise EvaluationError("dataset-empty", "the held-out set is empty")
    ones = sum(1 for item in rows if item.label == 1)
    return 1 if ones * 2 > len(rows) else 0


def predict(example: Example, *, threshold: float, mode: Literal["majority", "threshold"]) -> int:
    if mode == "majority":
        return majority_baseline()
    mean = sum(example.features) / len(example.features)
    return 1 if mean >= threshold else 0


def evaluate(
    examples: tuple[Example, ...] | None = None,
    *,
    threshold: float,
    mode: Literal["majority", "threshold"],
    seed: int = DEFAULT_SEED,
) -> EvaluationResult:
    """Compute accuracy, macro F1 and mean absolute error over the held-out set."""

    rows = examples if examples is not None else held_out_dataset()
    if not rows:
        raise EvaluationError("dataset-empty", "the held-out set is empty")
    if not 0.0 < threshold < 1.0:
        raise EvaluationError("threshold-invalid", "threshold must be strictly between 0 and 1")
    if mode not in {"majority", "threshold"} or type(seed) is not int or seed < 0:
        raise EvaluationError("setup-invalid", "unknown predictor or invalid seed")
    if len({item.example_id for item in rows}) != len(rows) or any(
        not item.example_id
        or type(item.label) is not int
        or item.label not in (0, 1)
        or not item.features
        or any(not math.isfinite(value) for value in item.features)
        for item in rows
    ):
        raise EvaluationError(
            "dataset-invalid", "examples must have unique IDs, finite features and binary labels"
        )
    details = tuple(
        Detail(
            example_id=item.example_id,
            predicted=predict(item, threshold=threshold, mode=mode),
            expected=item.label,
            correct=predict(item, threshold=threshold, mode=mode) == item.label,
            absolute_error=float(abs(predict(item, threshold=threshold, mode=mode) - item.label)),
        )
        for item in rows
    )
    metrics = {
        "accuracy": _ratio(_accuracy(details)),
        "macro_f1": _ratio(_macro_f1(details)),
        "mean_absolute_error": _ratio(_mean_absolute_error(details)),
    }
    return EvaluationResult(
        provenance=Provenance(
            dataset_digest=dataset_digest(rows),
            evaluator_name=EVALUATOR_NAME,
            evaluator_version=EVALUATOR_VERSION,
            split=SPLIT_NAME,
            seed=seed,
            example_count=len(rows),
        ),
        metrics=metrics,
        details=details,
    )


def recompute(result: EvaluationResult, examples: tuple[Example, ...]) -> EvaluationResult:
    """Re-derive an aggregate from its own stored detail.

    This is the reproducibility check: a report that cannot be reproduced from
    its detail artifact is not a result.
    """

    if len(examples) != len(result.details):
        raise EvaluationError("detail-length-mismatch", "detail and dataset lengths differ")
    if result.provenance.dataset_digest != dataset_digest(examples) or any(
        item.example_id != example.example_id or item.expected != example.label
        for item, example in zip(result.details, examples, strict=True)
    ):
        raise EvaluationError("detail-dataset-mismatch", "detail does not identify this dataset")
    replayed = tuple(
        Detail(
            example_id=item.example_id,
            predicted=item.predicted,
            expected=item.expected,
            correct=item.predicted == item.expected,
            absolute_error=float(abs(item.predicted - example.label)),
        )
        for item, example in zip(result.details, examples, strict=True)
    )
    return EvaluationResult(
        provenance=result.provenance,
        metrics={
            "accuracy": _ratio(_accuracy(replayed)),
            "macro_f1": _ratio(_macro_f1(replayed)),
            "mean_absolute_error": _ratio(_mean_absolute_error(replayed)),
        },
        details=replayed,
    )


def _ratio(value: float) -> str:
    """Format a metric as a fixed-precision string, clamped to [0, 1]."""

    bounded = min(1.0, max(0.0, value))
    text = f"{bounded:.6f}"
    if _RATIO_PATTERN.match(text) is None:  # pragma: no cover - formatting is total
        raise EvaluationError("metric-format", "metric could not be formatted")
    return text


def _accuracy(details: tuple[Detail, ...]) -> float:
    correct = sum(1 for item in details if item.correct)
    return correct / len(details)


def _macro_f1(details: tuple[Detail, ...]) -> float:
    scores = []
    for label in (0, 1):
        true_positive = sum(
            1 for item in details if item.expected == label and item.predicted == label
        )
        false_positive = sum(
            1 for item in details if item.expected != label and item.predicted == label
        )
        false_negative = sum(
            1 for item in details if item.expected == label and item.predicted != label
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else (2 * true_positive) / denominator)
    return sum(scores) / len(scores)


def _mean_absolute_error(details: tuple[Detail, ...]) -> float:
    return sum(item.absolute_error for item in details) / len(details)


def detail_payload(result: EvaluationResult) -> bytes:
    """Canonical bytes for the detail artifact."""

    return canonical_json(result.detail_document()).encode("utf-8")


def parse_detail(document: Any) -> EvaluationResult:
    """Refuse malformed or internally inconsistent detail before comparison."""
    try:
        EvaluationDetailDocument.model_validate(document)
        if (
            type(document) is not dict
            or document["kind"] != "EvaluationDetail"
            or document["apiVersion"] != "researchos.dev/evaluation/v0alpha1"
        ):
            raise ValueError("unknown detail contract")
        fields = ("datasetDigest", "evaluatorName", "evaluatorVersion", "split")
        if any(type(document[key]) is not str or not document[key] for key in fields):
            raise ValueError("invalid provenance")
        if re.fullmatch(r"jcs-sha256:[0-9a-f]{64}", document["datasetDigest"]) is None:
            raise ValueError("invalid dataset digest")
        seed, count = document["seed"], document["exampleCount"]
        if type(seed) is not int or seed < 0 or type(count) is not int or not 1 <= count <= 10000:
            raise ValueError("invalid counts")
        examples = document["examples"]
        if type(examples) is not list or len(examples) != count:
            raise ValueError("invalid examples")
        details = []
        for item in examples:
            if (
                type(item) is not dict
                or type(item["exampleId"]) is not str
                or not item["exampleId"]
            ):
                raise ValueError("invalid example identity")
            prediction, expected = item["predicted"], item["expected"]
            if (
                type(prediction) is not int
                or prediction not in (0, 1)
                or type(expected) is not int
                or expected not in (0, 1)
            ):
                raise ValueError("invalid binary classification")
            if type(item["correct"]) is not bool or item["correct"] != (prediction == expected):
                raise ValueError("inconsistent correctness")
            error = item["absoluteError"]
            if type(error) is not str or error != f"{abs(prediction - expected):.6f}":
                raise ValueError("inconsistent prediction error")
            details.append(
                Detail(item["exampleId"], prediction, expected, item["correct"], float(error))
            )
        rows = tuple(details)
        if len({item.example_id for item in rows}) != count:
            raise ValueError("duplicate examples")
        metrics = {
            "accuracy": _ratio(_accuracy(rows)),
            "macro_f1": _ratio(_macro_f1(rows)),
            "mean_absolute_error": _ratio(_mean_absolute_error(rows)),
        }
        if document["metrics"] != metrics:
            raise ValueError("aggregate does not match examples")
        return EvaluationResult(
            Provenance(
                document["datasetDigest"],
                document["evaluatorName"],
                document["evaluatorVersion"],
                document["split"],
                seed,
                count,
            ),
            metrics,
            rows,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EvaluationError(
            "detail-invalid", "evaluation detail is malformed or inconsistent"
        ) from exc
