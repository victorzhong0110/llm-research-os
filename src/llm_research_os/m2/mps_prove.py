"""One-command macOS/MPS Worker loop. Does not inherit OCI isolation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from llm_research_os.artifacts.models import ArtifactRecord
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
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
from llm_research_os.runs.cancellation import (
    request_cancellation,
    validate_run_cancellation_request_document,
)
from llm_research_os.runs.models import RunStatus
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec, TaskBlock
from llm_research_os.storage import EventStore
from llm_research_os.training.checkpoint import (
    MAX_MPS_CHECKPOINT_FILES,
    MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
    MAX_MPS_SNAPSHOT_FILE_BYTES,
    collect_output_artifacts,
    list_tree_files,
    tree_digest,
)
from llm_research_os.training.gpu_bind import resume_loads
from llm_research_os.training.mps_bind import bind_ms_swift_mps_command, plan_document_digest
from llm_research_os.training.requests import load_mac_mps_training_plan
from llm_research_os.workers.binding import (
    MPS_TRAINING_CAPABILITY,
    brick_execution_digest,
    json_object,
)
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.models import IMAGE_MEDIA_MPS_ENV, WORKER_RUNTIME_MACOS_MPS
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
_PLAN = "plan.json"
_ENVIRONMENT = "environment.json"
_AUTHORIZATION_EVENT = "authorization-event.json"
_WORKER = "worker.json"
_GRANT = "grant.json"
_RUN_EVENTS = "run-events.json"
_STUB = "stub-swift.py"


def prove_mps_loop(corpus: Path, database: Path, artifacts_root: Path) -> M2CheckpointResult:
    """Authorize, lease, and execute one Mac/MPS training object through a Worker."""

    spec_document = snapshot_json_document(
        load_document(_corpus_file(corpus, _SPEC), reject_symlinks=True)
    )
    if type(spec_document) is not dict:
        raise M2CheckpointError("MPS checkpoint spec must be an object", code="plan-not-ready")
    plan = load_mac_mps_training_plan(_corpus_file(corpus, _PLAN))
    registry = build_registry([_corpus_file(corpus, _BLOCK)])
    artifacts_root.mkdir(parents=True, exist_ok=True)
    artifact_store = LocalArtifactStore(artifacts_root)
    workspace = _prepare_workspace(corpus, database)
    interpreter = _prepare_interpreter(corpus, workspace)
    if _live_swift(interpreter):
        _archive_prior_output(workspace)
    environment = _store_environment(corpus, artifact_store, interpreter)
    plan_artifact = artifact_store.put(_corpus_file(corpus, _PLAN))
    _command, command_digest = bind_ms_swift_mps_command(plan)
    data_digest = tree_digest(
        list_tree_files(
            workspace / "data",
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_SNAPSHOT_FILE_BYTES,
        )
    )
    model_digest = tree_digest(
        list_tree_files(
            workspace / "model",
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_SNAPSHOT_FILE_BYTES,
        )
    )
    if data_digest is None or model_digest is None:
        raise M2CheckpointError("MPS workspace trees are empty", code="snapshot-path-invalid")
    _patch_spec(
        spec_document,
        image_digest=environment.digest,
        command_digest=command_digest,
        plan_digest=plan_document_digest(plan),
        plan_artifact_digest=plan_artifact.digest,
        dataset_digest=data_digest,
        model_digest=model_digest,
    )
    spec = ResearchSpec.model_validate(spec_document)
    if len(spec.workflows) != 1:
        raise M2CheckpointError(
            "checkpoint spec must contain exactly one workflow",
            code="plan-not-ready",
        )
    workflow_id = spec.workflows[0].id
    planned_task = spec.workflows[0].graph.nodes[0]
    if type(planned_task) is not TaskBlock:
        raise M2CheckpointError(
            "checkpoint spec must contain exactly one MPS training task",
            code="plan-not-ready",
        )
    dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
    if dry_run.status is not DryRunStatus.READY or dry_run.digests.plan is None:
        raise M2CheckpointError(
            "checkpoint spec did not produce a ready plan",
            code="plan-not-ready",
        )
    policy = PlanAuthorizationPolicy(
        spec_digest=dry_run.digests.spec,
        registry_digest=dry_run.digests.registry,
        plan_digest=dry_run.digests.plan,
        granted_capabilities=(MPS_TRAINING_CAPABILITY,),
    )
    result = authorize_plan(dry_run, policy)
    if result.authorized is not True:
        raise M2CheckpointError(
            "checkpoint authorization was not granted",
            code="authorization-denied",
        )
    if MPS_TRAINING_CAPABILITY not in result.required_capabilities:
        raise M2CheckpointError(
            "checkpoint authorization does not grant execute.mps",
            code="authorization-capability-mismatch",
        )
    worker_request = load_worker_register_request(_corpus_file(corpus, _WORKER))
    grant_request = load_authorization_grant_request(_corpus_file(corpus, _GRANT))
    identities = _load_run_events(_corpus_file(corpus, _RUN_EVENTS))
    if worker_request.runtime != WORKER_RUNTIME_MACOS_MPS:
        raise M2CheckpointError(
            "MPS checkpoint worker must advertise macos-mps-process",
            code="runtime-mismatch",
        )
    inner_config = json_object(planned_task.config.get("config", {}), field="config")
    inner_inputs = json_object(planned_task.config.get("inputs", {}), field="inputs")
    image = planned_task.config.get("imageDigest")
    if type(image) is not str:
        raise M2CheckpointError(
            "MPS checkpoint is missing imageDigest",
            code="execution-binding-mismatch",
        )
    config_digest = brick_execution_digest(
        image_digest=image,
        config=inner_config,
        inputs=inner_inputs,
        image_media_type=IMAGE_MEDIA_MPS_ENV,
        runtime=WORKER_RUNTIME_MACOS_MPS,
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
    hmac_key = secrets.token_bytes(HMAC_KEY_BYTES)
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
            runtime=WORKER_RUNTIME_MACOS_MPS,
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
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            image_digest=image,
            event_id="evt.work.queued.task.mps",
            config=inner_config,
            inputs=inner_inputs,
            time=grant_request.event.time,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
            required_accelerators=("mps",),
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
    followups: dict[str, Any] | None = None
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id=worker_request.worker_id,
            session=server.session_for(worker_request.worker_id),
            grant_token=grant_token,
            identity_dir=database.parent / f"{database.stem}-identities",
            timeout_seconds=1800,
            mps_data_dir=workspace / "data",
            mps_model_dir=workspace / "model",
            mps_output_dir=workspace / "output",
            mps_interpreter=interpreter,
        )
        completed = client.run_once(artifact_store)
        if completed is None:
            raise M2CheckpointError("worker poll returned no work", code="work-missing")
        if _live_swift(interpreter):
            followups = _run_live_followups(
                corpus=corpus,
                database=database,
                artifacts=artifact_store,
                hmac_key=hmac_key,
                spec=spec,
                spec_document=spec_document,
                registry=registry,
                dry_run=dry_run,
                authorization=result,
                recorded_event_id=recorded.stored.event.id,
                recorded_sequence=recorded.stored.event.sequence,
                worker_request=worker_request,
                grant_request=grant_request,
                image=image,
                inner_config=inner_config,
                inner_inputs=inner_inputs,
                workflow_id=workflow_id,
                plan=plan,
                workspace=workspace,
                interpreter=interpreter,
                server=server,
                identity_dir=client.identity_dir,
            )
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
                "MPS loop did not reconcile Run and Attempt to completed",
                code="run-inconsistent",
            )
        types, ids = _recorded_identity(store)
        report_markdown = render_markdown(
            build_run_report(store, grant_request.run_id, project_id=spec.metadata.id)
        )
        if "work.completed" not in types:
            raise M2CheckpointError("MPS loop did not record work.completed", code="work-missing")
        if followups is not None:
            _write_live_evidence(
                corpus=corpus,
                artifacts=artifact_store,
                workspace=workspace,
                environment_digest=environment.digest,
                plan_digest=plan_document_digest(plan),
                plan_artifact_digest=plan_artifact.digest,
                dataset_digest=data_digest,
                model_digest=model_digest,
                train_run_id=grant_request.run_id,
                train_artifact_digest=artifact_digest,
                event_types=types,
                event_ids=ids,
                report_markdown=report_markdown,
                followups=followups,
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


def _store_environment(
    corpus: Path,
    artifacts: LocalArtifactStore,
    interpreter: Path,
) -> ArtifactRecord:
    python = os.environ.get("RESEARCHOS_MPS_PYTHON")
    if type(python) is str and python != "":
        from llm_research_os.workers.mps import live_environment_document

        payload = json.dumps(
            live_environment_document(interpreter),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return artifacts.put_bytes(payload)
    return artifacts.put(_corpus_file(corpus, _ENVIRONMENT))


def _patch_spec(
    document: dict[str, object],
    *,
    image_digest: str,
    command_digest: str,
    plan_digest: str,
    plan_artifact_digest: str,
    dataset_digest: str,
    model_digest: str,
) -> None:
    workflows = document.get("workflows")
    if type(workflows) is not list or not workflows or type(workflows[0]) is not dict:
        raise M2CheckpointError("checkpoint spec is missing workflows", code="plan-not-ready")
    graph = workflows[0].get("graph")
    if type(graph) is not dict:
        raise M2CheckpointError("checkpoint spec is missing a graph", code="plan-not-ready")
    nodes = graph.get("nodes")
    if type(nodes) is not list or not nodes or type(nodes[0]) is not dict:
        raise M2CheckpointError("checkpoint spec is missing a task", code="plan-not-ready")
    config = nodes[0].get("config")
    if type(config) is not dict:
        raise M2CheckpointError("checkpoint spec is missing task config", code="plan-not-ready")
    inner = config.get("config")
    inputs = config.get("inputs")
    if type(inner) is not dict or type(inputs) is not dict:
        raise M2CheckpointError(
            "checkpoint spec is missing execution object",
            code="plan-not-ready",
        )
    config["imageDigest"] = image_digest
    inner["commandDigest"] = command_digest
    inputs["planDigest"] = plan_digest
    inputs["planArtifactDigest"] = plan_artifact_digest
    inputs["datasetDigest"] = dataset_digest
    inputs["modelDigest"] = model_digest


def _prepare_workspace(corpus: Path, database: Path) -> Path:
    configured = os.environ.get("RESEARCHOS_MPS_WORK")
    if type(configured) is str and configured != "":
        workspace = Path(configured)
    else:
        workspace = database.parent / f"{database.stem}-mps-work"
    (workspace / "output").mkdir(parents=True, exist_ok=True)
    _copy_tree(corpus / "model", workspace / "model")
    _copy_tree(corpus / "data", workspace / "data")
    return workspace


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    shutil.copytree(source, destination)


def _prepare_interpreter(corpus: Path, workspace: Path) -> Path:
    configured = os.environ.get("RESEARCHOS_MPS_PYTHON")
    if type(configured) is str and configured != "":
        python = Path(configured)
        sibling = python.parent / "swift"
        if sibling.is_file():
            return sibling
        return python
    binary = workspace / "bin" / "swift"
    binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_corpus_file(corpus, _STUB), binary)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    (binary.parent / ".mps-stub").write_text("1\n", encoding="utf-8")
    return binary


def _live_swift(interpreter: Path) -> bool:
    configured = os.environ.get("RESEARCHOS_MPS_PYTHON")
    if type(configured) is not str or configured == "":
        return False
    return not (interpreter.parent / ".mps-stub").exists()


def _archive_prior_output(workspace: Path) -> None:
    output = workspace / "output"
    if not output.exists():
        output.mkdir(parents=True)
        return
    entries = [path for path in output.iterdir() if path.name != ".DS_Store"]
    if not entries:
        return
    archive = workspace / "output.direct-gate"
    if archive.exists():
        shutil.rmtree(archive)
    output.rename(archive)
    output.mkdir(parents=True)


def _phase_identities(suffix: str) -> dict[str, tuple[str, str]]:
    stamp = "2026-09-08T00:00:00Z"
    kinds = (
        "run.queued",
        "run.started",
        "attempt.queued",
        "attempt.started",
        "attempt.succeeded",
        "run.completed",
        "attempt.unknown",
        "attempt.lost",
        "attempt.cancelled",
        "run.cancelled",
        "attempt.failed",
        "run.failed",
        "attempt.recovered",
    )
    return {kind: (f"evt.{kind}.{suffix}", stamp) for kind in kinds}


def _run_live_followups(
    *,
    corpus: Path,
    database: Path,
    artifacts: LocalArtifactStore,
    hmac_key: bytes,
    spec: ResearchSpec,
    spec_document: dict[str, Any],
    registry: Any,
    dry_run: Any,
    authorization: Any,
    recorded_event_id: str,
    recorded_sequence: str,
    worker_request: Any,
    grant_request: Any,
    image: str,
    inner_config: dict[str, object],
    inner_inputs: dict[str, object],
    workflow_id: str,
    plan: Any,
    workspace: Path,
    interpreter: Path,
    server: LoopbackWorkerServer,
    identity_dir: Path | None,
) -> dict[str, Any]:
    checkpoint = workspace / "output" / "checkpoint-10"
    before = _checkpoint_facts(checkpoint)
    if before.get("globalStep") != 10:
        raise M2CheckpointError(
            "live train did not save checkpoint-10 with global_step 10",
            code="mps-checkpoint-missing",
        )
    cancel = _run_live_cancel(
        database=database,
        artifacts=artifacts,
        hmac_key=hmac_key,
        spec=spec,
        registry=registry,
        dry_run=dry_run,
        authorization=authorization,
        recorded_event_id=recorded_event_id,
        recorded_sequence=recorded_sequence,
        worker_request=worker_request,
        grant_request=grant_request,
        image=image,
        inner_config=inner_config,
        inner_inputs=inner_inputs,
        workflow_id=workflow_id,
        workspace=workspace,
        interpreter=interpreter,
        server=server,
        identity_dir=identity_dir,
    )
    resume = _run_live_resume(
        corpus=corpus,
        database=database,
        artifacts=artifacts,
        hmac_key=hmac_key,
        spec_document=spec_document,
        registry=registry,
        worker_request=worker_request,
        grant_request=grant_request,
        image=image,
        inner_config=inner_config,
        inner_inputs=inner_inputs,
        workflow_id=workflow_id,
        plan=plan,
        workspace=workspace,
        interpreter=interpreter,
        server=server,
        identity_dir=identity_dir,
        before=before,
    )
    return {"cancel": cancel, "resume": resume, "checkpoint10BeforeResume": before}


def _run_live_cancel(
    *,
    database: Path,
    artifacts: LocalArtifactStore,
    hmac_key: bytes,
    spec: ResearchSpec,
    registry: Any,
    dry_run: Any,
    authorization: Any,
    recorded_event_id: str,
    recorded_sequence: str,
    worker_request: Any,
    grant_request: Any,
    image: str,
    inner_config: dict[str, object],
    inner_inputs: dict[str, object],
    workflow_id: str,
    workspace: Path,
    interpreter: Path,
    server: LoopbackWorkerServer,
    identity_dir: Path | None,
) -> dict[str, Any]:
    run_id = "run.worker.mps.cancel"
    attempt_id = "attempt.worker.mps.cancel.1"
    grant_id = "grant.mps.cancel"
    identities = _phase_identities("mps-cancel")
    config_digest = brick_execution_digest(
        image_digest=image,
        config=inner_config,
        inputs=inner_inputs,
        image_media_type=IMAGE_MEDIA_MPS_ENV,
        runtime=WORKER_RUNTIME_MACOS_MPS,
    )
    with EventStore(database, require_existing=True) as store:
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        )
        runtime = WorkerRuntime(
            store,
            project_id=spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            source=grant_request.source,
            subject=run_id,
            stream_id=run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        runtime.start(
            report=dry_run,
            authorization=authorization,
            citation={"eventId": recorded_event_id, "sequence": recorded_sequence},
            revision=spec.metadata.revision,
        )
        plane.record_grant(
            grant_id=grant_id,
            worker_id=worker_request.worker_id,
            task_id=grant_request.task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            nonce="nonce.mps.cancel",
            expires_at=grant_request.expires_at,
            actor_id=grant_request.actor.id,
            event_id="evt.grant.recorded.mps.cancel",
            authorization_event_id=recorded_event_id,
            authorization_sequence=recorded_sequence,
            image_digest=image,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time=grant_request.event.time,
            workflow_id=workflow_id,
        )
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            image_digest=image,
            event_id="evt.work.queued.task.mps.cancel",
            config=inner_config,
            inputs=inner_inputs,
            time=grant_request.event.time,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
            required_accelerators=("mps",),
        )
        token = plane.issue_token(grant_id)
    box: dict[str, Any] = {}

    def _execute() -> None:
        client = WorkerClient(
            base_url=server.base_url,
            worker_id=worker_request.worker_id,
            session=server.session_for(worker_request.worker_id),
            grant_token=token,
            identity_dir=identity_dir,
            timeout_seconds=1800,
            mps_data_dir=workspace / "data",
            mps_model_dir=workspace / "model",
            mps_output_dir=workspace / "output",
            mps_interpreter=interpreter,
        )
        try:
            box["completed"] = client.run_once(artifacts)
        except WorkerError as exc:
            box["error"] = exc

    thread = threading.Thread(target=_execute, name="researchos-mps-cancel", daemon=True)
    thread.start()
    _wait_for_identity(identity_dir, 90.0)
    with EventStore(database, require_existing=True) as store:
        request_cancellation(
            store,
            validate_run_cancellation_request_document(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "RunCancellationRequest",
                    "projectId": spec.metadata.id,
                    "experimentRevision": spec.metadata.revision,
                    "runId": run_id,
                    "target": {"kind": "run"},
                    "reasonCode": "researcher.requested",
                    "source": grant_request.source,
                    "subject": run_id,
                    "streamid": run_id,
                    "actor": {"id": grant_request.actor.id},
                    "event": {
                        "id": "evt.run.cancel.requested.mps",
                        "time": "2026-09-08T00:00:00Z",
                    },
                    "evidenceRefs": [],
                }
            ),
        )
    thread.join(timeout=1800)
    if thread.is_alive():
        raise M2CheckpointError("cancel thread did not stop", code="cancel-unobserved")
    error = box.get("error")
    if type(error) is not WorkerError or error.code != "cancel-observed":
        raise M2CheckpointError("live cancel was not observed", code="cancel-unobserved")
    with EventStore(database, require_existing=True) as store:
        fold = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        ).rebuild()
        runtime = WorkerRuntime(
            store,
            project_id=spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            source=grant_request.source,
            subject=run_id,
            stream_id=run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            fold,
            project_id=spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            report=dry_run,
            revision=spec.metadata.revision,
        )
        if snapshot.status is not RunStatus.CANCELLED:
            raise M2CheckpointError(
                "live cancel did not reconcile to cancelled",
                code="cancel-unobserved",
            )
        types, ids = _recorded_identity(store)
    return {
        "runId": run_id,
        "observed": error.code == "cancel-observed",
        "reasonCode": error.code,
        "status": snapshot.status.value,
        "cancelRequestEventId": "evt.run.cancel.requested.mps",
        "eventTypes": list(types),
        "eventIds": list(ids),
    }


def _run_live_resume(
    *,
    corpus: Path,
    database: Path,
    artifacts: LocalArtifactStore,
    hmac_key: bytes,
    spec_document: dict[str, Any],
    registry: Any,
    worker_request: Any,
    grant_request: Any,
    image: str,
    inner_config: dict[str, object],
    inner_inputs: dict[str, object],
    workflow_id: str,
    plan: Any,
    workspace: Path,
    interpreter: Path,
    server: LoopbackWorkerServer,
    identity_dir: Path | None,
    before: dict[str, Any],
) -> dict[str, Any]:
    argv, command_digest = bind_ms_swift_mps_command(
        plan,
        resume_mode="full-checkpoint",
        checkpoint_path="output/checkpoint-10",
    )
    if "--resume_from_checkpoint" not in argv:
        raise M2CheckpointError("full resume argv is missing", code="resume-overlay-conflict")
    resume_config = dict(inner_config)
    resume_config["commandDigest"] = command_digest
    resume_config["resume"] = "full-checkpoint"
    resume_config["checkpoint"] = "output/checkpoint-10"
    resume_document = snapshot_json_document(spec_document)
    if type(resume_document) is not dict:
        raise M2CheckpointError("resume spec must be an object", code="plan-not-ready")
    _patch_resume_config(resume_document, command_digest=command_digest)
    resume_spec = ResearchSpec.model_validate(resume_document)
    dry_run = TrustedKernel(registry).dry_run(resume_spec, workflow_id=workflow_id)
    if dry_run.status is not DryRunStatus.READY or dry_run.digests.plan is None:
        raise M2CheckpointError("resume spec did not produce a ready plan", code="plan-not-ready")
    policy = PlanAuthorizationPolicy(
        spec_digest=dry_run.digests.spec,
        registry_digest=dry_run.digests.registry,
        plan_digest=dry_run.digests.plan,
        granted_capabilities=(MPS_TRAINING_CAPABILITY,),
    )
    authorization = authorize_plan(dry_run, policy)
    if authorization.authorized is not True:
        raise M2CheckpointError("resume authorization was not granted", code="authorization-denied")
    event_document = snapshot_json_document(
        load_document(_corpus_file(corpus, _AUTHORIZATION_EVENT), reject_symlinks=True)
    )
    if type(event_document) is not dict:
        raise M2CheckpointError(
            "authorization event request must be a JSON object",
            code="authorization-binding-mismatch",
        )
    event_document["binding"] = {
        "specDigest": authorization.spec_digest,
        "registryDigest": authorization.registry_digest,
        "planDigest": authorization.plan_digest,
        "decisionDigest": authorization.decision_digest,
    }
    event = event_document.get("event")
    if type(event) is not dict:
        raise M2CheckpointError(
            "authorization event identity is invalid",
            code="authorization-binding-mismatch",
        )
    event["id"] = "evt.authorization.example-minimal.mps-resume"
    event_request = validate_plan_authorization_event_request_document(event_document)
    run_id = "run.worker.mps.resume"
    attempt_id = "attempt.worker.mps.resume.1"
    grant_id = "grant.mps.resume"
    identities = _phase_identities("mps-resume")
    config_digest = brick_execution_digest(
        image_digest=image,
        config=resume_config,
        inputs=inner_inputs,
        image_media_type=IMAGE_MEDIA_MPS_ENV,
        runtime=WORKER_RUNTIME_MACOS_MPS,
    )
    plan_nodes = [
        node
        for stage in (dry_run.plan.graph.stages if dry_run.plan is not None else ())
        for node in stage.nodes
    ]
    if len(plan_nodes) != 1 or type(plan_nodes[0]) is not PlannedTask:
        raise M2CheckpointError("resume plan is not a single task", code="plan-not-ready")
    if plan_nodes[0].config_digest != config_digest:
        raise M2CheckpointError(
            "resume plan configDigest is not the authorized execution object",
            code="execution-binding-mismatch",
        )
    with EventStore(database, require_existing=True) as store:
        recorded = record_plan_authorization_event(store, dry_run, policy, event_request)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=resume_spec.metadata.id,
            source=worker_request.source,
            experiment_revision=resume_spec.metadata.revision,
        )
        runtime = WorkerRuntime(
            store,
            project_id=resume_spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            source=grant_request.source,
            subject=run_id,
            stream_id=run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        runtime.start(
            report=dry_run,
            authorization=authorization,
            citation={
                "eventId": recorded.stored.event.id,
                "sequence": recorded.stored.event.sequence,
            },
            revision=resume_spec.metadata.revision,
        )
        plane.record_grant(
            grant_id=grant_id,
            worker_id=worker_request.worker_id,
            task_id=grant_request.task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            nonce="nonce.mps.resume",
            expires_at=grant_request.expires_at,
            actor_id=grant_request.actor.id,
            event_id="evt.grant.recorded.mps.resume",
            authorization_event_id=recorded.stored.event.id,
            authorization_sequence=recorded.stored.event.sequence,
            image_digest=image,
            config_digest=config_digest,
            spec=resume_spec,
            registry=registry,
            time=grant_request.event.time,
            workflow_id=workflow_id,
        )
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            image_digest=image,
            event_id="evt.work.queued.task.mps.resume",
            config=resume_config,
            inputs=inner_inputs,
            time=grant_request.event.time,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
            required_accelerators=("mps",),
        )
        token = plane.issue_token(grant_id)
    client = WorkerClient(
        base_url=server.base_url,
        worker_id=worker_request.worker_id,
        session=server.session_for(worker_request.worker_id),
        grant_token=token,
        identity_dir=identity_dir,
        timeout_seconds=1800,
        mps_data_dir=workspace / "data",
        mps_model_dir=workspace / "model",
        mps_output_dir=workspace / "output",
        mps_interpreter=interpreter,
    )
    completed = client.run_once(artifacts)
    if completed is None:
        raise M2CheckpointError("resume worker poll returned no work", code="work-missing")
    with EventStore(database, require_existing=True) as store:
        fold = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=resume_spec.metadata.id,
            source=worker_request.source,
            experiment_revision=resume_spec.metadata.revision,
        ).rebuild()
        lease = fold.lease(f"lease.{grant_id}")
        if lease is None or lease.artifact_digest is None:
            raise M2CheckpointError("resume did not record an artifact", code="artifact-missing")
        runtime = WorkerRuntime(
            store,
            project_id=resume_spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            source=grant_request.source,
            subject=run_id,
            stream_id=run_id,
            actor_id=grant_request.actor.id,
            events=identities,
        )
        snapshot = reconcile_worker_run(
            store,
            runtime,
            fold,
            project_id=resume_spec.metadata.id,
            run_id=run_id,
            attempt_id=attempt_id,
            report=dry_run,
            revision=resume_spec.metadata.revision,
        )
        if snapshot.status is not RunStatus.COMPLETED:
            raise M2CheckpointError("resume run did not complete", code="run-inconsistent")
        report = _read_json_artifact(artifacts, lease.artifact_digest)
    after = _checkpoint_facts(workspace / "output" / "checkpoint-20")
    if after.get("globalStep") != 20:
        raise M2CheckpointError(
            "full resume did not continue to global_step 20",
            code="mps-checkpoint-missing",
        )
    if before.get("optimizerDigest") is None or after.get("optimizerDigest") is None:
        raise M2CheckpointError(
            "full resume checkpoint is missing optimizer state",
            code="mps-checkpoint-missing",
        )
    if after.get("scheduler") is not True or after.get("rng") is not True:
        raise M2CheckpointError(
            "full resume checkpoint is missing scheduler or RNG",
            code="mps-checkpoint-missing",
        )
    return {
        "runId": run_id,
        "mode": "full-checkpoint",
        "declaredLoads": list(resume_loads("full-checkpoint")),
        "argvFlags": ["--resume_from_checkpoint", "output/checkpoint-10"],
        "fromStep": 10,
        "toStep": after.get("globalStep"),
        "commandDigest": command_digest,
        "artifactDigest": lease.artifact_digest,
        "report": report,
        "observed": {
            "globalStep": {
                "before": before.get("globalStep"),
                "after": after.get("globalStep"),
                "source": "trainer_state.json global_step",
                "continuous": before.get("globalStep") == 10 and after.get("globalStep") == 20,
            },
            "optimizer": _restore_observation(before, after, "optimizerDigest"),
            "scheduler": _restore_observation(before, after, "schedulerDigest"),
            "rng": _restore_observation(before, after, "rngDigest"),
            "adapter": _restore_observation(before, after, "adapterDigest"),
        },
        "optimizerContinued": before.get("optimizerDigest") != after.get("optimizerDigest"),
        "adapterOnly": False,
    }


def _patch_resume_config(document: dict[str, Any], *, command_digest: str) -> None:
    workflows = document.get("workflows")
    if type(workflows) is not list or not workflows or type(workflows[0]) is not dict:
        raise M2CheckpointError("resume spec is missing workflows", code="plan-not-ready")
    graph = workflows[0].get("graph")
    if type(graph) is not dict:
        raise M2CheckpointError("resume spec is missing a graph", code="plan-not-ready")
    nodes = graph.get("nodes")
    if type(nodes) is not list or not nodes or type(nodes[0]) is not dict:
        raise M2CheckpointError("resume spec is missing a task", code="plan-not-ready")
    config = nodes[0].get("config")
    if type(config) is not dict:
        raise M2CheckpointError("resume spec is missing task config", code="plan-not-ready")
    inner = config.get("config")
    if type(inner) is not dict:
        raise M2CheckpointError("resume spec is missing execution object", code="plan-not-ready")
    inner["commandDigest"] = command_digest
    inner["resume"] = "full-checkpoint"
    inner["checkpoint"] = "output/checkpoint-10"


def _wait_for_identity(identity_dir: Path | None, timeout_seconds: float) -> None:
    if identity_dir is None:
        time.sleep(min(5.0, timeout_seconds))
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if identity_dir.is_dir() and any(identity_dir.iterdir()):
            time.sleep(0.5)
            return
        time.sleep(0.1)


def _checkpoint_facts(path: Path) -> dict[str, Any]:
    public = f"output/{path.name}" if path.name.startswith("checkpoint-") else path.name
    if not path.is_dir():
        return {"path": public, "present": False}
    state_path = path / "trainer_state.json"
    global_step: int | None = None
    if state_path.is_file():
        try:
            document = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = None
        if type(document) is dict and type(document.get("global_step")) is int:
            global_step = document["global_step"]
    optimizer = _named_digest(path, ("optimizer.pt", "optimizer.bin"))
    scheduler = _named_digest(path, ("scheduler.pt", "scheduler.bin"))
    rng = _named_digest(path, ("rng_state.pth", "rng_state_0.pth", "rng_state.bin"))
    adapter = _named_digest(path, ("adapter_model.safetensors", "adapter_model.bin"))
    return {
        "path": public,
        "present": True,
        "globalStep": global_step,
        "optimizer": optimizer is not None,
        "optimizerDigest": optimizer,
        "scheduler": scheduler is not None,
        "schedulerDigest": scheduler,
        "rng": rng is not None,
        "rngDigest": rng,
        "adapter": adapter is not None,
        "adapterDigest": adapter,
    }


def _named_digest(path: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        candidate = path / name
        if candidate.is_file():
            return "sha256:" + _sha256_file(candidate)
    return None


def _restore_observation(
    before: Mapping[str, Any], after: Mapping[str, Any], key: str
) -> dict[str, Any]:
    before_digest = before.get(key)
    after_digest = after.get(key)
    present = type(before_digest) is str and type(after_digest) is str
    changed = present and before_digest != after_digest
    if changed:
        status = "bytes-changed"
    elif present:
        status = "file-present-digest-unchanged"
    else:
        status = "missing"
    return {
        "digestBefore": before_digest,
        "digestAfter": after_digest,
        "digestChanged": changed,
        "status": status,
    }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_json_artifact(artifacts: LocalArtifactStore, digest: str) -> dict[str, Any]:
    with artifacts.open(digest) as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    if type(payload) is not dict:
        raise M2CheckpointError(
            "training report artifact is not an object",
            code="artifact-missing",
        )
    return payload


def _host_inventory() -> dict[str, Any]:
    chip = platform.machine()
    try:
        probed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            capture_output=True,
            timeout=2,
        )
        if probed.returncode == 0:
            text = probed.stdout.decode("utf-8", errors="replace").strip()
            if text != "":
                chip = text
    except (OSError, subprocess.TimeoutExpired):
        pass
    mem_bytes = None
    try:
        probed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.memsize"],
            check=False,
            capture_output=True,
            timeout=2,
        )
        if probed.returncode == 0:
            mem_bytes = int(probed.stdout.decode("utf-8").strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        mem_bytes = None
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "chip": chip,
        "python": platform.python_version(),
        "memBytes": mem_bytes,
    }


def _write_live_evidence(
    *,
    corpus: Path,
    artifacts: LocalArtifactStore,
    workspace: Path,
    environment_digest: str,
    plan_digest: str,
    plan_artifact_digest: str,
    dataset_digest: str,
    model_digest: str,
    train_run_id: str,
    train_artifact_digest: str,
    event_types: tuple[str, ...],
    event_ids: tuple[str, ...],
    report_markdown: str,
    followups: dict[str, Any],
) -> None:
    train_report = _read_json_artifact(artifacts, train_artifact_digest)
    environment = _read_json_artifact(artifacts, environment_digest)
    collect = collect_output_artifacts(
        workspace / "output",
        artifacts,
        max_files=MAX_MPS_CHECKPOINT_FILES,
        max_file_bytes=MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
        max_upload_bytes=MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
    )
    verified = []
    for item in collect.files:
        artifacts.verify(item.digest)
        verified.append({"path": item.path, "digest": item.digest, "size": item.size})
    probe_device = train_report.get("device")
    cpu_fallback = train_report.get("cpuFallback") is True
    payload = {
        "kind": "MacMpsLiveEvidence",
        "apiVersion": "researchos.dev/v0alpha1",
        "status": "live",
        "effectNotAcceptance": True,
        "cpuFallback": cpu_fallback,
        "cpuFallbackBasis": {
            "probeDevice": probe_device,
            "reportCpuFallback": train_report.get("cpuFallback"),
            "rule": "Worker probe must return device mps; any other device is mps-unavailable",
            "mpsFallbackOps": train_report.get("mpsFallbackOps"),
            "sourceArtifactDigest": train_artifact_digest,
        },
        "isolation": {
            "runtime": "macos-mps-process",
            "capability": "execute.mps",
            "declared": "process-group",
            "ociIsolationClaimed": False,
            "nativeProcessRuntime": False,
        },
        "host": _host_inventory(),
        "environmentDigest": environment_digest,
        "environment": environment,
        "planDigest": plan_digest,
        "planArtifactDigest": plan_artifact_digest,
        "datasetDigest": dataset_digest,
        "modelDigest": model_digest,
        "memory": {
            "workerPeakRssBytes": train_report.get("peakRssBytes"),
            "workerPeakRssSource": "ps -o rss= sampled while the Worker process ran",
            "workerPeakRssIncludesMpsAllocations": False,
            "mpsAllocatedBytes": None,
            "mpsAllocatedStatus": "unmeasured",
        },
        "train": {
            "runId": train_run_id,
            "artifactDigest": train_artifact_digest,
            "report": train_report,
            "eventTypes": list(event_types),
            "eventIds": list(event_ids),
        },
        "cancel": followups.get("cancel"),
        "resume": followups.get("resume"),
        "checkpoint10BeforeResume": followups.get("checkpoint10BeforeResume"),
        "collect": {
            "profile": "mps",
            "status": collect.status,
            "bytesUploaded": collect.bytes_uploaded,
            "manifestDigest": collect.manifest_digest,
            "files": verified,
        },
        "reportTraceable": "work.completed" in event_types and train_run_id in report_markdown,
        "cudaOci": "pending-live",
        "twoHost": "pending-live",
        "issue38": "open",
    }
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    (corpus / "live-evidence.json").write_text(encoded, encoding="utf-8")
    (workspace / "live-evidence.json").write_text(encoded, encoding="utf-8")
