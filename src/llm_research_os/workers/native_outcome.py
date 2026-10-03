"""Reconcile a consumed remote native Attempt from its bound Worker observation."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC
from typing import Any

from llm_research_os.artifacts.store import MAX_WORKER_PUT_BYTES
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import request_digest
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import RunStatus
from llm_research_os.workers.errors import WorkerCallError
from llm_research_os.workers.models import WORKER_RUNTIME_NATIVE_REVIEWED
from llm_research_os.workers.native_claim import _append_bound, _event_id, _queue_rows
from llm_research_os.workers.native_outcome_documents import (
    NativeOutcomeReceipt,
    NativeOutcomeRequest,
)
from llm_research_os.workers.native_request import native_request_from_binding
from llm_research_os.workers.native_start import _journal
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import run_cancel_requested
from llm_research_os.workers.tokens import verify_grant_token


def reconcile_native_outcome(
    plane: WorkerPlane,
    *,
    worker_id: str,
    grant_token: str,
    document: NativeOutcomeRequest,
) -> NativeOutcomeReceipt:
    """Caller holds output_lock. Worker reports are not controller OS observations."""
    claims = verify_grant_token(plane.hmac_key, grant_token, now=plane.clock(), require_live=False)
    fold = plane.rebuild()
    lease, grant = plane._bind_result_authorization(
        fold, worker_id=worker_id, lease_id=document.start.lease_id, claims=claims
    )
    queued = fold.queued_work(lease.task_id, lease.attempt_id)
    if (
        queued is None
        or queued.runtime != WORKER_RUNTIME_NATIVE_REVIEWED
        or not lease.claimed
        or grant.consumed_lease_id != lease.lease_id
    ):
        raise WorkerCallError("native outcome lease differs", code="native-outcome-binding")
    plane._require_execution_match(grant, queued, claims)
    request = native_request_from_binding(
        plane.store, project_id=plane.project_id, grant=grant, queued=queued
    )
    if document.start.preparation.request_digest != request_digest(request):
        raise WorkerCallError("native outcome request differs", code="native-outcome-binding")
    start_binding = {
        "workerId": worker_id,
        "grantId": grant.grant_id,
        "start": document.start.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    # The start record originally checked the actual controller kernel and all material.
    from llm_research_os.workers.native_state import start_journal_name

    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
    with _journal(
        plane.store.path.parent,
        start_journal_name(plane.store.path, request),
        canonical_json(start_binding).encode(),
        allow_new=False,
    ):
        for event_type, payload, attempt in (*_queue_rows(request), ("attempt.started", {}, True)):
            if plane.store.get_event(_event_id(request, event_type)) is None:
                raise WorkerCallError(
                    "native outcome start is missing", code="native-outcome-binding"
                )
            _append_bound(run, plane, request, event_type, payload, attempt=attempt)
        state = run.rebuild().snapshot
        if (
            state is None
            or len(state.attempts) != 1
            or state.attempts[0].attempt_id != request.attempt_id
        ):
            raise WorkerCallError("native outcome Run differs", code="native-outcome-binding")
        body = document.model_dump(mode="json", by_alias=True, exclude_none=True)
        binding = {"workerId": worker_id, "grantId": grant.grant_id, "outcome": body}
        digest = content_digest(binding)
        if document.outcome == "unknown":
            if state.status not in {RunStatus.RUNNING, RunStatus.UNKNOWN}:
                raise WorkerCallError(
                    "terminal Run cannot become unknown", code="native-outcome-conflict"
                )
            if document.observation == "running":
                final_type = "attempt.started"
            else:
                _append_bound(
                    run,
                    plane,
                    request,
                    "attempt.unknown",
                    {"reasonCode": "native-outcome-uncertain"},
                    attempt=True,
                )
                final_type = "attempt.unknown"
        else:
            terminal_payload = canonical_json(binding).encode()
            if len(terminal_payload) > 16384:
                raise WorkerCallError("native outcome exceeds its bound", code="http-too-large")
            if document.outcome == "completed" and lease.status != "completed":
                raise WorkerCallError(
                    "verified completion is missing", code="native-outcome-conflict"
                )
            terminal_name = (
                "native-outcome-"
                + hashlib.sha256(
                    (start_journal_name(plane.store.path, request) + digest).encode()
                ).hexdigest()
                + ".json"
            )
            with _journal(
                plane.store.path.parent,
                terminal_name,
                terminal_payload,
                allow_new=state.status in {RunStatus.RUNNING, RunStatus.UNKNOWN},
            ):
                # Rebuild after journal I/O. Work completion/failure and cancellation remain facts.
                fold = plane.rebuild()
                lease, grant = plane._bind_result_authorization(
                    fold, worker_id=worker_id, lease_id=document.start.lease_id, claims=claims
                )
                requested = run_cancel_requested(
                    plane.store,
                    project_id=request.project_id,
                    run_id=request.run_id,
                    attempt_id=request.attempt_id,
                )
                types: tuple[tuple[str, dict[str, Any], bool], ...]
                if document.outcome == "completed":
                    if lease.status != "completed":
                        raise WorkerCallError(
                            "verified completion is missing", code="native-outcome-conflict"
                        )
                    from llm_research_os.workers.native_output import _output_document

                    if lease.artifact_digest is None or lease.result_digest is None:
                        raise WorkerCallError(
                            "verified completion is missing", code="native-outcome-conflict"
                        )
                    with plane.artifacts.open(lease.artifact_digest) as stream:
                        size = os.fstat(stream.fileno()).st_size
                        if not 0 < size <= min(request.limits.artifact_bytes, MAX_WORKER_PUT_BYTES):
                            raise WorkerCallError(
                                "native output exceeds its bound", code="native-outcome-binding"
                            )
                        output_bytes = stream.read(size + 1)
                    if (
                        len(output_bytes) != size
                        or "sha256:" + hashlib.sha256(output_bytes).hexdigest()
                        != lease.artifact_digest
                    ):
                        raise WorkerCallError(
                            "native output differs", code="native-outcome-binding"
                        )
                    output = _output_document(output_bytes, lease, request_digest(request))
                    if content_digest(output) != lease.result_digest:
                        raise WorkerCallError(
                            "verified output differs", code="native-outcome-binding"
                        )
                    types = (("attempt.succeeded", {}, True), ("run.completed", {}, False))
                elif document.outcome == "failed":
                    if lease.status != "failed":
                        if requested or grant.revoked:
                            raise WorkerCallError(
                                "native failure is cancelled", code="native-outcome-conflict"
                            )
                        plane._require_live_result_grant(
                            grant, claims, lease, now=plane.clock().astimezone(UTC)
                        )
                        plane.fail(
                            worker_id=worker_id,
                            grant_token=grant_token,
                            lease_id=lease.lease_id,
                            reason_code="native-task-failed",
                        )
                        settled = plane.rebuild().lease(lease.lease_id)
                        if settled is None:
                            raise WorkerCallError(
                                "native failure is missing", code="native-outcome-conflict"
                            )
                        lease = settled
                    if lease.reason_code != "native-task-failed":
                        raise WorkerCallError(
                            "native failure differs", code="native-outcome-conflict"
                        )
                    types = (
                        (
                            "attempt.failed",
                            {"reasonCode": "native-task-failed", "retryHint": "not-retryable"},
                            True,
                        ),
                        ("run.failed", {"reasonCode": "native-task-failed"}, False),
                    )
                else:
                    if grant.revoked and not requested:
                        _append_bound(
                            run,
                            plane,
                            request,
                            "run.cancel.requested",
                            {"reasonCode": "grant-revoked"},
                            attempt=False,
                        )
                    plane.fail_observed_cancellation(
                        worker_id=worker_id, grant_token=grant_token, lease_id=lease.lease_id
                    )
                    types = (("attempt.cancelled", {}, True), ("run.cancelled", {}, False))
                for event_type, payload_data, attempt in types:
                    _append_bound(run, plane, request, event_type, payload_data, attempt=attempt)
                final_type = types[-1][0]
        event = plane.store.get_event(_event_id(request, final_type))
        if event is None:
            raise WorkerCallError("native outcome fact is missing", code="native-outcome-conflict")
        return NativeOutcomeReceipt.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeOutcomeReceipt",
                "leaseId": document.start.lease_id,
                "bindingDigest": digest,
                "disposition": "running" if final_type == "attempt.started" else document.outcome,
                "eventId": event.event.id,
                "sequence": event.sequence,
                "launchAllowed": False,
            }
        )
