"""Project-scoped CAS append for Worker, work-lease, and grant facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore
from llm_research_os.workers.errors import WorkerCallError, WorkerPayloadError
from llm_research_os.workers.models import (
    WORKER_EVENT_TYPES,
    GrantConsumedPayload,
    GrantRecordedPayload,
    GrantRevokedPayload,
    WorkClaimedPayload,
    WorkCompletedPayload,
    WorkerRegisteredPayload,
    WorkFailedPayload,
    WorkLeasedPayload,
    WorkLeaseExpiredPayload,
    WorkQueuedPayload,
    parse_worker_payload,
    require_worker_actor,
)
from llm_research_os.workers.tokens import parse_rfc3339

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})
_TERMINAL_LEASE = frozenset({"completed", "failed", "expired"})


@dataclass(frozen=True, slots=True)
class WorkerRecord:
    worker_id: str
    accelerators: frozenset[str]


@dataclass(frozen=True, slots=True)
class GrantRecord:
    grant_id: str
    grant_event_id: str
    worker_id: str
    task_id: str
    nonce: str
    expires_at: str
    run_id: str
    attempt_id: str
    revoked: bool = False
    consumed_lease_id: str | None = None


@dataclass(frozen=True, slots=True)
class QueuedWork:
    task_id: str
    run_id: str
    attempt_id: str
    image_digest: str
    required_accelerators: frozenset[str]


@dataclass(frozen=True, slots=True)
class LeaseRecord:
    lease_id: str
    worker_id: str
    task_id: str
    grant_id: str
    run_id: str
    attempt_id: str
    expires_at: str
    claimed: bool = False
    status: str = "leased"
    result_digest: str | None = None
    artifact_digest: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerFold:
    workers: tuple[WorkerRecord, ...] = ()
    grants: tuple[GrantRecord, ...] = ()
    queued: tuple[QueuedWork, ...] = ()
    leases: tuple[LeaseRecord, ...] = ()

    def worker(self, worker_id: str) -> WorkerRecord | None:
        return next((item for item in self.workers if item.worker_id == worker_id), None)

    def grant(self, grant_id: str) -> GrantRecord | None:
        return next((item for item in self.grants if item.grant_id == grant_id), None)

    def queued_work(self, task_id: str, attempt_id: str) -> QueuedWork | None:
        return next(
            (
                item
                for item in self.queued
                if item.task_id == task_id and item.attempt_id == attempt_id
            ),
            None,
        )

    def lease(self, lease_id: str) -> LeaseRecord | None:
        return next((item for item in self.leases if item.lease_id == lease_id), None)

    def active_lease_for(
        self, task_id: str, attempt_id: str, *, now: datetime
    ) -> LeaseRecord | None:
        for item in self.leases:
            if item.task_id != task_id or item.attempt_id != attempt_id:
                continue
            if item.status in _TERMINAL_LEASE:
                continue
            if parse_rfc3339(item.expires_at) <= now.astimezone(UTC):
                continue
            return item
        return None

    def lease_for_worker(self, task_id: str, attempt_id: str, worker_id: str) -> LeaseRecord | None:
        matches = [
            item
            for item in self.leases
            if item.task_id == task_id
            and item.attempt_id == attempt_id
            and item.worker_id == worker_id
        ]
        return matches[-1] if matches else None


@dataclass(frozen=True, slots=True)
class WorkerHead:
    last_sequence: int
    fold: WorkerFold


class WorkerControl:
    """CAS-append one Worker or grant fact against a frozen fold."""

    def __init__(self, store: EventStore, *, project_id: str, page_size: int = 100) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._project_id = project_id

    def rebuild(self) -> WorkerHead:
        high_water = self._store.freeze_high_water()
        fold = WorkerFold()
        for stored in replay_events(
            self._store,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            fold = apply_worker_fold(fold, stored.event, project_id=self._project_id)
        return WorkerHead(last_sequence=high_water, fold=fold)

    def append(self, document: dict[str, Any]) -> StoredEvent:
        return self._append_at(self.rebuild(), document)

    def _append_at(self, head: WorkerHead, document: dict[str, Any]) -> StoredEvent:
        event = self._preflight_event(head, document)
        apply_worker_fold(head.fold, event, project_id=self._project_id)
        draft = snapshot_json_document(document)
        return self._store.append(draft, expected_last_sequence=head.last_sequence)

    def _preflight_event(self, head: WorkerHead, document: dict[str, Any]) -> ResearchEvent:
        frozen_head = head.last_sequence
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise WorkerCallError(str(exc), code="invalid-draft") from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise WorkerCallError(
                f"WorkerControl does not accept store-assigned fields; caller supplied: {supplied}",
                code="store-assigned-fields",
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise WorkerCallError("global event sequence is exhausted", code="sequence-exhausted")
        preflight_document = dict(draft)
        preflight_document.update(
            {
                "sequence": str(frozen_head + 1),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        preflight_event = _validate_preflight_event(preflight_document)
        if preflight_event.data.project_id != self._project_id:
            raise WorkerCallError(
                "event projectId does not match this WorkerControl",
                code="project-mismatch",
            )
        return preflight_event


def apply_worker_fold(fold: WorkerFold, event: ResearchEvent, *, project_id: str) -> WorkerFold:
    if event.data.project_id != project_id:
        return fold
    if event.type not in WORKER_EVENT_TYPES:
        return fold
    require_worker_actor(event)
    payload = parse_worker_payload(event)
    if isinstance(payload, WorkerRegisteredPayload):
        return _apply_registered(fold, payload)
    if isinstance(payload, GrantRecordedPayload):
        return _apply_grant_recorded(fold, event, payload)
    if isinstance(payload, GrantRevokedPayload):
        return _apply_grant_revoked(fold, payload)
    if isinstance(payload, GrantConsumedPayload):
        return _apply_grant_consumed(fold, payload)
    if isinstance(payload, WorkQueuedPayload):
        return _apply_queued(fold, event, payload)
    if isinstance(payload, WorkLeasedPayload):
        return _apply_leased(fold, event, payload)
    if isinstance(payload, WorkClaimedPayload):
        return _apply_claimed(fold, payload)
    if isinstance(payload, WorkCompletedPayload):
        return _apply_completed(fold, payload)
    if isinstance(payload, WorkFailedPayload):
        return _apply_failed(fold, payload)
    if isinstance(payload, WorkLeaseExpiredPayload):
        return _apply_expired(fold, payload)
    raise WorkerCallError("worker payload type is not foldable", code="unknown-worker-type")


def _apply_registered(fold: WorkerFold, payload: WorkerRegisteredPayload) -> WorkerFold:
    if fold.worker(payload.worker_id) is not None:
        raise WorkerCallError("workerId is already registered", code="duplicate-worker-id")
    record = WorkerRecord(
        worker_id=payload.worker_id,
        accelerators=frozenset(payload.accelerators),
    )
    return WorkerFold(
        workers=(*fold.workers, record),
        grants=fold.grants,
        queued=fold.queued,
        leases=fold.leases,
    )


def _apply_grant_recorded(
    fold: WorkerFold, event: ResearchEvent, payload: GrantRecordedPayload
) -> WorkerFold:
    if fold.grant(payload.grant_id) is not None:
        raise WorkerCallError("grantId is already recorded", code="duplicate-grant-id")
    if fold.worker(payload.worker_id) is None:
        raise WorkerCallError("grant workerId is not registered", code="unknown-worker")
    run_id = event.data.run_id
    attempt_id = event.data.attempt_id
    if run_id is None or attempt_id is None:
        raise WorkerCallError("grant events require runId and attemptId", code="grant-run-missing")
    record = GrantRecord(
        grant_id=payload.grant_id,
        grant_event_id=event.id,
        worker_id=payload.worker_id,
        task_id=payload.task_id,
        nonce=payload.nonce,
        expires_at=payload.expires_at,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=(*fold.grants, record),
        queued=fold.queued,
        leases=fold.leases,
    )


def _apply_grant_revoked(fold: WorkerFold, payload: GrantRevokedPayload) -> WorkerFold:
    current = fold.grant(payload.grant_id)
    if current is None:
        raise WorkerCallError("grantId is not recorded", code="unknown-grant")
    if current.revoked:
        raise WorkerCallError("grantId is already revoked", code="grant-already-revoked")
    updated = GrantRecord(
        grant_id=current.grant_id,
        grant_event_id=current.grant_event_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        nonce=current.nonce,
        expires_at=current.expires_at,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        revoked=True,
        consumed_lease_id=current.consumed_lease_id,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=_replace_grant(fold.grants, updated),
        queued=fold.queued,
        leases=fold.leases,
    )


def _apply_grant_consumed(fold: WorkerFold, payload: GrantConsumedPayload) -> WorkerFold:
    current = fold.grant(payload.grant_id)
    if current is None:
        raise WorkerCallError("grantId is not recorded", code="unknown-grant")
    if current.revoked:
        raise WorkerCallError("revoked grant cannot be consumed", code="grant-revoked")
    if current.nonce != payload.nonce:
        raise WorkerCallError("grant nonce does not match", code="grant-nonce-mismatch")
    if current.consumed_lease_id is not None:
        if current.consumed_lease_id == payload.lease_id:
            return fold
        raise WorkerCallError("grant nonce was already consumed", code="grant-replay")
    lease = fold.lease(payload.lease_id)
    if lease is None or lease.grant_id != payload.grant_id:
        raise WorkerCallError("grant consume lease does not match", code="grant-lease-mismatch")
    updated = GrantRecord(
        grant_id=current.grant_id,
        grant_event_id=current.grant_event_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        nonce=current.nonce,
        expires_at=current.expires_at,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        revoked=current.revoked,
        consumed_lease_id=payload.lease_id,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=_replace_grant(fold.grants, updated),
        queued=fold.queued,
        leases=fold.leases,
    )


def _apply_queued(fold: WorkerFold, event: ResearchEvent, payload: WorkQueuedPayload) -> WorkerFold:
    run_id = event.data.run_id
    attempt_id = event.data.attempt_id
    if run_id is None or attempt_id is None:
        raise WorkerCallError("work.queued requires runId and attemptId", code="work-run-missing")
    if fold.queued_work(payload.task_id, attempt_id) is not None:
        raise WorkerCallError("task attempt is already queued", code="duplicate-work")
    item = QueuedWork(
        task_id=payload.task_id,
        run_id=run_id,
        attempt_id=attempt_id,
        image_digest=payload.image_digest,
        required_accelerators=frozenset(payload.required_accelerators),
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=(*fold.queued, item),
        leases=fold.leases,
    )


def _apply_leased(fold: WorkerFold, event: ResearchEvent, payload: WorkLeasedPayload) -> WorkerFold:
    if fold.lease(payload.lease_id) is not None:
        raise WorkerCallError("leaseId is already recorded", code="duplicate-lease-id")
    worker = fold.worker(payload.worker_id)
    if worker is None:
        raise WorkerCallError("lease workerId is not registered", code="unknown-worker")
    grant = fold.grant(payload.grant_id)
    if grant is None:
        raise WorkerCallError("lease grantId is not recorded", code="unknown-grant")
    if grant.revoked:
        raise WorkerCallError("revoked grant cannot lease work", code="grant-revoked")
    if grant.worker_id != payload.worker_id or grant.task_id != payload.task_id:
        raise WorkerCallError("lease does not match the grant", code="grant-lease-mismatch")
    run_id = event.data.run_id
    attempt_id = event.data.attempt_id
    if run_id is None or attempt_id is None:
        raise WorkerCallError("work.leased requires runId and attemptId", code="work-run-missing")
    queued = fold.queued_work(payload.task_id, attempt_id)
    if queued is None:
        raise WorkerCallError("leased task attempt is not queued", code="unknown-work")
    if not queued.required_accelerators.issubset(worker.accelerators):
        raise WorkerCallError(
            "worker does not advertise required accelerators",
            code="accelerator-missing",
        )
    now = parse_rfc3339(event.time)
    active = fold.active_lease_for(payload.task_id, attempt_id, now=now)
    if active is not None:
        raise WorkerCallError("task attempt already has an active lease", code="lease-conflict")
    record = LeaseRecord(
        lease_id=payload.lease_id,
        worker_id=payload.worker_id,
        task_id=payload.task_id,
        grant_id=payload.grant_id,
        run_id=run_id,
        attempt_id=attempt_id,
        expires_at=payload.expires_at,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=fold.queued,
        leases=(*fold.leases, record),
    )


def _apply_claimed(fold: WorkerFold, payload: WorkClaimedPayload) -> WorkerFold:
    current = fold.lease(payload.lease_id)
    if current is None:
        raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
    if current.worker_id != payload.worker_id:
        raise WorkerCallError("claim worker does not own the lease", code="lease-worker-mismatch")
    if current.status in _TERMINAL_LEASE:
        raise WorkerCallError("terminal lease cannot be claimed", code="lease-terminal")
    if current.claimed:
        return fold
    updated = LeaseRecord(
        lease_id=current.lease_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        grant_id=current.grant_id,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        expires_at=current.expires_at,
        claimed=True,
        status=current.status,
        result_digest=current.result_digest,
        artifact_digest=current.artifact_digest,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=fold.queued,
        leases=_replace_lease(fold.leases, updated),
    )


def _apply_completed(fold: WorkerFold, payload: WorkCompletedPayload) -> WorkerFold:
    current = fold.lease(payload.lease_id)
    if current is None:
        raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
    if current.status == "completed":
        if (
            current.result_digest == payload.result_digest
            and current.artifact_digest == payload.artifact_digest
        ):
            return fold
        raise WorkerCallError("completed lease result does not match", code="complete-mismatch")
    if current.status in _TERMINAL_LEASE:
        raise WorkerCallError("terminal lease cannot be completed", code="lease-terminal")
    if not current.claimed:
        raise WorkerCallError("lease must be claimed before complete", code="lease-not-claimed")
    updated = LeaseRecord(
        lease_id=current.lease_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        grant_id=current.grant_id,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        expires_at=current.expires_at,
        claimed=True,
        status="completed",
        result_digest=payload.result_digest,
        artifact_digest=payload.artifact_digest,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=fold.queued,
        leases=_replace_lease(fold.leases, updated),
    )


def _apply_failed(fold: WorkerFold, payload: WorkFailedPayload) -> WorkerFold:
    current = fold.lease(payload.lease_id)
    if current is None:
        raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
    if current.status in _TERMINAL_LEASE:
        raise WorkerCallError("terminal lease cannot fail", code="lease-terminal")
    updated = LeaseRecord(
        lease_id=current.lease_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        grant_id=current.grant_id,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        expires_at=current.expires_at,
        claimed=current.claimed,
        status="failed",
        result_digest=current.result_digest,
        artifact_digest=current.artifact_digest,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=fold.queued,
        leases=_replace_lease(fold.leases, updated),
    )


def _apply_expired(fold: WorkerFold, payload: WorkLeaseExpiredPayload) -> WorkerFold:
    current = fold.lease(payload.lease_id)
    if current is None:
        raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
    if current.status in _TERMINAL_LEASE:
        if current.status == "expired":
            return fold
        raise WorkerCallError("terminal lease cannot expire", code="lease-terminal")
    updated = LeaseRecord(
        lease_id=current.lease_id,
        worker_id=current.worker_id,
        task_id=current.task_id,
        grant_id=current.grant_id,
        run_id=current.run_id,
        attempt_id=current.attempt_id,
        expires_at=current.expires_at,
        claimed=current.claimed,
        status="expired",
        result_digest=current.result_digest,
        artifact_digest=current.artifact_digest,
    )
    return WorkerFold(
        workers=fold.workers,
        grants=fold.grants,
        queued=fold.queued,
        leases=_replace_lease(fold.leases, updated),
    )


def _replace_grant(
    grants: tuple[GrantRecord, ...], updated: GrantRecord
) -> tuple[GrantRecord, ...]:
    return tuple(updated if item.grant_id == updated.grant_id else item for item in grants)


def _replace_lease(
    leases: tuple[LeaseRecord, ...], updated: LeaseRecord
) -> tuple[LeaseRecord, ...]:
    return tuple(updated if item.lease_id == updated.lease_id else item for item in leases)


def _require_page_size(page_size: int) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")
    return page_size


def _validate_preflight_event(document: dict[str, Any]) -> ResearchEvent:
    try:
        validated = validate_event_document(document)
    except ValidationError:
        payload_error = WorkerPayloadError(
            "event draft failed ResearchEvent validation",
            code="invalid-event",
        )
    else:
        return validated
    raise payload_error
