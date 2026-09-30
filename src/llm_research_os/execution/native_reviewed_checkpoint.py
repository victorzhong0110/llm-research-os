"""Evidence gate for a new reviewed Attempt using a prior task checkpoint.

The profile cannot infer Python optimizer semantics. The reviewed task must
explicitly export and consume a structured state envelope of the same mode.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from llm_research_os.artifacts.errors import ArtifactStoreError
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import (
    ByteDigest,
    NativeReviewedDocumentModel,
    NativeReviewedExecutionRequest,
    ReviewedIdentifier,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import RunStatus
from llm_research_os.workers.plane import WorkerPlane


class NativeRestoreError(ValueError):
    """The proposed checkpoint cannot authorize a restored Attempt."""


class NativeRestoreClaim(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeRestoreClaim"]
    mode: Literal["full-state", "adapter-only"]
    source_run_id: ReviewedIdentifier = Field(alias="sourceRunId")
    source_attempt_id: ReviewedIdentifier = Field(alias="sourceAttemptId")
    target_run_id: ReviewedIdentifier = Field(alias="targetRunId")
    target_attempt_id: ReviewedIdentifier = Field(alias="targetAttemptId")
    checkpoint_input: ReviewedIdentifier = Field(alias="checkpointInput")
    artifact_digest: ByteDigest = Field(alias="artifactDigest")


def verify_native_restore(
    *,
    claim: NativeRestoreClaim,
    source: NativeReviewedExecutionRequest,
    target: NativeReviewedExecutionRequest,
    plane: WorkerPlane,
) -> None:
    """Verify CAS, completed lineage, task mode, new identity, and exact runtime.

    This is a prerequisite to launch, never permission to replay the source
    Attempt. A full-state envelope must include model, optimizer, scheduler,
    and RNG; an adapter envelope never claims optimizer-state restoration.
    """

    if (
        source.project_id != target.project_id
        or source.project_id != plane.project_id
        or (source.run_id, source.attempt_id) != (claim.source_run_id, claim.source_attempt_id)
        or (target.run_id, target.attempt_id) != (claim.target_run_id, claim.target_attempt_id)
        or source.run_id == target.run_id
        or source.attempt_id == target.attempt_id
    ):
        raise NativeRestoreError("restore lineage is incompatible")
    if (
        source.code != target.code
        or source.environment != target.environment
        or source.platform != target.platform
    ):
        raise NativeRestoreError("restore code or environment differs")
    inputs = [item for item in target.inputs if item.purpose == "checkpoint"]
    if len(inputs) != 1 or inputs[0].name != claim.checkpoint_input:
        raise NativeRestoreError("exactly one bound checkpoint input is required")
    if inputs[0].digest != claim.artifact_digest:
        raise NativeRestoreError("checkpoint input digest differs")
    snapshot = (
        RunControl(plane.store, project_id=source.project_id, run_id=source.run_id)
        .rebuild()
        .snapshot
    )
    if snapshot is None or snapshot.status != RunStatus.COMPLETED:
        raise NativeRestoreError("source Run has no completed outcome")
    leases = [
        item
        for item in plane.rebuild().leases
        if item.run_id == source.run_id and item.attempt_id == source.attempt_id
    ]
    if len(leases) != 1 or leases[0].status != "completed":
        raise NativeRestoreError("source lease has no completed artifact")
    if leases[0].artifact_digest != claim.artifact_digest:
        raise NativeRestoreError("checkpoint is not the source result artifact")
    try:
        artifact = plane.artifacts.verify(claim.artifact_digest)
        if artifact.size_bytes != inputs[0].size_bytes:
            raise NativeRestoreError("checkpoint size differs")
        with plane.artifacts.open(claim.artifact_digest) as stream:
            document = json.load(stream)
    except NativeRestoreError:
        raise
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise NativeRestoreError("checkpoint CAS object is missing or invalid") from exc
    if not isinstance(document, dict) or (
        document.get("runId") != source.run_id
        or document.get("attemptId") != source.attempt_id
        or document.get("requestDigest") != request_digest(source)
    ):
        raise NativeRestoreError("checkpoint result envelope differs")
    checkpoint = document.get("output")
    if not isinstance(checkpoint, dict) or checkpoint.get("restoreMode") != claim.mode:
        raise NativeRestoreError("checkpoint restore mode differs")
    state = checkpoint.get("state")
    required = (
        {"model", "optimizer", "scheduler", "rng"} if claim.mode == "full-state" else {"adapter"}
    )
    if (
        not isinstance(state, dict)
        or not required.issubset(state)
        or any(state[key] in (None, "", {}, []) for key in required)
    ):
        raise NativeRestoreError("checkpoint lacks required state components")
    # The target's changed input must be part of its separately authorized plan.
    if target.config_digest == source.config_digest or execution_object(target) == execution_object(
        source
    ):
        raise NativeRestoreError("restore requires a distinct authorized execution object")
