"""One-command CPU OCI Worker loop. Fails closed without a live OCI runtime."""

from __future__ import annotations

import secrets
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
from llm_research_os.execution.models import DryRunStatus, PlannedTask
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.m2.prove import (
    M2CheckpointResult,
    _corpus_file,
    _load_run_events,
    _recorded_identity,
)
from llm_research_os.report import build_run_report, render_markdown
from llm_research_os.runs.models import RunStatus
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import TaskBlock
from llm_research_os.storage import EventStore
from llm_research_os.workers.binding import (
    OCI_BRICK_CAPABILITY,
    brick_execution_digest,
    json_object,
)
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.models import IMAGE_MEDIA_OCI_IMAGE, WORKER_RUNTIME_OCI_CONTAINER
from llm_research_os.workers.oci import discover_oci_backend, require_pinned_docker_image
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import reconcile_worker_run
from llm_research_os.workers.requests import (
    load_authorization_grant_request,
    load_worker_register_request,
)
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.tokens import HMAC_KEY_BYTES

_SPEC = "spec.yaml"
_BLOCK = "block.json"
_AUTHORIZATION_REQUEST = "authorization-request.json"
_AUTHORIZATION_EVENT = "authorization-event.json"
_WORKER = "worker.json"
_GRANT = "grant.json"
_RUN_EVENTS = "run-events.json"
_BRICK = "brick.py"


def prove_oci_loop(corpus: Path, database: Path, artifacts_root: Path) -> M2CheckpointResult:
    """Register an OCI Worker, execute one digest-pinned image, and rebuild the report.

    Plan and grant binding are checked before the engine. A valid corpus on a
    host without docker fails `oci-runtime-missing` and MUST NOT print success.
    """

    spec = load_spec(_corpus_file(corpus, _SPEC))
    if len(spec.workflows) != 1:
        raise M2CheckpointError(
            "checkpoint spec must contain exactly one workflow",
            code="plan-not-ready",
        )
    workflow_id = spec.workflows[0].id
    planned_task = spec.workflows[0].graph.nodes[0]
    if type(planned_task) is not TaskBlock:
        raise M2CheckpointError(
            "checkpoint spec must contain exactly one OCI python-brick task",
            code="plan-not-ready",
        )
    registry = build_registry([_corpus_file(corpus, _BLOCK)])
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
    if OCI_BRICK_CAPABILITY not in result.required_capabilities:
        raise M2CheckpointError(
            "checkpoint authorization does not grant execute.oci",
            code="authorization-capability-mismatch",
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
    if worker_request.runtime != WORKER_RUNTIME_OCI_CONTAINER:
        raise M2CheckpointError(
            "OCI checkpoint worker must advertise oci-container",
            code="runtime-mismatch",
        )
    hmac_key = secrets.token_bytes(HMAC_KEY_BYTES)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    artifact_store = LocalArtifactStore(artifacts_root)
    brick = artifact_store.put(_corpus_file(corpus, _BRICK))
    inner_config = json_object(planned_task.config.get("config", {}), field="config")
    inner_inputs = json_object(planned_task.config.get("inputs", {}), field="inputs")
    image = planned_task.config.get("imageDigest")
    if type(image) is not str:
        raise M2CheckpointError(
            "OCI checkpoint is missing imageDigest",
            code="execution-binding-mismatch",
        )
    config_digest = brick_execution_digest(
        image_digest=image,
        config=inner_config,
        inputs=inner_inputs,
        image_media_type=IMAGE_MEDIA_OCI_IMAGE,
        runtime=WORKER_RUNTIME_OCI_CONTAINER,
    )
    if inner_inputs.get("brickDigest") != brick.digest:
        raise M2CheckpointError(
            "CAS brick digest does not match the planned brickDigest",
            code="execution-binding-mismatch",
        )
    plan_nodes = [
        node
        for stage in (dry_run.plan.graph.stages if dry_run.plan is not None else ())
        for node in stage.nodes
    ]
    if len(plan_nodes) != 1 or type(plan_nodes[0]) is not PlannedTask:
        raise M2CheckpointError(
            "checkpoint spec did not produce a single planned task",
            code="plan-not-ready",
        )
    if plan_nodes[0].config_digest != config_digest:
        raise M2CheckpointError(
            "plan configDigest is not the authorized execution object",
            code="execution-binding-mismatch",
        )
    if grant_request.image_digest != image or grant_request.config_digest != config_digest:
        raise M2CheckpointError(
            "grant request is not bound to the authorized execution object",
            code="execution-binding-mismatch",
        )
    if grant_request.task_id != planned_task.id:
        raise M2CheckpointError(
            "grant taskId does not match the planned task",
            code="execution-binding-mismatch",
        )
    backend = discover_oci_backend()
    if backend is None:
        raise M2CheckpointError(
            "OCI runtime is not available on this host",
            code="oci-runtime-missing",
        )
    require_pinned_docker_image(backend, image)
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
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
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
            authorization_event_id=recorded.stored.event.id,
            authorization_sequence=recorded.stored.event.sequence,
            image_digest=image,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time=grant_request.event.time,
            workflow_id=workflow_id,
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
        if (
            grant_request.authorization_event_id != recorded.stored.event.id
            or grant_request.authorization_sequence != recorded.stored.event.sequence
        ):
            raise M2CheckpointError(
                "grant request does not cite the recorded authorization fact",
                code="authorization-binding-mismatch",
            )
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            image_digest=image,
            event_id="evt.work.queued.task.oci",
            config=inner_config,
            inputs=inner_inputs,
            time=grant_request.event.time,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
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
        snapshot = reconcile_worker_run(
            store,
            runtime,
            fold,
            project_id=spec.metadata.id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            report=dry_run,
            revision=spec.metadata.revision,
        )
        if snapshot.status is not RunStatus.COMPLETED:
            raise M2CheckpointError(
                "OCI loop did not reconcile Run and Attempt to completed",
                code="run-inconsistent",
            )
        types, ids = _recorded_identity(store)
        report_markdown = render_markdown(
            build_run_report(store, grant_request.run_id, project_id=spec.metadata.id)
        )
        if "work.completed" not in types:
            raise M2CheckpointError("OCI loop did not record work.completed", code="work-missing")
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
        image_digest=image,
        artifact_digest=artifact_digest,
        event_types=types,
        event_ids=ids,
        report_markdown=report_markdown,
    )
