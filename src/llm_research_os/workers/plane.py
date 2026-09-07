"""Semantic Worker plane: leases, grants, and completion. Heartbeats stay off the log."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.control import LeaseRecord, WorkerControl, WorkerFold
from llm_research_os.workers.drafts import (
    grant_consumed_draft,
    grant_recorded_draft,
    grant_revoked_draft,
    registered_draft,
    work_claimed_draft,
    work_completed_draft,
    work_failed_draft,
    work_lease_expired_draft,
    work_leased_draft,
    work_queued_draft,
)
from llm_research_os.workers.errors import WorkerCallError, WorkerGrantError
from llm_research_os.workers.tokens import (
    format_rfc3339,
    issue_grant_token,
    parse_rfc3339,
    require_hmac_key,
    verify_grant_token,
    verify_worker_session,
)

Clock = Callable[[], datetime]
DEFAULT_LEASE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ClaimedWork:
    lease_id: str
    worker_id: str
    task_id: str
    run_id: str
    attempt_id: str
    grant_id: str
    nonce: str
    image_digest: str
    expires_at: str


@dataclass
class WorkerPlane:
    """In-process Worker semantics. HTTP is a binding, not a second protocol (ADR-0009)."""

    store: EventStore
    artifacts: LocalArtifactStore
    hmac_key: bytes
    project_id: str
    source: str
    experiment_revision: int = 1
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    clock: Clock = field(default=lambda: datetime.now(UTC))
    heartbeats: dict[str, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_hmac_key(self.hmac_key)
        self._control = WorkerControl(self.store, project_id=self.project_id)

    def rebuild(self) -> WorkerFold:
        return self._control.rebuild().fold

    def register(
        self,
        *,
        worker_id: str,
        actor_id: str,
        event_id: str,
        accelerators: tuple[str, ...] = (),
        time: str | None = None,
    ) -> StoredEvent:
        return self._control.append(
            registered_draft(
                project_id=self.project_id,
                worker_id=worker_id,
                event_id=event_id,
                time=self._stamp(time),
                source=self.source,
                actor_id=actor_id,
                accelerators=accelerators,
                experiment_revision=self.experiment_revision,
            )
        )

    def record_grant(
        self,
        *,
        grant_id: str,
        worker_id: str,
        task_id: str,
        run_id: str,
        attempt_id: str,
        nonce: str,
        expires_at: str,
        actor_id: str,
        event_id: str,
        time: str | None = None,
    ) -> StoredEvent:
        return self._control.append(
            grant_recorded_draft(
                project_id=self.project_id,
                grant_id=grant_id,
                worker_id=worker_id,
                task_id=task_id,
                run_id=run_id,
                attempt_id=attempt_id,
                nonce=nonce,
                expires_at=expires_at,
                event_id=event_id,
                time=self._stamp(time),
                source=self.source,
                actor_id=actor_id,
                experiment_revision=self.experiment_revision,
            )
        )

    def revoke_grant(
        self,
        *,
        grant_id: str,
        actor_id: str,
        event_id: str,
        reason_code: str = "human.revoke",
        time: str | None = None,
    ) -> StoredEvent:
        grant = self.rebuild().grant(grant_id)
        if grant is None:
            raise WorkerCallError("grantId is not recorded", code="unknown-grant")
        return self._control.append(
            grant_revoked_draft(
                project_id=self.project_id,
                grant_id=grant_id,
                run_id=grant.run_id,
                attempt_id=grant.attempt_id,
                event_id=event_id,
                time=self._stamp(time),
                source=self.source,
                actor_id=actor_id,
                reason_code=reason_code,
                experiment_revision=self.experiment_revision,
            )
        )

    def enqueue(
        self,
        *,
        task_id: str,
        run_id: str,
        attempt_id: str,
        image_digest: str,
        event_id: str,
        required_accelerators: tuple[str, ...] = (),
        time: str | None = None,
    ) -> StoredEvent:
        return self._control.append(
            work_queued_draft(
                project_id=self.project_id,
                task_id=task_id,
                run_id=run_id,
                attempt_id=attempt_id,
                image_digest=image_digest,
                event_id=event_id,
                time=self._stamp(time),
                source=self.source,
                required_accelerators=required_accelerators,
                experiment_revision=self.experiment_revision,
            )
        )

    def issue_token(self, grant_id: str) -> str:
        grant = self.rebuild().grant(grant_id)
        if grant is None:
            raise WorkerGrantError("grantId is not recorded", code="unknown-grant")
        if grant.revoked:
            raise WorkerGrantError("grantId is revoked", code="grant-revoked")
        return issue_grant_token(
            self.hmac_key,
            grant_id=grant.grant_id,
            grant_event_id=grant.grant_event_id,
            worker_id=grant.worker_id,
            task_id=grant.task_id,
            attempt_id=grant.attempt_id,
            run_id=grant.run_id,
            nonce=grant.nonce,
            expires_at=grant.expires_at,
        )

    def heartbeat(self, *, worker_id: str, session: str, lease_id: str) -> None:
        """Transport liveness only. Must not append EventStore facts (ADR-0041)."""

        session_worker = verify_worker_session(self.hmac_key, session)
        if session_worker != worker_id:
            raise WorkerGrantError("worker session does not match", code="worker-session-mismatch")
        fold = self.rebuild()
        lease = fold.lease(lease_id)
        if lease is None or lease.worker_id != worker_id:
            raise WorkerCallError(
                "heartbeat lease is not owned by this worker",
                code="unknown-lease",
            )
        self.heartbeats[lease_id] = self.clock()

    def poll(self, *, worker_id: str, grant_token: str) -> ClaimedWork | None:
        now = self.clock().astimezone(UTC)
        claims = verify_grant_token(self.hmac_key, grant_token, now=now)
        if claims["workerId"] != worker_id:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        fold = self.rebuild()
        grant = fold.grant(claims["grantId"])
        if grant is None:
            raise WorkerGrantError("grantId is not recorded", code="unknown-grant")
        self._require_live_grant(grant, claims, now=now)
        queued = fold.queued_work(grant.task_id, grant.attempt_id)
        if queued is None:
            return None
        existing = fold.lease_for_worker(grant.task_id, grant.attempt_id, worker_id)
        if existing is not None:
            return self._resume_or_reject(fold, existing, queued, grant, now=now)
        active = fold.active_lease_for(grant.task_id, grant.attempt_id, now=now)
        if active is not None:
            raise WorkerCallError("task attempt already has an active lease", code="lease-conflict")
        stale = _stale_lease(fold, grant.task_id, grant.attempt_id, now=now)
        if stale is not None and stale.status not in {"expired", "completed", "failed"}:
            self.expire_lease(lease_id=stale.lease_id)
            fold = self.rebuild()
        return self._open_lease(fold, queued, grant, now=now)

    def expire_lease(self, *, lease_id: str, time: str | None = None) -> StoredEvent:
        fold = self.rebuild()
        lease = fold.lease(lease_id)
        if lease is None:
            raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
        return self._control.append(
            work_lease_expired_draft(
                project_id=self.project_id,
                lease_id=lease.lease_id,
                worker_id=lease.worker_id,
                run_id=lease.run_id,
                attempt_id=lease.attempt_id,
                event_id=f"evt.work.lease.expired.{lease.lease_id}",
                time=self._stamp(time),
                source=self.source,
                experiment_revision=self.experiment_revision,
            )
        )

    def complete(
        self,
        *,
        worker_id: str,
        grant_token: str,
        lease_id: str,
        result_digest: str,
        artifact_digest: str,
        time: str | None = None,
    ) -> StoredEvent:
        now = self.clock().astimezone(UTC)
        claims = verify_grant_token(self.hmac_key, grant_token, now=now)
        if claims["workerId"] != worker_id:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        fold = self.rebuild()
        lease = fold.lease(lease_id)
        if lease is None:
            raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
        if lease.worker_id != worker_id:
            raise WorkerCallError(
                "complete worker does not own the lease",
                code="lease-worker-mismatch",
            )
        if parse_rfc3339(lease.expires_at) <= now:
            raise WorkerCallError("expired lease cannot complete", code="lease-expired")
        if lease.status == "completed":
            if lease.result_digest == result_digest and lease.artifact_digest == artifact_digest:
                stored = self.store.get_event(f"evt.work.completed.{lease.lease_id}")
                if stored is None:
                    raise WorkerCallError(
                        "completed lease is missing its fact",
                        code="complete-missing",
                    )
                return stored
            raise WorkerCallError("completed lease result does not match", code="complete-mismatch")
        try:
            self.artifacts.verify(artifact_digest)
        except (ArtifactNotFoundError, ArtifactStoreError):
            raise WorkerCallError(
                "complete artifact digest is not in CAS",
                code="artifact-missing",
            ) from None
        return self._control.append(
            work_completed_draft(
                project_id=self.project_id,
                lease_id=lease.lease_id,
                worker_id=worker_id,
                result_digest=result_digest,
                artifact_digest=artifact_digest,
                run_id=lease.run_id,
                attempt_id=lease.attempt_id,
                event_id=f"evt.work.completed.{lease.lease_id}",
                time=self._stamp(time),
                source=self.source,
                experiment_revision=self.experiment_revision,
            )
        )

    def fail(
        self,
        *,
        worker_id: str,
        grant_token: str,
        lease_id: str,
        reason_code: str,
        time: str | None = None,
    ) -> StoredEvent:
        now = self.clock().astimezone(UTC)
        claims = verify_grant_token(self.hmac_key, grant_token, now=now)
        if claims["workerId"] != worker_id:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        fold = self.rebuild()
        lease = fold.lease(lease_id)
        if lease is None or lease.worker_id != worker_id:
            raise WorkerCallError("fail worker does not own the lease", code="unknown-lease")
        return self._control.append(
            work_failed_draft(
                project_id=self.project_id,
                lease_id=lease.lease_id,
                worker_id=worker_id,
                reason_code=reason_code,
                run_id=lease.run_id,
                attempt_id=lease.attempt_id,
                event_id=f"evt.work.failed.{lease.lease_id}",
                time=self._stamp(time),
                source=self.source,
                experiment_revision=self.experiment_revision,
            )
        )

    def _open_lease(
        self,
        fold: WorkerFold,
        queued: Any,
        grant: Any,
        *,
        now: datetime,
    ) -> ClaimedWork:
        worker = fold.worker(grant.worker_id)
        if worker is None:
            raise WorkerCallError("workerId is not registered", code="unknown-worker")
        if not queued.required_accelerators.issubset(worker.accelerators):
            raise WorkerCallError(
                "worker does not advertise required accelerators",
                code="accelerator-missing",
            )
        lease_id = f"lease.{grant.grant_id}"
        expires_at = format_rfc3339(now + timedelta(seconds=self.lease_seconds))
        stamp = format_rfc3339(now)
        self._control.append(
            work_leased_draft(
                project_id=self.project_id,
                lease_id=lease_id,
                worker_id=grant.worker_id,
                task_id=grant.task_id,
                grant_id=grant.grant_id,
                run_id=queued.run_id,
                attempt_id=queued.attempt_id,
                expires_at=expires_at,
                event_id=f"evt.work.leased.{lease_id}",
                time=stamp,
                source=self.source,
                experiment_revision=self.experiment_revision,
            )
        )
        self._control.append(
            work_claimed_draft(
                project_id=self.project_id,
                lease_id=lease_id,
                worker_id=grant.worker_id,
                nonce=grant.nonce,
                run_id=queued.run_id,
                attempt_id=queued.attempt_id,
                event_id=f"evt.work.claimed.{lease_id}",
                time=stamp,
                source=self.source,
                experiment_revision=self.experiment_revision,
            )
        )
        self._control.append(
            grant_consumed_draft(
                project_id=self.project_id,
                grant_id=grant.grant_id,
                lease_id=lease_id,
                nonce=grant.nonce,
                run_id=queued.run_id,
                attempt_id=queued.attempt_id,
                event_id=f"evt.grant.consumed.{grant.grant_id}",
                time=stamp,
                source=self.source,
                worker_id=grant.worker_id,
                experiment_revision=self.experiment_revision,
            )
        )
        self.heartbeats[lease_id] = now
        return ClaimedWork(
            lease_id=lease_id,
            worker_id=grant.worker_id,
            task_id=grant.task_id,
            run_id=queued.run_id,
            attempt_id=queued.attempt_id,
            grant_id=grant.grant_id,
            nonce=grant.nonce,
            image_digest=queued.image_digest,
            expires_at=expires_at,
        )

    def _resume_or_reject(
        self,
        fold: WorkerFold,
        existing: LeaseRecord,
        queued: Any,
        grant: Any,
        *,
        now: datetime,
    ) -> ClaimedWork | None:
        if existing.status == "completed":
            return None
        if existing.status in {"failed", "expired"}:
            raise WorkerCallError("terminal lease cannot be resumed", code="lease-terminal")
        if parse_rfc3339(existing.expires_at) <= now:
            self.expire_lease(lease_id=existing.lease_id)
            raise WorkerCallError("expired lease cannot be claimed", code="lease-expired")
        if not existing.claimed:
            stamp = format_rfc3339(now)
            self._control.append(
                work_claimed_draft(
                    project_id=self.project_id,
                    lease_id=existing.lease_id,
                    worker_id=existing.worker_id,
                    nonce=grant.nonce,
                    run_id=existing.run_id,
                    attempt_id=existing.attempt_id,
                    event_id=f"evt.work.claimed.{existing.lease_id}",
                    time=stamp,
                    source=self.source,
                    experiment_revision=self.experiment_revision,
                )
            )
        grant_record = fold.grant(grant.grant_id)
        if grant_record is not None and grant_record.consumed_lease_id is None:
            stamp = format_rfc3339(now)
            self._control.append(
                grant_consumed_draft(
                    project_id=self.project_id,
                    grant_id=grant.grant_id,
                    lease_id=existing.lease_id,
                    nonce=grant.nonce,
                    run_id=existing.run_id,
                    attempt_id=existing.attempt_id,
                    event_id=f"evt.grant.consumed.{grant.grant_id}",
                    time=stamp,
                    source=self.source,
                    worker_id=grant.worker_id,
                    experiment_revision=self.experiment_revision,
                )
            )
        self.heartbeats[existing.lease_id] = now
        return ClaimedWork(
            lease_id=existing.lease_id,
            worker_id=existing.worker_id,
            task_id=existing.task_id,
            run_id=existing.run_id,
            attempt_id=existing.attempt_id,
            grant_id=existing.grant_id,
            nonce=grant.nonce,
            image_digest=queued.image_digest,
            expires_at=existing.expires_at,
        )

    def _require_live_grant(self, grant: Any, claims: dict[str, str], *, now: datetime) -> None:
        if grant.revoked:
            raise WorkerGrantError("grantId is revoked", code="grant-revoked")
        if grant.worker_id != claims["workerId"]:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        if grant.grant_event_id != claims["grantEventId"]:
            raise WorkerGrantError("grant event id does not match", code="grant-event-mismatch")
        if grant.nonce != claims["nonce"]:
            raise WorkerGrantError("grant nonce does not match", code="grant-nonce-mismatch")
        if parse_rfc3339(grant.expires_at) <= now:
            raise WorkerGrantError("grant token has expired", code="grant-expired")

    def _stamp(self, time: str | None) -> str:
        if time is not None:
            return time
        return format_rfc3339(self.clock())


def _stale_lease(
    fold: WorkerFold, task_id: str, attempt_id: str, *, now: datetime
) -> LeaseRecord | None:
    matches = [
        item for item in fold.leases if item.task_id == task_id and item.attempt_id == attempt_id
    ]
    if not matches:
        return None
    latest = matches[-1]
    if latest.status in {"completed", "failed", "expired"}:
        return None
    if parse_rfc3339(latest.expires_at) <= now:
        return latest
    return None
