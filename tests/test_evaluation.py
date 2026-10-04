"""R13: real evaluation, comparison and human conclusions.

A reported number must be reproducible from its detail artifact, a comparison
must refuse incompatible setups, and a conclusion must remain a human judgement
that one improved score cannot manufacture.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.evaluation import (
    ConclusionError,
    EvaluationError,
    compare,
    evaluate,
    held_out_dataset,
    majority_baseline,
    recompute,
    record,
)
from llm_research_os.evaluation.evaluator import (
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    Provenance,
)

# --- The evaluator is real and deterministic -----------------------------------


def test_evaluation_is_deterministic() -> None:
    dataset = held_out_dataset()
    first = evaluate(dataset, threshold=0.45, mode="threshold")
    second = evaluate(dataset, threshold=0.45, mode="threshold")
    assert first.metrics == second.metrics
    assert first.digest() == second.digest()


def test_aggregate_is_reproducible_from_its_own_detail() -> None:
    """The R13 bar: a result must be re-derivable from what it ships with."""

    dataset = held_out_dataset()
    result = evaluate(dataset, threshold=0.45, mode="threshold")
    replayed = recompute(result, dataset)
    assert replayed.metrics == result.metrics
    assert replayed.digest() == result.digest()


def test_detail_artifact_carries_provenance_and_every_example() -> None:
    dataset = held_out_dataset()
    result = evaluate(dataset, threshold=0.45, mode="threshold")
    document = result.detail_document()
    assert document["evaluatorName"] == EVALUATOR_NAME
    assert document["evaluatorVersion"] == EVALUATOR_VERSION
    assert document["split"] == "held-out"
    assert document["seed"] == 0
    assert document["exampleCount"] == len(dataset)
    assert len(document["examples"]) == len(dataset)
    # The detail is real, not a summary: it names every example it scored.
    assert document["examples"][0]["exampleId"] == dataset[0].example_id
    assert json.loads(json.dumps(document)) == document


def test_metrics_are_fixed_precision_strings() -> None:
    """A metric is a string, so a comparison cannot depend on binary rounding."""

    result = evaluate(held_out_dataset(), threshold=0.45, mode="threshold")
    for value in result.metrics.values():
        assert isinstance(value, str)
        assert len(value.split(".")[1]) == 6


def test_baseline_is_real_and_deliberately_weak() -> None:
    dataset = held_out_dataset()
    baseline = evaluate(dataset, threshold=0.5, mode="majority")
    assert majority_baseline(dataset) in {0, 1}
    assert baseline.metrics["accuracy"] != "1.000000", (
        "a majority baseline that is perfect would not be a baseline worth comparing to"
    )


def test_empty_dataset_is_refused() -> None:
    with pytest.raises(EvaluationError, match="empty") as caught:
        evaluate((), threshold=0.5, mode="threshold")
    assert caught.value.code == "dataset-empty"


def test_out_of_range_threshold_is_refused() -> None:
    with pytest.raises(EvaluationError, match="threshold") as caught:
        evaluate(held_out_dataset(), threshold=1.5, mode="threshold")
    assert caught.value.code == "threshold-invalid"


# --- Comparison refuses incompatible setups ------------------------------------


def _result(*, seed: int = 0, split: str = "held-out") -> Any:
    return evaluate(held_out_dataset(), threshold=0.45, mode="threshold", seed=seed)


def test_comparison_reports_each_metric() -> None:
    dataset = held_out_dataset()
    baseline = evaluate(dataset, threshold=0.5, mode="majority")
    candidate = evaluate(dataset, threshold=0.45, mode="threshold")
    comparison = compare(baseline, candidate)
    assert comparison.outcome == "improved"
    assert {delta.metric for delta in comparison.deltas} == {
        "accuracy",
        "macro_f1",
        "mean_absolute_error",
    }
    accuracy = next(d for d in comparison.deltas if d.metric == "accuracy")
    assert accuracy.direction == "better"
    assert accuracy.change.startswith("+")


def test_different_dataset_is_refused_not_averaged() -> None:
    baseline = _result()
    other = evaluate(held_out_dataset(), threshold=0.45, mode="threshold", seed=7)
    comparison = compare(baseline, other)
    assert comparison.outcome == "incomparable"
    assert comparison.comparable is False
    assert comparison.refusal is not None
    assert "seed" in comparison.refusal
    assert comparison.deltas == ()


def test_different_evaluator_version_is_refused_and_named() -> None:
    baseline = _result()
    candidate = _result()
    shifted = type(candidate)(
        provenance=Provenance(
            dataset_digest=candidate.provenance.dataset_digest,
            evaluator_name=candidate.provenance.evaluator_name,
            evaluator_version="v0alpha2",
            split=candidate.provenance.split,
            seed=candidate.provenance.seed,
            example_count=candidate.provenance.example_count,
        ),
        metrics=candidate.metrics,
        details=candidate.details,
    )
    comparison = compare(baseline, shifted)
    assert comparison.outcome == "incomparable"
    assert "evaluator version" in (comparison.refusal or "")


def test_incomparable_comparison_states_its_limitation() -> None:
    comparison = compare(_result(), _result(seed=3))
    assert comparison.limitations, "a refusal must say why it cannot speak"
    assert comparison.document()["supportsAConclusion"] is False


def test_comparison_is_reported_as_a_regression_when_it_is_one() -> None:
    dataset = held_out_dataset()
    good = evaluate(dataset, threshold=0.45, mode="threshold")
    worse = evaluate(dataset, threshold=0.95, mode="threshold")
    comparison = compare(good, worse)
    assert comparison.outcome == "regressed"


# --- Conclusions are human judgements -----------------------------------------


def test_supported_conclusion_requires_a_supporting_comparison() -> None:
    dataset = held_out_dataset()
    comparison = compare(
        evaluate(dataset, threshold=0.5, mode="majority"),
        evaluate(dataset, threshold=0.45, mode="threshold"),
    )
    assert comparison.supports_a_conclusion is True
    conclusion = record(
        comparison,
        conclusion_id="conclusion.1",
        project_id="example-minimal",
        experiment_revision=1,
        verdict="supported",
        rationale="Accuracy and macro F1 both improve on the fixed held-out set.",
        evidence_refs=("sha256:" + "a" * 64,),
        actor_id="researcher.alice",
    )
    assert conclusion.verdict == "supported"
    assert conclusion.actor_id == "researcher.alice"
    assert conclusion.document()["kind"] == "ResearchConclusion"
    assert conclusion.contract_version == "v0alpha1"


def test_a_negative_result_is_a_valid_conclusion() -> None:
    dataset = held_out_dataset()
    comparison = compare(
        evaluate(dataset, threshold=0.45, mode="threshold"),
        evaluate(dataset, threshold=0.95, mode="threshold"),
    )
    conclusion = record(
        comparison,
        conclusion_id="conclusion.negative",
        project_id="example-minimal",
        experiment_revision=1,
        verdict="unsupported",
        rationale="The candidate threshold regresses on the held-out set.",
        evidence_refs=(),
        actor_id="researcher.alice",
    )
    assert conclusion.verdict == "unsupported"


def test_inconclusive_is_always_recordable() -> None:
    """Saying the evidence is insufficient is itself a finding."""

    comparison = compare(_result(), _result(seed=11))
    assert comparison.supports_a_conclusion is False
    conclusion = record(
        comparison,
        conclusion_id="conclusion.inconclusive",
        project_id="example-minimal",
        experiment_revision=1,
        verdict="insufficient-evidence",
        rationale="The two evaluations used different seeds, so no comparison is possible.",
        evidence_refs=(),
        actor_id="researcher.alice",
    )
    assert conclusion.verdict == "insufficient-evidence"


def test_a_refused_comparison_cannot_carry_a_supported_conclusion() -> None:
    comparison = compare(_result(), _result(seed=5))
    with pytest.raises(ConclusionError) as caught:
        record(
            comparison,
            conclusion_id="conclusion.refused",
            project_id="example-minimal",
            experiment_revision=1,
            verdict="supported",
            rationale="It looked better.",
            evidence_refs=(),
            actor_id="researcher.alice",
        )
    assert caught.value.code == "conclusion-unsupported"


def test_one_improved_metric_cannot_establish_a_conclusion() -> None:
    """The specific failure R13 names: a single better score is not a finding."""

    dataset = held_out_dataset()
    baseline = evaluate(dataset, threshold=0.5, mode="majority")
    candidate = evaluate(dataset, threshold=0.45, mode="threshold")
    # Keep only the single metric that moved, and drop the rest.
    thin = type(candidate)(
        provenance=candidate.provenance,
        metrics={"accuracy": candidate.metrics["accuracy"]},
        details=candidate.details,
    )
    comparison = compare(baseline, thin)
    assert comparison.comparable is True
    assert comparison.supports_a_conclusion is False
    with pytest.raises(ConclusionError, match="conclusion"):
        record(
            comparison,
            conclusion_id="conclusion.thin",
            project_id="example-minimal",
            experiment_revision=1,
            verdict="supported",
            rationale="Accuracy went up.",
            evidence_refs=(),
            actor_id="researcher.alice",
        )


def test_conclusion_requires_a_rationale_and_a_human_actor() -> None:
    dataset = held_out_dataset()
    comparison = compare(
        evaluate(dataset, threshold=0.5, mode="majority"),
        evaluate(dataset, threshold=0.45, mode="threshold"),
    )
    with pytest.raises(ConclusionError, match="rationale"):
        record(
            comparison,
            conclusion_id="conclusion.none",
            project_id="example-minimal",
            experiment_revision=1,
            verdict="supported",
            rationale="   ",
            evidence_refs=(),
            actor_id="researcher.alice",
        )
    with pytest.raises(ConclusionError, match="actor"):
        record(
            comparison,
            conclusion_id="conclusion.noactor",
            project_id="example-minimal",
            experiment_revision=1,
            verdict="supported",
            rationale="Looks better.",
            evidence_refs=(),
            actor_id="",
        )


def test_duplicate_evidence_references_are_refused() -> None:
    dataset = held_out_dataset()
    comparison = compare(
        evaluate(dataset, threshold=0.5, mode="majority"),
        evaluate(dataset, threshold=0.45, mode="threshold"),
    )
    digest = "sha256:" + "b" * 64
    with pytest.raises(ConclusionError, match="unique"):
        record(
            comparison,
            conclusion_id="conclusion.dup",
            project_id="example-minimal",
            experiment_revision=1,
            verdict="supported",
            rationale="Looks better.",
            evidence_refs=(digest, digest),
            actor_id="researcher.alice",
        )


# --- Storage -------------------------------------------------------------------


def test_detail_artifact_is_storable_and_addressable() -> None:
    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.evaluation.evaluator import detail_payload

    result = _result()
    with tempfile.TemporaryDirectory() as raw:
        store = LocalArtifactStore(Path(raw))
        payload = detail_payload(result)
        stored = store.put_bytes(payload)
        assert store.exists(stored.digest)
        # The CAS keys objects by raw SHA-256 while the result carries a JCS
        # semantic digest. They are different namespaces on purpose; what must
        # round-trip is the content, so the stored bytes replay to the same
        # metrics and the same semantic digest.
        with store.open(stored.digest) as stream:
            assert stream.read() == payload
        assert json.loads(payload.decode("utf-8")) == result.detail_document()


def test_error_tracks_predictions_and_majority_ignores_threshold() -> None:
    baseline = evaluate(threshold=0.1, mode="majority")
    assert baseline.metrics["mean_absolute_error"] == "0.500000"
    assert baseline.digest() == evaluate(threshold=0.9, mode="majority").digest()
    candidate = evaluate(threshold=0.45, mode="threshold")
    assert candidate.metrics["mean_absolute_error"] == "0.000000"
    assert all(
        item.absolute_error == abs(item.predicted - item.expected) for item in candidate.details
    )


@pytest.mark.parametrize(
    "fault",
    ["aggregate", "prediction", "correct", "error", "duplicate", "count", "seed", "missing"],
)
def test_inconsistent_detail_is_refused(fault: str) -> None:
    from llm_research_os.evaluation.evaluator import parse_detail

    document = evaluate(threshold=0.45, mode="threshold").detail_document()
    changes = {
        "aggregate": lambda: document["metrics"].update(accuracy="0.000000"),
        "prediction": lambda: document["examples"][0].update(predicted=True),
        "correct": lambda: document["examples"][0].update(correct="true"),
        "error": lambda: document["examples"][0].update(absoluteError="NaN"),
        "duplicate": lambda: document["examples"][1].update(exampleId="ex-01"),
        "count": lambda: document.update(exampleCount=11),
        "seed": lambda: document.update(seed=True),
        "missing": lambda: document["examples"][0].pop("predicted"),
    }
    changes[fault]()
    with pytest.raises(EvaluationError, match="malformed or inconsistent"):
        parse_detail(document)


def test_recompute_refuses_a_different_dataset() -> None:
    from dataclasses import replace

    rows = held_out_dataset()
    result = evaluate(rows, threshold=0.45, mode="threshold")
    different = (replace(rows[0], label=1), *rows[1:])
    with pytest.raises(EvaluationError, match="does not identify"):
        recompute(result, different)
