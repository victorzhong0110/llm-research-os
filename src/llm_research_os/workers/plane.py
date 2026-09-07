"""Semantic Worker plane: leases, grants, and completion. Heartbeats stay off the log."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.binding import (
    brick_execution_digest,
    require_authorized_execution_binding,
    require_execution_digest,
)
from llm_research_os.workers.control import (
    GrantRecord,
    LeaseRecord,
    QueuedWork,
    WorkerControl,
    WorkerFold,
)
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
    config_digest: str
    config: dict[str, object]
    inputs: dict[str, object]
    runtime: str
    expires_at: str
    resumed: bool


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
        authorization_event_id: str,
        authorization_sequence: str,
        image_digest: str,
        config_digest: str,
        spec: ResearchSpec,
        registry: BlockRegistry,
        time: str | None = None,
        workflow_id: str | None = None,
    ) -> StoredEvent:
        require_authorized_execution_binding(
            self.store,
            spec,
            registry,
            project_id=self.project_id,
            experiment_revision=self.experiment_revision,
            planned_task_id=task_id,
            event_id=authorization_event_id,
            sequence=authorization_sequence,
            image_digest=image_digest,
            config_digest=config_digest,
            workflow_id=workflow_id,
        )
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
                authorization_event_id=authorization_event_id,
                authorization_sequence=authorization_sequence,
                image_digest=image_digest,
                config_digest=config_digest,
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
        config: dict[str, object] | None = None,
        inputs: dict[str, object] | None = None,
        required_accelerators: tuple[str, ...] = (),
        time: str | None = None,
    ) -> StoredEvent:
        request_config = dict(config or {})
        request_inputs = dict(inputs or {})
        config_digest = brick_execution_digest(
            image_digest=image_digest,
            config=request_config,
            inputs=request_inputs,
        )
        return self._control.append(
            work_queued_draft(
                project_id=self.project_id,
                task_id=task_id,
                run_id=run_id,
                attempt_id=attempt_id,
                image_digest=image_digest,
                config_digest=config_digest,
                event_id=event_id,
                time=self._stamp(time),
                source=self.source,
                config=request_config,
                inputs=request_inputs,
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
            project_id=self.project_id,
            image_digest=grant.image_digest,
            config_digest=grant.config_digest,
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
        self._require_execution_match(grant, queued, claims)
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
        claims = verify_grant_token(self.hmac_key, grant_token, now=now, require_live=False)
        fold = self.rebuild()
        lease, grant = self._bind_result_authorization(
            fold, worker_id=worker_id, lease_id=lease_id, claims=claims
        )
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
        self._require_live_result_grant(grant, claims, lease, now=now)
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
        claims = verify_grant_token(self.hmac_key, grant_token, now=now, require_live=False)
        fold = self.rebuild()
        lease, grant = self._bind_result_authorization(
            fold, worker_id=worker_id, lease_id=lease_id, claims=claims
        )
        if lease.status == "failed":
            if lease.reason_code == reason_code:
                stored = self.store.get_event(f"evt.work.failed.{lease.lease_id}")
                if stored is None:
                    raise WorkerCallError(
                        "failed lease is missing its fact",
                        code="fail-missing",
                    )
                return stored
            raise WorkerCallError("failed lease reason does not match", code="fail-mismatch")
        self._require_live_result_grant(grant, claims, lease, now=now)
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
        queued: QueuedWork,
        grant: GrantRecord,
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
        self._require_execution_match(grant, queued, None)
        try:
            self.artifacts.verify(queued.image_digest)
        except (ArtifactNotFoundError, ArtifactStoreError):
            raise WorkerCallError(
                "authorized image digest is not in CAS",
                code="execution-binding-mismatch",
            ) from None
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
        return self._claimed(
            lease_id=lease_id,
            worker_id=grant.worker_id,
            task_id=grant.task_id,
            run_id=queued.run_id,
            attempt_id=queued.attempt_id,
            grant_id=grant.grant_id,
            nonce=grant.nonce,
            queued=queued,
            expires_at=expires_at,
            resumed=False,
        )

    def _resume_or_reject(
        self,
        fold: WorkerFold,
        existing: LeaseRecord,
        queued: QueuedWork,
        grant: GrantRecord,
        *,
        now: datetime,
    ) -> ClaimedWork | None:
        already_claimed = existing.claimed
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
        return self._claimed(
            lease_id=existing.lease_id,
            worker_id=existing.worker_id,
            task_id=existing.task_id,
            run_id=existing.run_id,
            attempt_id=existing.attempt_id,
            grant_id=existing.grant_id,
            nonce=grant.nonce,
            queued=queued,
            expires_at=existing.expires_at,
            resumed=already_claimed,
        )

    def _claimed(
        self,
        *,
        lease_id: str,
        worker_id: str,
        task_id: str,
        run_id: str,
        attempt_id: str,
        grant_id: str,
        nonce: str,
        queued: QueuedWork,
        expires_at: str,
        resumed: bool,
    ) -> ClaimedWork:
        return ClaimedWork(
            lease_id=lease_id,
            worker_id=worker_id,
            task_id=task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            grant_id=grant_id,
            nonce=nonce,
            image_digest=queued.image_digest,
            config_digest=queued.config_digest,
            config=dict(queued.config),
            inputs=dict(queued.inputs),
            runtime="python-sandbox",
            expires_at=expires_at,
            resumed=resumed,
        )

    def _bind_result_authorization(
        self,
        fold: WorkerFold,
        *,
        worker_id: str,
        lease_id: str,
        claims: dict[str, str],
    ) -> tuple[LeaseRecord, GrantRecord]:
        if claims["workerId"] != worker_id:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        if claims["projectId"] != self.project_id:
            raise WorkerGrantError(
                "grant token project does not match",
                code="grant-project-mismatch",
            )
        grant = fold.grant(claims["grantId"])
        if grant is None:
            raise WorkerGrantError("grantId is not recorded", code="unknown-grant")
        lease = fold.lease(lease_id)
        if lease is None:
            raise WorkerCallError("leaseId is not recorded", code="unknown-lease")
        if lease.worker_id != worker_id:
            raise WorkerCallError(
                "complete worker does not own the lease",
                code="lease-worker-mismatch",
            )
        if (
            claims["taskId"] != lease.task_id
            or claims["runId"] != lease.run_id
            or claims["attemptId"] != lease.attempt_id
            or grant.task_id != lease.task_id
            or grant.run_id != lease.run_id
            or grant.attempt_id != lease.attempt_id
            or grant.worker_id != lease.worker_id
            or grant.grant_id != lease.grant_id
        ):
            raise WorkerGrantError(
                "grant token is not bound to this lease",
                code="grant-task-mismatch",
            )
        if grant.grant_event_id != claims["grantEventId"] or grant.nonce != claims["nonce"]:
            raise WorkerGrantError(
                "grant token does not match the recorded grant",
                code="grant-nonce-mismatch",
            )
        if (
            claims["imageDigest"] != grant.image_digest
            or claims["configDigest"] != grant.config_digest
        ):
            raise WorkerCallError(
                "grant token execution object does not match the recorded grant",
                code="execution-binding-mismatch",
            )
        return lease, grant

    def _require_live_result_grant(
        self,
        grant: GrantRecord,
        claims: dict[str, str],
        lease: LeaseRecord,
        *,
        now: datetime,
    ) -> None:
        if grant.revoked:
            raise WorkerGrantError("grantId is revoked", code="grant-revoked")
        if parse_rfc3339(claims["exp"]) <= now or parse_rfc3339(grant.expires_at) <= now:
            raise WorkerGrantError("grant token has expired", code="grant-expired")
        if parse_rfc3339(lease.expires_at) <= now:
            raise WorkerCallError("expired lease cannot complete", code="lease-expired")
        if lease.status in {"failed", "expired"}:
            raise WorkerCallError("terminal lease cannot be completed", code="lease-terminal")

    def _require_execution_match(
        self,
        grant: GrantRecord,
        queued: QueuedWork,
        claims: dict[str, str] | None,
    ) -> None:
        require_execution_digest(
            image_digest=queued.image_digest,
            config=queued.config,
            inputs=queued.inputs,
            config_digest=queued.config_digest,
        )
        if (
            queued.image_digest != grant.image_digest
            or queued.config_digest != grant.config_digest
            or queued.task_id != grant.task_id
            or queued.run_id != grant.run_id
            or queued.attempt_id != grant.attempt_id
        ):
            raise WorkerCallError(
                "queued execution object does not match the grant",
                code="execution-binding-mismatch",
            )
        if claims is None:
            return
        if (
            claims["imageDigest"] != grant.image_digest
            or claims["configDigest"] != grant.config_digest
            or claims["taskId"] != grant.task_id
            or claims["runId"] != grant.run_id
            or claims["attemptId"] != grant.attempt_id
            or claims["projectId"] != self.project_id
        ):
            raise WorkerGrantError(
                "grant token is not bound to this execution object",
                code="grant-task-mismatch",
            )

    def _require_live_grant(
        self, grant: GrantRecord, claims: dict[str, str], *, now: datetime
    ) -> None:
        if grant.revoked:
            raise WorkerGrantError("grantId is revoked", code="grant-revoked")
        if grant.worker_id != claims["workerId"]:
            raise WorkerGrantError(
                "grant token worker does not match",
                code="grant-worker-mismatch",
            )
        if claims["projectId"] != self.project_id:
            raise WorkerGrantError(
                "grant token project does not match",
                code="grant-project-mismatch",
            )
        if grant.grant_event_id != claims["grantEventId"]:
            raise WorkerGrantError("grant event id does not match", code="grant-event-mismatch")
        if grant.nonce != claims["nonce"]:
            raise WorkerGrantError("grant nonce does not match", code="grant-nonce-mismatch")
        if (
            grant.task_id != claims["taskId"]
            or grant.run_id != claims["runId"]
            or grant.attempt_id != claims["attemptId"]
        ):
            raise WorkerGrantError(
                "grant token is not bound to this execution object",
                code="grant-task-mismatch",
            )
        if (
            grant.image_digest != claims["imageDigest"]
            or grant.config_digest != claims["configDigest"]
        ):
            raise WorkerCallError(
                "grant token execution object does not match the recorded grant",
                code="execution-binding-mismatch",
            )
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
