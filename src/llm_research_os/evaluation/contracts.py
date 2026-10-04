"""Published evaluation, comparison and human conclusion document contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Digest = Annotated[str, Field(pattern=r"^jcs-sha256:[0-9a-f]{64}$")]
Ratio = Annotated[str, Field(pattern=r"^(?:0\.[0-9]{6}|1\.000000)$")]
Metric = Literal["accuracy", "macro_f1", "mean_absolute_error"]


class Document(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", allow_inf_nan=False)


class Metrics(Document):
    accuracy: Ratio
    macro_f1: Ratio
    mean_absolute_error: Ratio


class ExampleDetail(Document):
    example_id: Text = Field(alias="exampleId")
    predicted: Literal[0, 1]
    expected: Literal[0, 1]
    correct: bool
    absolute_error: Ratio = Field(alias="absoluteError")


class EvaluationDetailDocument(Document):
    api_version: Literal["researchos.dev/evaluation/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["EvaluationDetail"]
    dataset_digest: Digest = Field(alias="datasetDigest")
    evaluator_name: Text = Field(alias="evaluatorName")
    evaluator_version: Text = Field(alias="evaluatorVersion")
    split: Text
    seed: int = Field(ge=0)
    example_count: int = Field(alias="exampleCount", ge=1, le=10000)
    metrics: Metrics
    examples: list[ExampleDetail] = Field(min_length=1, max_length=10000)


class MetricDeltaDocument(Document):
    metric: Metric
    baseline: Ratio
    candidate: Ratio
    change: Annotated[str, Field(pattern=r"^[+-](?:0\.[0-9]{6}|1\.000000)$")]
    direction: Literal["better", "same", "worse", "incomparable"]


class EvaluationComparisonDocument(Document):
    api_version: Literal["researchos.dev/evaluation/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["EvaluationComparison"]
    outcome: Literal["improved", "regressed", "unchanged", "incomparable"]
    baseline_detail_digest: Digest = Field(alias="baselineDetailDigest")
    candidate_detail_digest: Digest = Field(alias="candidateDetailDigest")
    required_metrics: list[Metric] = Field(alias="requiredMetrics", max_length=3)
    deltas: list[MetricDeltaDocument] = Field(max_length=3)
    missing_metrics: list[Metric] = Field(alias="missingMetrics", max_length=3)
    supports_a_conclusion: bool = Field(alias="supportsAConclusion")
    refusal: Text | None
    limitations: list[Text] = Field(max_length=32)


class ResearchConclusionDocument(Document):
    api_version: Literal["researchos.dev/conclusion/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ResearchConclusion"]
    contract_version: Literal["v0alpha1"] = Field(alias="contractVersion")
    conclusion_id: Text = Field(alias="conclusionId")
    project_id: Text = Field(alias="projectId")
    experiment_revision: int = Field(alias="experimentRevision", ge=1)
    verdict: Literal["insufficient-evidence", "supported", "unsupported"]
    rationale: Text
    comparison_detail_digest: Digest = Field(alias="comparisonDetailDigest")
    evidence_refs: list[Text] = Field(alias="evidenceRefs", max_length=32)
    actor_id: Text = Field(alias="actorId")
