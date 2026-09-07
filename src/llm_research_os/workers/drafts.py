"""Caller-owned Worker and grant event drafts. Store-assigned fields are omitted."""

from __future__ import annotations

from typing import Any

from llm_research_os.events.models import RESEARCH_EVENT_SCHEMA_ID
from llm_research_os.workers.models import (
    TYPE_GRANT_CONSUMED,
    TYPE_GRANT_RECORDED,
    TYPE_GRANT_REVOKED,
    TYPE_WORK_CLAIMED,
    TYPE_WORK_COMPLETED,
    TYPE_WORK_FAILED,
    TYPE_WORK_LEASE_EXPIRED,
    TYPE_WORK_LEASED,
    TYPE_WORK_QUEUED,
    TYPE_WORKER_REGISTERED,
)


def worker_event_draft(
    *,
    event_id: str,
    event_type: str,
    time: str,
    source: str,
    subject: str,
    stream_id: str,
    actor: dict[str, str],
    project_id: str,
    experiment_revision: int,
    payload: dict[str, Any],
    evidence_refs: tuple[str, ...] = (),
    run_id: str | None = None,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": actor,
        "projectId": project_id,
        "experimentRevision": experiment_revision,
        "payload": payload,
        "evidenceRefs": list(evidence_refs),
    }
    if run_id is not None:
        data["runId"] = run_id
    if attempt_id is not None:
        data["attemptId"] = attempt_id
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": event_type,
        "time": time,
        "subject": subject,
        "dataschema": RESEARCH_EVENT_SCHEMA_ID,
        "datacontenttype": "application/json",
        "streamid": stream_id,
        "data": data,
    }


def registered_draft(
    *,
    project_id: str,
    worker_id: str,
    event_id: str,
    time: str,
    source: str,
    actor_id: str,
    accelerators: tuple[str, ...] = (),
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORKER_REGISTERED,
        time=time,
        source=source,
        subject=worker_id,
        stream_id=project_id,
        actor={"id": actor_id, "kind": "human"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={
            "workerId": worker_id,
            "runtime": "python-sandbox",
            "protocol": "researchos.worker-longpoll/v0alpha1",
            "accelerators": list(accelerators),
        },
    )


def grant_recorded_draft(
    *,
    project_id: str,
    grant_id: str,
    worker_id: str,
    task_id: str,
    run_id: str,
    attempt_id: str,
    nonce: str,
    expires_at: str,
    event_id: str,
    time: str,
    source: str,
    actor_id: str,
    authorization_event_id: str,
    authorization_sequence: str,
    image_digest: str,
    config_digest: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_GRANT_RECORDED,
        time=time,
        source=source,
        subject=grant_id,
        stream_id=project_id,
        actor={"id": actor_id, "kind": "human"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={
            "grantId": grant_id,
            "workerId": worker_id,
            "taskId": task_id,
            "nonce": nonce,
            "expiresAt": expires_at,
            "keyId": "local.hmac.1",
            "authorizationEventId": authorization_event_id,
            "authorizationSequence": authorization_sequence,
            "imageDigest": image_digest,
            "configDigest": config_digest,
        },
        run_id=run_id,
        attempt_id=attempt_id,
    )


def grant_revoked_draft(
    *,
    project_id: str,
    grant_id: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    actor_id: str,
    reason_code: str = "human.revoke",
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_GRANT_REVOKED,
        time=time,
        source=source,
        subject=grant_id,
        stream_id=project_id,
        actor={"id": actor_id, "kind": "human"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"grantId": grant_id, "reasonCode": reason_code},
        run_id=run_id,
        attempt_id=attempt_id,
    )


def grant_consumed_draft(
    *,
    project_id: str,
    grant_id: str,
    lease_id: str,
    nonce: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    worker_id: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_GRANT_CONSUMED,
        time=time,
        source=source,
        subject=grant_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"grantId": grant_id, "leaseId": lease_id, "nonce": nonce},
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_queued_draft(
    *,
    project_id: str,
    task_id: str,
    run_id: str,
    attempt_id: str,
    image_digest: str,
    config_digest: str,
    event_id: str,
    time: str,
    source: str,
    actor_id: str = "control.plane",
    config: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    required_accelerators: tuple[str, ...] = (),
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_QUEUED,
        time=time,
        source=source,
        subject=task_id,
        stream_id=project_id,
        actor={"id": actor_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={
            "taskId": task_id,
            "imageDigest": image_digest,
            "imageMediaType": "researchos.python-brick/v0alpha1",
            "runtime": "python-sandbox",
            "config": dict(config or {}),
            "inputs": dict(inputs or {}),
            "configDigest": config_digest,
            "requiredAccelerators": list(required_accelerators),
        },
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_leased_draft(
    *,
    project_id: str,
    lease_id: str,
    worker_id: str,
    task_id: str,
    grant_id: str,
    run_id: str,
    attempt_id: str,
    expires_at: str,
    event_id: str,
    time: str,
    source: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_LEASED,
        time=time,
        source=source,
        subject=lease_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={
            "leaseId": lease_id,
            "workerId": worker_id,
            "taskId": task_id,
            "grantId": grant_id,
            "expiresAt": expires_at,
        },
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_claimed_draft(
    *,
    project_id: str,
    lease_id: str,
    worker_id: str,
    nonce: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_CLAIMED,
        time=time,
        source=source,
        subject=lease_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"leaseId": lease_id, "workerId": worker_id, "nonce": nonce},
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_completed_draft(
    *,
    project_id: str,
    lease_id: str,
    worker_id: str,
    result_digest: str,
    artifact_digest: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_COMPLETED,
        time=time,
        source=source,
        subject=lease_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={
            "leaseId": lease_id,
            "resultDigest": result_digest,
            "artifactDigest": artifact_digest,
        },
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_failed_draft(
    *,
    project_id: str,
    lease_id: str,
    worker_id: str,
    reason_code: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_FAILED,
        time=time,
        source=source,
        subject=lease_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"leaseId": lease_id, "reasonCode": reason_code},
        run_id=run_id,
        attempt_id=attempt_id,
    )


def work_lease_expired_draft(
    *,
    project_id: str,
    lease_id: str,
    worker_id: str,
    run_id: str,
    attempt_id: str,
    event_id: str,
    time: str,
    source: str,
    reason_code: str = "lease.expired",
    experiment_revision: int = 1,
) -> dict[str, Any]:
    return worker_event_draft(
        event_id=event_id,
        event_type=TYPE_WORK_LEASE_EXPIRED,
        time=time,
        source=source,
        subject=lease_id,
        stream_id=project_id,
        actor={"id": worker_id, "kind": "system"},
        project_id=project_id,
        experiment_revision=experiment_revision,
        payload={"leaseId": lease_id, "reasonCode": reason_code},
        run_id=run_id,
        attempt_id=attempt_id,
    )
