"""Versioned real-model detail and evidence-linked human report contracts."""

from typing import Annotated, Literal

from pydantic import Field

from llm_research_os.evaluation.contracts import (
    Digest,
    Document,
    EvaluationComparisonDocument,
    EvaluationDetailDocument,
    Text,
)

ByteDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class TrainingProvenance(Document):
    project_id: Text = Field(alias="projectId")
    experiment_revision: int = Field(alias="experimentRevision", ge=1)
    run_id: Text = Field(alias="runId")
    attempt_id: Text = Field(alias="attemptId")
    task_id: Text = Field(alias="taskId")
    output_artifact: ByteDigest = Field(alias="outputArtifact")
    request_artifact: ByteDigest = Field(alias="requestArtifact")
    request_digest: Digest = Field(alias="requestDigest")
    source_digest: ByteDigest = Field(alias="sourceDigest")
    training_dataset_digest: Digest = Field(alias="trainingDatasetDigest")
    config_digest: Digest = Field(alias="configDigest")
    model_digest: Digest = Field(alias="modelDigest")
    completed_event_id: Text = Field(alias="completedEventId")
    completed_sequence: int = Field(alias="completedSequence", ge=1)
    proposal_id: Text | None = Field(alias="proposalId")
    decision_id: Text | None = Field(alias="decisionId")


class TrainedEvaluationDetail(Document):
    api_version: Literal["researchos.dev/evaluation/v0alpha2"] = Field(alias="apiVersion")
    kind: Literal["TrainedEvaluationDetail"]
    label: Literal["real-trained-public-development-benchmark"]
    model_role: Literal["baseline", "candidate"] = Field(alias="modelRole")
    provenance: TrainingProvenance
    detail: EvaluationDetailDocument
    failure_example_ids: list[Text] = Field(alias="failureExampleIds", max_length=20)
    limitations: list[Text] = Field(max_length=32)


class TrainedComparison(Document):
    api_version: Literal["researchos.dev/evaluation/v0alpha2"] = Field(alias="apiVersion")
    kind: Literal["TrainedComparison"]
    baseline_artifact: ByteDigest = Field(alias="baselineArtifact")
    candidate_artifact: ByteDigest = Field(alias="candidateArtifact")
    baseline: TrainingProvenance
    candidate: TrainingProvenance
    comparison: EvaluationComparisonDocument
    limitations: list[Text] = Field(max_length=32)
    system_derived_conclusion: Literal[False] = Field(alias="systemDerivedConclusion")


class ResearchReport(Document):
    api_version: Literal["researchos.dev/conclusion/v0alpha2"] = Field(alias="apiVersion")
    kind: Literal["ResearchReport"]
    contract_version: Literal["v0alpha2"] = Field(alias="contractVersion")
    report_id: Text = Field(alias="reportId")
    project_id: Text = Field(alias="projectId")
    experiment_revision: int = Field(alias="experimentRevision", ge=1)
    actor_id: Text = Field(alias="actorId")
    actor_kind: Literal["human"] = Field(alias="actorKind")
    submitted_at: Text = Field(alias="submittedAt")
    comparison_digest: Digest = Field(alias="comparisonDigest")
    comparison: TrainedComparison
    narrative: Annotated[str, Field(min_length=1, max_length=12000)]
    verdict: Literal["insufficient-evidence", "supported", "unsupported"]
    rationale: Text
    evidence_refs: list[Text] = Field(alias="evidenceRefs", max_length=32)
    system_derived: Literal[False] = Field(alias="systemDerived")
