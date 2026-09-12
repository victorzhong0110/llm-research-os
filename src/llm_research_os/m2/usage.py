"""Worker/RunControl usage evidence. Not EventStore.append fill, not GPU."""

from __future__ import annotations

import json
import os
import resource
import secrets
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.requests import validate_budget_limit_request
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.execution.authorization_documents import load_plan_authorization_request
from llm_research_os.execution.models import DryRunReport
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.m2.oci_prove import prove_oci_loop
from llm_research_os.report.fold import build_run_report
from llm_research_os.report.render import render_markdown
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.requests import validate_proposal_submit_request
from llm_research_os.runs.cancellation import (
    request_cancellation,
    validate_run_cancellation_request_document,
)
from llm_research_os.runs.models import RunStatus
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec, TaskBlock
from llm_research_os.storage.errors import EventSequenceConflictError
from llm_research_os.storage.store import EventStore
from llm_research_os.workers.binding import brick_execution_digest, json_object
from llm_research_os.workers.credentials import (
    WorkerCredential,
    write_hmac_key,
    write_worker_credential,
)
from llm_research_os.workers.errors import WorkerError, WorkerGrantError, WorkerSandboxError
from llm_research_os.workers.oci import oci_integration_required
from llm_research_os.workers.plane import ClaimedWork, WorkerPlane
from llm_research_os.workers.recovery import reconcile_worker_run
from llm_research_os.workers.requests import (
    load_authorization_grant_request,
    load_worker_register_request,
)
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.sandbox import execute_python_brick
from llm_research_os.workers.tls import pem_fingerprint
from llm_research_os.workers.tokens import HMAC_KEY_BYTES, issue_grant_token, issue_worker_session

_REPO = Path(__file__).resolve().parents[3]
_CPU_CORPUS = _REPO / "examples" / "m2-checkpoint"
_OCI_CORPUS = _REPO / "examples" / "m2-oci-checkpoint"
_PROPOSAL = _REPO / "examples" / "research-decisions" / "valid" / "proposal-submit.json"
_BUDGET = _REPO / "examples" / "budget-limit-requests" / "valid" / "minimal.json"
_SOURCE = "https://researchos.dev/projects/example-minimal"
_CONCURRENT_WORKERS = 4
_CAS_RETRIES = 32
_REPORT_LABELS = (
    "Spec digest",
    "Registry digest",
    "Plan digest",
    "Worker runtime",
    "Image digest",
    "Config digest",
    "Output artifact",
)


@dataclass(frozen=True, slots=True)
class M2UsageEvidence:
    control_path: dict[str, object]
    isolated_worker: dict[str, object]
    oci: dict[str, object]
    report: dict[str, object]

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "M2UsageEvidence",
            "usedEventStoreAppendFill": False,
            "crossMachine": "pending-live",
            "gpu": "not-run",
            "controlPath": self.control_path,
            "isolatedWorker": self.isolated_worker,
            "oci": self.oci,
            "report": self.report,
        }


def run_usage_evidence(output: Path) -> M2UsageEvidence:
    """Measure the real control path, then isolated Worker + OCI + report cites."""

    if output.exists() and any(output.iterdir()):
        raise ValueError("usage output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    control = _control_path_baseline(output / "control")
    isolated = _isolated_cpu_and_report(output / "isolated")
    oci = _oci_or_skip(output / "oci")
    evidence = M2UsageEvidence(
        control_path=control,
        isolated_worker=isolated["isolatedWorker"],
        oci=oci,
        report=isolated["report"],
    )
    (output / "USAGE.json").write_text(
        json.dumps(evidence.as_json(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def _control_path_baseline(root: Path) -> dict[str, object]:
    """Append/claim/cancel/coordinate through WorkerPlane and RunControl."""

    root.mkdir(parents=True, exist_ok=True)
    database = root / "research.db"
    artifacts_root = root / "artifacts"
    artifacts_root.mkdir()
    hmac_key = secrets.token_bytes(HMAC_KEY_BYTES)
    spec = load_spec(_CPU_CORPUS / "spec.yaml")
    registry = build_registry([_CPU_CORPUS / "block.json"])
    rss_before = _max_rss_bytes()
    with EventStore(database) as store:
        artifacts = LocalArtifactStore(artifacts_root)
        image = artifacts.put(_CPU_CORPUS / "brick.py")
        auth_id, auth_seq = _record_authorization(store, spec, registry)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=_SOURCE,
        )
        budget_started = time.perf_counter()
        BudgetControl(store, project_id=spec.metadata.id).append(
            validate_budget_limit_request(load_document(_BUDGET)).event_draft()
        )
        for index in range(1, _CONCURRENT_WORKERS + 1):
            ResearchControl(store, project_id=spec.metadata.id).append(_proposal_draft(index))
        mix_seconds = time.perf_counter() - budget_started
        for index in range(1, _CONCURRENT_WORKERS + 1):
            plane.register(
                worker_id=f"worker.usage.{index}",
                actor_id="researcher.alice",
                event_id=f"evt.worker.registered.usage.{index}",
            )
        inner_config = json_object({}, field="config")
        inner_inputs = json_object({}, field="inputs")
        config_digest = brick_execution_digest(
            image_digest=image.digest,
            config=inner_config,
            inputs=inner_inputs,
        )
        tokens: list[tuple[str, str]] = []
        append_started = time.perf_counter()
        for index in range(1, _CONCURRENT_WORKERS + 1):
            worker_id = f"worker.usage.{index}"
            grant_id = f"grant.usage.{index}"
            plane.record_grant(
                grant_id=grant_id,
                worker_id=worker_id,
                task_id="task.cpu",
                run_id=f"run.usage.{index}",
                attempt_id=f"attempt.usage.{index}",
                nonce=f"nonce.usage.{index}",
                expires_at="2099-01-01T00:00:00Z",
                actor_id="researcher.alice",
                event_id=f"evt.grant.recorded.usage.{index}",
                authorization_event_id=auth_id,
                authorization_sequence=auth_seq,
                image_digest=image.digest,
                config_digest=config_digest,
                spec=spec,
                registry=registry,
            )
            plane.enqueue(
                task_id="task.cpu",
                run_id=f"run.usage.{index}",
                attempt_id=f"attempt.usage.{index}",
                image_digest=image.digest,
                event_id=f"evt.work.queued.usage.{index}",
                config=inner_config,
                inputs=inner_inputs,
            )
            tokens.append((worker_id, plane.issue_token(grant_id)))
        append_seconds = time.perf_counter() - append_started
        claim_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_CONCURRENT_WORKERS) as pool:
            claim_futures = [
                pool.submit(
                    _claim_on_private_store,
                    database,
                    artifacts,
                    hmac_key,
                    spec.metadata.id,
                    worker_id,
                    token,
                )
                for worker_id, token in tokens
            ]
            claimed_pairs = [future.result() for future in as_completed(claim_futures)]
        claim_seconds = time.perf_counter() - claim_started
        claim_retries = sum(item[2] for item in claimed_pairs)
        typed_claims: list[tuple[str, ClaimedWork, int]] = []
        for worker_id, claimed, retries in claimed_pairs:
            if claimed is None:
                raise M2CheckpointError("usage claim returned no work", code="work-missing")
            typed_claims.append((worker_id, claimed, retries))
        result = execute_python_brick(artifacts, image.digest)
        result_digest = result.result_digest
        if result_digest is None:
            raise M2CheckpointError("usage brick produced no result digest", code="work-missing")
        record = artifacts.put_bytes(result.stdout)
        token_by_worker = dict(tokens)
        complete_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_CONCURRENT_WORKERS) as pool:
            complete_futures = [
                pool.submit(
                    _complete_on_private_store,
                    database,
                    artifacts,
                    hmac_key,
                    spec.metadata.id,
                    worker_id,
                    token_by_worker[worker_id],
                    claimed,
                    result_digest,
                    record.digest,
                )
                for worker_id, claimed, _retries in typed_claims
            ]
            complete_retries = sum(future.result() for future in as_completed(complete_futures))
        complete_seconds = time.perf_counter() - complete_started
        plane.register(
            worker_id="worker.usage.other",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.usage.other",
        )
        coordinate_started = time.perf_counter()
        foreign = issue_grant_token(
            hmac_key,
            grant_id="grant.usage.1",
            grant_event_id="evt.grant.recorded.usage.1",
            worker_id="worker.usage.other",
            task_id="task.cpu",
            attempt_id="attempt.usage.1",
            run_id="run.usage.1",
            nonce="nonce.usage.1",
            expires_at="2099-01-01T00:00:00Z",
            project_id=spec.metadata.id,
            image_digest=image.digest,
            config_digest=config_digest,
        )
        try:
            plane.poll(worker_id="worker.usage.other", grant_token=foreign)
            raise M2CheckpointError("foreign worker claimed another grant", code="lease-conflict")
        except WorkerGrantError as exc:
            if exc.code != "grant-worker-mismatch":
                raise
        coordinate_seconds = time.perf_counter() - coordinate_started
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
        policy = _authorization_policy(dry_run)
        gate = authorize_plan(dry_run, policy)
        identities = _run_identities("cancel")
        runtime = WorkerRuntime(
            store,
            project_id=spec.metadata.id,
            run_id="run.usage.cancel",
            attempt_id="attempt.usage.cancel",
            source=_SOURCE,
            subject="run.usage.cancel",
            stream_id="run.usage.cancel",
            actor_id="researcher.alice",
            events=identities,
        )
        runtime.start(
            report=dry_run,
            authorization=gate,
            citation={"eventId": auth_id, "sequence": auth_seq},
            revision=spec.metadata.revision,
        )
        plane.register(
            worker_id="worker.usage.cancel",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.usage.cancel",
        )
        plane.record_grant(
            grant_id="grant.usage.cancel",
            worker_id="worker.usage.cancel",
            task_id="task.cpu",
            run_id="run.usage.cancel",
            attempt_id="attempt.usage.cancel",
            nonce="nonce.usage.cancel",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.usage.cancel",
            authorization_event_id=auth_id,
            authorization_sequence=auth_seq,
            image_digest=image.digest,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
        )
        plane.enqueue(
            task_id="task.cpu",
            run_id="run.usage.cancel",
            attempt_id="attempt.usage.cancel",
            image_digest=image.digest,
            event_id="evt.work.queued.usage.cancel",
            config=inner_config,
            inputs=inner_inputs,
        )
        cancel_token = plane.issue_token("grant.usage.cancel")
        cancel_started = time.perf_counter()
        claimed_cancel, _ = _retry_cas(
            lambda: plane.poll(worker_id="worker.usage.cancel", grant_token=cancel_token)
        )
        if claimed_cancel is None:
            raise M2CheckpointError("cancel usage claim returned no work", code="work-missing")
        request_cancellation(
            store,
            validate_run_cancellation_request_document(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "RunCancellationRequest",
                    "projectId": spec.metadata.id,
                    "experimentRevision": spec.metadata.revision,
                    "runId": "run.usage.cancel",
                    "target": {"kind": "run"},
                    "reasonCode": "researcher.requested",
                    "source": _SOURCE,
                    "subject": "run.usage.cancel",
                    "streamid": "run.usage.cancel",
                    "actor": {"id": "researcher.alice"},
                    "event": {
                        "id": "evt.run.cancel.requested.usage",
                        "time": "2026-09-08T00:00:00Z",
                    },
                    "evidenceRefs": [],
                }
            ),
        )
        resumed, _ = _retry_cas(
            lambda: plane.poll(worker_id="worker.usage.cancel", grant_token=cancel_token)
        )
        cancel_seconds = time.perf_counter() - cancel_started
        if resumed is None or resumed.cancel_requested is not True or resumed.resumed is not True:
            raise M2CheckpointError(
                "cancel usage poll did not return resumed cancelRequested",
                code="cancel-unobserved",
            )
        types = [item.event.type for item in store.read_events(limit=500)]
        counts = dict(Counter(types))
        sqlite_bytes = database.stat().st_size
    return {
        "appendSeconds": _seconds(append_seconds),
        "claimSeconds": _seconds(claim_seconds),
        "completeSeconds": _seconds(complete_seconds),
        "cancelSeconds": _seconds(cancel_seconds),
        "coordinateSeconds": _seconds(coordinate_seconds),
        "mixedResearchBudgetSeconds": _seconds(mix_seconds),
        "concurrentWorkers": _CONCURRENT_WORKERS,
        "casRetries": claim_retries + complete_retries,
        "eventCount": len(types),
        "sqliteBytes": sqlite_bytes,
        "eventTypeCounts": counts,
        "peakRssBytes": max(rss_before, _max_rss_bytes()),
        "usedEventStoreAppendFill": False,
        "cancelRequestedOnResume": True,
        "foreignClaimCode": "grant-worker-mismatch",
    }


def _isolated_cpu_and_report(root: Path) -> dict[str, dict[str, object]]:
    """Independent control-plane process + Worker CAS, then a cited report."""

    root.mkdir(parents=True, exist_ok=True)
    control = root / "control"
    worker = root / "worker"
    state = control / "state"
    control_cas = control / "artifacts"
    worker_cas = worker / "artifacts"
    database = control / "research.db"
    control.mkdir()
    worker.mkdir()
    control_cas.mkdir()
    hmac_key = secrets.token_bytes(HMAC_KEY_BYTES)
    spec = load_spec(_CPU_CORPUS / "spec.yaml")
    registry = build_registry([_CPU_CORPUS / "block.json"])
    worker_request = load_worker_register_request(_CPU_CORPUS / "worker.json")
    grant_request = load_authorization_grant_request(_CPU_CORPUS / "grant.json")
    identities = _load_run_events(_CPU_CORPUS / "run-events.json")
    planned = spec.workflows[0].graph.nodes[0]
    if type(planned) is not TaskBlock:
        raise M2CheckpointError(
            "usage spec must contain a python-brick task",
            code="plan-not-ready",
        )
    inner_config = json_object(planned.config.get("config", {}), field="config")
    inner_inputs = json_object(planned.config.get("inputs", {}), field="inputs")
    with EventStore(database) as store:
        artifacts = LocalArtifactStore(control_cas)
        image = artifacts.put(_CPU_CORPUS / "brick.py")
        if grant_request.image_digest != image.digest:
            raise M2CheckpointError(
                "CAS brick digest does not match the grant imageDigest",
                code="execution-binding-mismatch",
            )
        auth_id, auth_seq = _record_authorization(store, spec, registry)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        )
        plane.register(
            worker_id=worker_request.worker_id,
            actor_id=worker_request.actor.id,
            event_id=worker_request.event.id,
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
            authorization_event_id=auth_id,
            authorization_sequence=auth_seq,
            image_digest=image.digest,
            config_digest=grant_request.config_digest,
            spec=spec,
            registry=registry,
            time=grant_request.event.time,
            workflow_id=spec.workflows[0].id,
        )
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
        gate = authorize_plan(dry_run, _authorization_policy(dry_run))
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
            authorization=gate,
            citation={"eventId": auth_id, "sequence": auth_seq},
            revision=spec.metadata.revision,
        )
        plane.enqueue(
            task_id=grant_request.task_id,
            run_id=grant_request.run_id,
            attempt_id=grant_request.attempt_id,
            image_digest=image.digest,
            event_id="evt.work.queued.task.cpu",
            config=inner_config,
            inputs=inner_inputs,
            time=grant_request.event.time,
        )
        grant_token = plane.issue_token(grant_request.grant_id)
    write_hmac_key(state / "hmac.key", hmac_key)
    serve = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "workers",
            "serve",
            str(database),
            "--artifacts",
            str(control_cas),
            "--state",
            str(state),
            "--project",
            spec.metadata.id,
            "--source",
            worker_request.source,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if serve.stdout is None:
            raise M2CheckpointError("control-plane serve produced no stdout", code="serve-missing")
        receipt = json.loads(serve.stdout.readline())
        url = receipt["url"]
        if not url.startswith("https://127.0.0.1:"):
            raise M2CheckpointError("isolated serve is not loopback HTTPS", code="tls-required")
        ca = worker / "tls-cert.pem"
        shutil.copy2(state / "tls-cert.pem", ca)
        os.chmod(ca, stat.S_IRUSR | stat.S_IWUSR)
        credential_path = worker / "credential.json"
        write_worker_credential(
            credential_path,
            WorkerCredential(
                control_plane_url=url,
                worker_id=worker_request.worker_id,
                session=issue_worker_session(hmac_key, worker_id=worker_request.worker_id),
                grant_token=grant_token,
                tls_ca_path=ca,
                tls_fingerprint=pem_fingerprint(ca),
            ),
        )
        completed = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "llm_research_os",
                "workers",
                "run",
                str(credential_path),
                "--artifacts",
                str(worker_cas),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise M2CheckpointError(
                completed.stderr.strip() or "isolated worker failed",
                code="work-missing",
            )
        if "rg1." in completed.stdout or "rg1." in completed.stderr:
            raise M2CheckpointError("isolated worker leaked a grant token", code="token-leaked")
        LocalArtifactStore(worker_cas).verify(image.digest)
        if control_cas.resolve() == worker_cas.resolve():
            raise M2CheckpointError(
                "Worker CAS must not be the control-plane CAS",
                code="cas-shared",
            )
    finally:
        serve.terminate()
        serve.wait(timeout=10)
    with EventStore(database, require_existing=True) as store:
        artifacts = LocalArtifactStore(control_cas)
        fold = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=spec.metadata.id,
            source=worker_request.source,
            experiment_revision=spec.metadata.revision,
        ).rebuild()
        lease = fold.lease(f"lease.{grant_request.grant_id}")
        if lease is None or lease.artifact_digest is None:
            raise M2CheckpointError(
                "isolated complete did not record an artifact",
                code="artifact-missing",
            )
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
        gate = authorize_plan(dry_run, _authorization_policy(dry_run))
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
                "isolated loop did not complete the Run",
                code="run-inconsistent",
            )
        markdown = render_markdown(
            build_run_report(store, grant_request.run_id, project_id=spec.metadata.id)
        )
        missing = [label for label in _REPORT_LABELS if label not in markdown]
        if missing:
            raise M2CheckpointError(
                "report is missing binding cites: " + ", ".join(missing),
                code="report-cites-missing",
            )
        (root / "report.md").write_text(markdown, encoding="utf-8")
    return {
        "isolatedWorker": {
            "status": "observed",
            "workCompleted": True,
            "privateCas": True,
            "controlPlaneUrlScheme": "https",
            "localhostIsNotCrossMachine": True,
        },
        "report": {
            "runId": grant_request.run_id,
            "cites": list(_REPORT_LABELS),
            "imageDigest": image.digest,
            "artifactDigest": lease.artifact_digest,
        },
    }


def _oci_or_skip(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "research.db"
    artifacts = root / "artifacts"
    try:
        result = prove_oci_loop(_OCI_CORPUS, database, artifacts)
    except (WorkerSandboxError, M2CheckpointError, WorkerError) as exc:
        code = getattr(exc, "code", "worker")
        if oci_integration_required():
            raise
        if code == "oci-runtime-missing":
            return {
                "status": "skipped-no-runtime",
                "required": False,
                "note": "ordinary hosts may skip; designated Linux OCI CI must not",
            }
        if code == "oci-image-missing":
            return {
                "status": "skipped-no-image",
                "required": False,
                "note": "pinned image is local-only; designated Linux OCI CI must not skip",
            }
        raise
    return {
        "status": "observed",
        "required": oci_integration_required(),
        "runId": result.run_id,
        "imageDigest": result.image_digest,
        "artifactDigest": result.artifact_digest,
    }


def _claim_on_private_store(
    database: Path,
    artifacts: LocalArtifactStore,
    hmac_key: bytes,
    project_id: str,
    worker_id: str,
    token: str,
) -> tuple[str, ClaimedWork | None, int]:
    with EventStore(database, require_existing=True) as store:
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=project_id,
            source=_SOURCE,
        )
        claimed, retries = _retry_cas(lambda: plane.poll(worker_id=worker_id, grant_token=token))
        return worker_id, claimed, retries


def _complete_on_private_store(
    database: Path,
    artifacts: LocalArtifactStore,
    hmac_key: bytes,
    project_id: str,
    worker_id: str,
    token: str,
    claimed: ClaimedWork,
    result_digest: str,
    artifact_digest: str,
) -> int:
    with EventStore(database, require_existing=True) as store:
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=hmac_key,
            project_id=project_id,
            source=_SOURCE,
        )
        _, retries = _retry_cas(
            lambda: plane.complete(
                worker_id=worker_id,
                grant_token=token,
                lease_id=claimed.lease_id,
                result_digest=result_digest,
                artifact_digest=artifact_digest,
            )
        )
        return retries


def _record_authorization(
    store: EventStore, spec: ResearchSpec, registry: BlockRegistry
) -> tuple[str, str]:
    dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    policy = _authorization_policy(dry_run)
    gate = authorize_plan(dry_run, policy)
    document = snapshot_json_document(
        load_document(_CPU_CORPUS / "authorization-event.json", reject_symlinks=True)
    )
    if type(document) is not dict:
        raise M2CheckpointError(
            "authorization event request must be an object",
            code="authorization-binding-mismatch",
        )
    document["binding"] = {
        "specDigest": gate.spec_digest,
        "registryDigest": gate.registry_digest,
        "planDigest": gate.plan_digest,
        "decisionDigest": gate.decision_digest,
    }
    recorded = record_plan_authorization_event(
        store,
        dry_run,
        policy,
        validate_plan_authorization_event_request_document(document),
    )
    return recorded.stored.event.id, recorded.stored.event.sequence


def _authorization_policy(dry_run: DryRunReport) -> PlanAuthorizationPolicy:
    request = load_plan_authorization_request(_CPU_CORPUS / "authorization-request.json")
    if dry_run.digests.plan is None:
        raise M2CheckpointError("usage plan digest is missing", code="plan-not-ready")
    return PlanAuthorizationPolicy(
        spec_digest=dry_run.digests.spec,
        registry_digest=dry_run.digests.registry,
        plan_digest=dry_run.digests.plan,
        granted_capabilities=request.policy().granted_capabilities,
    )


def _proposal_draft(index: int) -> dict[str, Any]:
    document = snapshot_json_document(load_document(_PROPOSAL))
    if type(document) is not dict:
        raise M2CheckpointError("proposal template must be an object", code="proposal-invalid")
    document["proposalId"] = f"proposal.usage.{index}"
    document["subject"] = f"proposal.usage.{index}"
    event = document["event"]
    if type(event) is not dict:
        raise M2CheckpointError(
            "proposal event identity must be an object",
            code="proposal-invalid",
        )
    event["id"] = f"evt.proposal.usage.{index}"
    return validate_proposal_submit_request(document).event_draft()


def _load_run_events(path: Path) -> dict[str, tuple[str, str]]:
    document = snapshot_json_document(load_document(path, reject_symlinks=True))
    if type(document) is not dict:
        raise M2CheckpointError("run events document must be an object", code="run-events-invalid")
    events = document.get("events")
    identities: dict[str, tuple[str, str]] = {}
    if type(events) is not dict:
        raise M2CheckpointError("run events document is missing events", code="run-events-invalid")
    for event_type, identity in events.items():
        if type(identity) is not dict:
            raise M2CheckpointError("run events identity is invalid", code="run-events-invalid")
        identities[str(event_type)] = (str(identity["id"]), str(identity["time"]))
    identities.update(
        {
            "attempt.cancelled": ("evt.attempt.cancelled.usage", "2026-09-08T00:00:00Z"),
            "run.cancelled": ("evt.run.cancelled.usage", "2026-09-08T00:00:00Z"),
        }
    )
    return identities


def _run_identities(suffix: str) -> dict[str, tuple[str, str]]:
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


def _retry_cas[T](operation: Callable[[], T], *, retries: int = _CAS_RETRIES) -> tuple[T, int]:
    last: Exception | None = None
    used = 0
    for attempt in range(retries):
        try:
            return operation(), used
        except EventSequenceConflictError as exc:
            last = exc
            used = attempt + 1
            time.sleep(0.01)
    raise M2CheckpointError("control-path CAS retries exhausted", code="cas-conflict") from last


def _max_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(usage)
    return int(usage) * 1024


def _seconds(value: float) -> float:
    return round(value, 3)
