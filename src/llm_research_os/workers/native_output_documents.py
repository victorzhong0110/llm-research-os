"""External documents for one native result and its Worker completion receipt."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from llm_research_os.artifacts.store import MAX_WORKER_PUT_BYTES
from llm_research_os.execution.native_reviewed_documents import (
    ByteDigest,
    JcsDigest,
    NativeReviewedDocumentModel,
    ReviewedIdentifier,
)


class NativeReviewedTaskOutput(NativeReviewedDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedTaskOutput"]
    request_digest: JcsDigest = Field(alias="requestDigest")
    task_id: ReviewedIdentifier = Field(alias="taskId")
    run_id: ReviewedIdentifier = Field(alias="runId")
    attempt_id: ReviewedIdentifier = Field(alias="attemptId")
    output: JsonValue


class NativeOutputReceipt(NativeReviewedDocumentModel):
    digest: ByteDigest
    size_bytes: int = Field(alias="sizeBytes", ge=1, le=MAX_WORKER_PUT_BYTES)
    result_digest: JcsDigest = Field(alias="resultDigest")
    lease_id: str = Field(alias="leaseId", min_length=1, max_length=512, pattern=r"^[!-~]+$")
    event_id: str = Field(alias="eventId", min_length=1, max_length=540)
    type: Literal["work.completed"]
    sequence: int = Field(ge=1)
