"""Recompute fixed trained outputs and bind them to verified native Run facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import Workspace
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.evaluation import iris
from llm_research_os.evaluation.compare import compare
from llm_research_os.evaluation.evaluator import (
    Detail,
    EvaluationResult,
    Example,
    Provenance,
    dataset_digest,
    parse_detail,
    recompute,
)
from llm_research_os.evaluation.trained_contracts import TrainedEvaluationDetail
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_material import NativeReviewedPythonBundle
from llm_research_os.research.control import ResearchControl
from llm_research_os.runs.control import RunControl
from llm_research_os.storage import EventStore
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.models import WORKER_RUNTIME_NATIVE_REVIEWED
from llm_research_os.workers.native_output_documents import NativeReviewedTaskOutput

LIMITATIONS = [
    "Public development benchmark, not unseen validation or independent confirmation.",
    "One deterministic 80/20 split, seed 0; no repeat-variance or significance estimate.",
    "Binary Iris subset, raw features and training-only centroids/majority; not an LLM benchmark.",
    "Accuracy and binary MAE are complementary; three metrics are not independent evidence.",
    "A real CPU training run verifies integration; no general research improvement is established.",
]


def detail_documents(
    workspace: Workspace,
    request: NativeReviewedExecutionRequest,
    request_artifact: str,
    output_artifact: str,
    read: Any,
    decision_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refuse caller-asserted completion, substituted model bytes or absent lineage."""
    if request.project_id != workspace.project_id:
        raise ApplicationError("evaluation-project", "training belongs to another project")
    output_document = json.loads(read(Path(output_artifact)))
    envelope = NativeReviewedTaskOutput.model_validate(output_document)
    if (
        envelope.request_digest != request_digest(request)
        or envelope.task_id != request.task_id
        or envelope.run_id != request.run_id
        or envelope.attempt_id != request.attempt_id
    ):
        raise ApplicationError("evaluation-lineage", "output identity does not match request")
    source = Path(iris.__file__).read_bytes()
    source_digest = "sha256:" + hashlib.sha256(source).hexdigest()
    bundle = NativeReviewedPythonBundle.model_validate_json(read(Path(request.code.bundle_digest)))
    if (
        bundle.entrypoint != "brick.task:main"
        or request.code.entrypoint != bundle.entrypoint
        or len(bundle.files) != 1
        or bundle.files[0].path != "brick/task.py"
        or bundle.files[0].digest != source_digest
        or read(Path(source_digest)) != source
    ):
        raise ApplicationError("evaluation-source", "unsupported training implementation")
    expected = iris.main()
    if canonical_json(envelope.output) != canonical_json(expected):
        raise ApplicationError("evaluation-model", "model parameters or predictions failed replay")
    with EventStore(workspace.control_db, create=False) as store:
        worker = WorkerControl(store, project_id=workspace.project_id).rebuild().fold
        queued = worker.queued_work(request.task_id, request.attempt_id)
        if (
            queued is None
            or queued.run_id != request.run_id
            or queued.runtime != WORKER_RUNTIME_NATIVE_REVIEWED
            or queued.image_digest != request.code.bundle_digest
            or queued.config != execution_object(request)
        ):
            raise ApplicationError("evaluation-lineage", "training queue identity does not match")
        leases = [
            lease
            for lease in worker.leases
            if lease.run_id == request.run_id
            and lease.attempt_id == request.attempt_id
            and lease.task_id == request.task_id
            and lease.status == "completed"
            and lease.artifact_digest == output_artifact
            and lease.result_digest == content_digest(output_document)
        ]
        if len(leases) != 1:
            raise ApplicationError("evaluation-lineage", "no unique verified Worker completion")
        run = (
            RunControl(store, project_id=workspace.project_id, run_id=request.run_id)
            .rebuild()
            .snapshot
        )
        if (
            run is None
            or run.status.value != "completed"
            or run.experiment_revision != int(request.revision_id)
            or not any(
                a.attempt_id == request.attempt_id and a.status.value == "succeeded"
                for a in run.attempts
            )
        ):
            raise ApplicationError("evaluation-lineage", "the actual Run did not complete")
        facts = store.read_events(
            project_id=workspace.project_id,
            run_id=request.run_id,
            event_types=frozenset({"work.completed"}),
            limit=100,
        )
        matches = [
            f
            for f in facts
            if f.event.data.attempt_id == request.attempt_id
            and f.event.data.payload.get("leaseId") == leases[0].lease_id
        ]
        if len(matches) != 1 or matches[0].event.data.experiment_revision != int(
            request.revision_id
        ):
            raise ApplicationError("evaluation-lineage", "completion revision does not match")
        fact = matches[0]
        proposal_id = None
        if decision_id is not None:
            ledger = ResearchControl(store, project_id=workspace.project_id).rebuild().snapshot
            decision = next((d for d in ledger.decisions if d.decision_id == decision_id), None)
            proposal = next(
                (
                    p
                    for p in ledger.proposals
                    if decision is not None and p.proposal_id == decision.target_id
                ),
                None,
            )
            queued_runs = store.read_events(
                project_id=workspace.project_id,
                run_id=request.run_id,
                event_types=frozenset({"run.queued"}),
                limit=100,
            )
            if (
                decision is None
                or decision.target_kind.value != "proposal"
                or decision.outcome.value != "accept"
                or proposal is None
                or proposal.proposed_spec_digest != request.spec_digest
                or proposal.base_revision + 1 != int(request.revision_id)
                or len(queued_runs) != 1
                or decision.sequence >= queued_runs[0].sequence
            ):
                raise ApplicationError(
                    "evaluation-decision", "accepted proposal does not precede this exact Run spec"
                )
            proposal_id = proposal.proposal_id
    rows = tuple(
        Example(row["id"], tuple(float(x) for x in row["features"]), row["label"])
        for row in expected["heldout"]
    )
    documents = []
    for role in ("baseline", "candidate"):
        details = tuple(
            Detail(
                row.example_id,
                prediction[role],
                row.label,
                prediction[role] == row.label,
                float(abs(prediction[role] - row.label)),
            )
            for row, prediction in zip(rows, expected["predictions"], strict=True)
        )
        result = recompute(
            EvaluationResult(
                Provenance(
                    dataset_digest(rows), "iris-fixed-trained-binary", "v0alpha1", "held-out", 0, 20
                ),
                {},
                details,
            ),
            rows,
        )
        document = {
            "apiVersion": "researchos.dev/evaluation/v0alpha2",
            "kind": "TrainedEvaluationDetail",
            "label": "real-trained-public-development-benchmark",
            "modelRole": role,
            "provenance": {
                "projectId": workspace.project_id,
                "experimentRevision": int(request.revision_id),
                "runId": request.run_id,
                "attemptId": request.attempt_id,
                "taskId": request.task_id,
                "outputArtifact": output_artifact,
                "requestArtifact": request_artifact,
                "requestDigest": request_digest(request),
                "sourceDigest": source_digest,
                "trainingDatasetDigest": content_digest(expected["training"]),
                "configDigest": content_digest(iris.CONFIG),
                "modelDigest": content_digest(expected["models"][role]),
                "completedEventId": fact.event.id,
                "completedSequence": fact.sequence,
                "proposalId": proposal_id,
                "decisionId": decision_id,
            },
            "detail": result.detail_document(),
            "failureExampleIds": [d.example_id for d in details if not d.correct],
            "limitations": list(LIMITATIONS),
        }
        TrainedEvaluationDetail.model_validate(document)
        documents.append(document)
    return documents[0], documents[1]


def load_detail(workspace: Workspace, digest: str, read: Any) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(read(Path(digest)))
    parsed = TrainedEvaluationDetail.model_validate(document)
    request = NativeReviewedExecutionRequest.model_validate_json(
        read(Path(parsed.provenance.request_artifact))
    )
    pair = detail_documents(
        workspace,
        request,
        parsed.provenance.request_artifact,
        parsed.provenance.output_artifact,
        read,
        parsed.provenance.decision_id,
    )
    expected = pair[0 if parsed.model_role == "baseline" else 1]
    if canonical_json(document) != canonical_json(expected):
        raise ApplicationError("evaluation-detail", "detail differs from verified model replay")
    return document


def comparison_document(
    workspace: Workspace, baseline: str, candidate: str, read: Any
) -> dict[str, Any]:
    left, right = load_detail(workspace, baseline, read), load_detail(workspace, candidate, read)
    if left["modelRole"] != "baseline" or right["modelRole"] != "candidate":
        raise ApplicationError(
            "evaluation-roles", "select baseline then candidate trained artifacts"
        )
    comparison = compare(parse_detail(left["detail"]), parse_detail(right["detail"]))
    fields = ("projectId", "experimentRevision", "configDigest", "trainingDatasetDigest")
    differing = [
        field for field in fields if left["provenance"][field] != right["provenance"][field]
    ]
    if differing:
        comparison = replace(
            comparison,
            outcome="incomparable",
            deltas=(),
            refusal="training setups differ: " + ", ".join(differing),
        )
    # The evidence is the full typed detail, not merely a score-bearing subobject.
    comparison = replace(
        comparison,
        baseline_detail_digest=content_digest(left),
        candidate_detail_digest=content_digest(right),
    )
    return {
        "apiVersion": "researchos.dev/evaluation/v0alpha2",
        "kind": "TrainedComparison",
        "baselineArtifact": baseline,
        "candidateArtifact": candidate,
        "baseline": left["provenance"],
        "candidate": right["provenance"],
        "comparison": comparison.document(),
        "limitations": list(LIMITATIONS),
        "systemDerivedConclusion": False,
    }
