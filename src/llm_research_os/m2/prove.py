"""One-command M2-0 CPU Worker loop. Does not spend GPU and does not close Issue #38."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization_documents import load_plan_authorization_request
from llm_research_os.execution.models import DryRunStatus
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.projections.replay import replay_events
from llm_research_os.report import build_run_report, render_markdown
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.storage import EventStore
from llm_research_os.storage.models import StoredEvent
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.requests import (
    load_authorization_grant_request,
    load_worker_register_request,
)
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.tokens import HMAC_KEY_BYTES

_SPEC = "spec.yaml"
_AUTHORIZATION_REQUEST = "authorization-request.json"
_AUTHORIZATION_EVENT = "authorization-event.json"
_WORKER = "worker.json"
_GRANT = "grant.json"
_RUN_EVENTS = "run-events.json"
_BRICK = "brick.py"


@dataclass(frozen=True, slots=True)
class M2CheckpointResult:
    project_id: str
    run_id: str
    worker_id: str
    image_digest: str
    artifact_digest: str
    event_types: tuple[str, ...]
    event_ids: tuple[str, ...]
    report_markdown: str


def prove_cpu_loop(corpus: Path, database: Path, artifacts_root: Path) -> M2CheckpointResult:
    """Register a loopback Worker, execute one CAS-pinned brick, and rebuild the report."""

    spec = load_spec(_corpus_file(corpus, _SPEC))
    if len(spec.workflows) != 1:
        raise M2CheckpointError(
            "checkpoint spec must contain exactly one workflow",
            code="plan-not-ready",
        )
    workflow_id = spec.workflows[0].id
    registry = build_registry([])
    dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
    if dry_run.status is not DryRunStatus.READY or dry_run.digests.plan is None:
        raise M2CheckpointError(
            "checkpoint spec did not produce a ready plan",
            code="plan-not-ready",
        )
    authorization_request = load_plan_authorization_request(
        _corpus_file(corpus, _AUTHORIZATION_REQUEST)
    )
    if (
        authorization_request.spec_digest != dry_run.digests.spec
        or authorization_request.registry_digest != dry_run.digests.registry
        or authorization_request.plan_digest != dry_run.digests.plan
    ):
        raise M2CheckpointError(
            "authorization request is not bound to the live plan",
            code="authorization-binding-mismatch",
        )
    policy = authorization_request.policy()
    result = authorize_plan(dry_run, policy)
    if result.authorized is not True:
        raise M2CheckpointError(
            "checkpoint authorization was not granted",
            code="authorization-denied",
        )
    worker_request = load_worker_register_request(_corpus_file(corpus, _WORKER))
    grant_request = load_authorization_grant_request(_corpus_file(corpus, _GRANT))
    identities = _load_run_events(_corpus_file(corpus, _RUN_EVENTS))
    if (
        worker_request.project_id != spec.metadata.id
        or grant_request.project_id != spec.metadata.id
    ):
        raise M2CheckpointError(
            "worker corpus projectId does not match the spec",
            code="project-mismatch",
        )
    hmac_key = secrets.token_bytes(HMAC_KEY_BYTES)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    artifact_store = LocalArtifactStore(artifacts_root)
    image = artifact_store.put(_corpus_file(corpus, _BRICK))
    server: LoopbackWorkerServer | None = None
    with EventStore(database) as store:
        if store.last_sequence() != 0:
            raise M2CheckpointError("checkpoint database must be empty", code="store-not-empty")
        event_document = snapshot_json_document(
            load_document(_corpus_file(corpus, _AUTHORIZATION_EVENT), reject_symlinks=True)
        )
        if type(event_document) is not dict:
            raise M2CheckpointError(
                "authorization event request must be a JSON object",
                code="authorization-binding-mismatch",
            )
        event_document["binding"] = {
            "specDigest": result.spec_digest,
            "registryDigest": result.registry_digest,
            "planDigest": result.plan_digest,
            "decisionDigest": result.decision_digest,
        }
        event_request = validate_plan_authorization_event_request_document(event_document)
        recorded = record_plan_authorization_event(store, dry_run, policy, event_request)
        plane = WorkerPlane(
            store,
            artifacts=artifact_store,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        )
        plane.register(
            worker_id=worker_request.worker_id,
            actor_id=worker_request.actor.id,
            event_id=worker_request.event.id,
            accelerators=worker_request.accelerators,
            time=worker_request.event.time,
        )
        plane.record_grant(
            grant_id=grant_request.grant_id,
            worker_id=grant_request.worker_id,
            task_id=grant_request.task_id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            nonce=grant_request.nonce,
            expires_at=grant_request.expires_at,
            actor_id=grant_request.actor.id,
            event_id=grant_request.event.id,
            time=grant_request.event.time,
        )
        runtime = WorkerRuntime(
            store,
            project_id=spec.metadata.id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            source=grant_request.source,
            subject=grant_request.run_id,
            stream_id=grant_request.run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        runtime.start(
            report=dry_run,
            authorization=result,
            citation={
                "eventId": recorded.stored.event.id,
                "sequence": recorded.stored.event.sequence,
            },
            revision=spec.metadata.revision,
        )
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            image_digest=image.digest,
            event_id="evt.work.queued.task.cpu",
            time=grant_request.event.time,
        )
        grant_token = plane.issue_token(grant_request.grant_id)
    server = LoopbackWorkerServer(
        database,
        artifact_store,
        hmac_key=hmac_key,
        project_id=spec.metadata.id,
        source=worker_request.source,
        experiment_revision=spec.metadata.revision,
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id=worker_request.worker_id,
            session=server.session_for(worker_request.worker_id),
            grant_token=grant_token,
        )
        completed = client.run_once(artifact_store)
        if completed is None:
            raise M2CheckpointError("worker poll returned no work", code="work-missing")
    finally:
        server.stop()
    with EventStore(database, require_existing=True) as store:
        fold = WorkerPlane(
            store,
            artifacts=artifact_store,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        ).rebuild()
        lease = fold.lease(f"lease.{grant_request.grant_id}")
        if lease is None or lease.artifact_digest is None:
            raise M2CheckpointError(
                "worker complete did not record an artifact",
                code="artifact-missing",
            )
        artifact_digest = lease.artifact_digest
        runtime = WorkerRuntime(
            store,
            project_id=spec.metadata.id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            source=grant_request.source,
            subject=grant_request.run_id,
            stream_id=grant_request.run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        runtime.succeed(report=dry_run, revision=spec.metadata.revision)
        types, ids = _recorded_identity(store)
        report_markdown = render_markdown(
            build_run_report(store, grant_request.run_id, project_id=spec.metadata.id)
        )
        if "work.completed" not in types:
            raise M2CheckpointError("CPU loop did not record work.completed", code="work-missing")
    with EventStore(database, require_existing=True) as store:
        replayed_types, replayed_ids = _recorded_identity(store)
        if replayed_types != types or replayed_ids != ids:
            raise M2CheckpointError(
                "reopened store did not replay the same events",
                code="replay-mismatch",
            )
        replayed_report = render_markdown(
            build_run_report(store, grant_request.run_id, project_id=spec.metadata.id)
        )
        if replayed_report != report_markdown:
            raise M2CheckpointError(
                "reopened store did not replay the same report",
                code="replay-mismatch",
            )
    return M2CheckpointResult(
        project_id=spec.metadata.id,
        run_id=grant_request.run_id,
        worker_id=worker_request.worker_id,
        image_digest=image.digest,
        artifact_digest=artifact_digest,
        event_types=types,
        event_ids=ids,
        report_markdown=report_markdown,
    )


def _load_run_events(path: Path) -> dict[str, tuple[str, str]]:
    document = snapshot_json_document(load_document(path, reject_symlinks=True))
    if type(document) is not dict or document.get("kind") != "WorkerRunEvents":
        raise M2CheckpointError(
            "run events document must be WorkerRunEvents",
            code="run-events-invalid",
        )
    events = document.get("events")
    if type(events) is not dict:
        raise M2CheckpointError("run events document is missing events", code="run-events-invalid")
    identities: dict[str, tuple[str, str]] = {}
    for event_type, identity in events.items():
        if type(event_type) is not str or type(identity) is not dict:
            raise M2CheckpointError("run events identity is invalid", code="run-events-invalid")
        event_id = identity.get("id")
        time = identity.get("time")
        if type(event_id) is not str or type(time) is not str:
            raise M2CheckpointError("run events identity is invalid", code="run-events-invalid")
        identities[event_type] = (event_id, time)
    return identities


def _corpus_file(corpus: Path, name: str) -> Path:
    path = corpus / name
    if path.is_symlink() or not path.is_file():
        raise M2CheckpointError(
            "checkpoint corpus is missing a required file",
            code="missing-corpus-file",
        )
    return path


def _recorded_identity(store: EventStore) -> tuple[tuple[str, ...], tuple[str, ...]]:
    stored = tuple(_stored(store))
    return (
        tuple(item.event.type for item in stored),
        tuple(item.event.id for item in stored),
    )


def _stored(store: EventStore) -> tuple[StoredEvent, ...]:
    return tuple(replay_events(store, freeze_high_water=False))
