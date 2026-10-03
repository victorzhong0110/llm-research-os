"""Single-attempt reviewed native launch through the Worker and Run controls."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BufferedReader
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.events.models import RESEARCH_EVENT_SCHEMA_ID
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_material import NativeReviewedInterpreterIdentity
from llm_research_os.execution.native_reviewed_preparation import (
    _payload_digest,
    _read_file,
    _runtime_file_digest,
    check_before_user_code,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NativeReviewedPreparationReceipt,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.workers.binding import require_authorized_execution_binding
from llm_research_os.workers.models import (
    IMAGE_MEDIA_NATIVE_REVIEWED,
    WORKER_RUNTIME_NATIVE_REVIEWED,
)
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import run_cancel_requested
from llm_research_os.workers.supervise import (
    OBSERVATION_EXITED,
    ExecutionIdentity,
    observe_process_group,
    posix_start_token,
    save_execution_identity,
)

if TYPE_CHECKING:
    from llm_research_os.execution.native_reviewed_checkpoint import NativeRestoreClaim


class NativeLaunchError(ValueError):
    """The attempt was refused or its execution outcome is uncertain."""


@dataclass(frozen=True, slots=True)
class NativeTaskResult:
    lease_id: str
    artifact_digest: str
    result_digest: str
    output: object


def execute_reviewed_native(
    *,
    request: NativeReviewedExecutionRequest,
    spec: ResearchSpec,
    registry: BlockRegistry,
    plane: WorkerPlane,
    workspace: Path,
    state_dir: Path,
    grant_token: str,
    restore_claim: NativeRestoreClaim | None = None,
    source_request: NativeReviewedExecutionRequest | None = None,
) -> NativeTaskResult:
    """Execute exactly one prepared Attempt. A consumed grant is never relaunched.

    A durable intent precedes consumption. The child blocks on stdin until its
    process identity has been saved; loss of the parent closes the pipe without
    importing user code. Any uncertain boundary leaves the intent and consumed
    authority in place for explicit observation under R06.
    """

    if (
        request.project_id != plane.project_id
        or int(request.revision_id) != plane.experiment_revision
    ):
        raise NativeLaunchError("request project or revision does not match Worker")
    if content_digest(execution_object(request)) != request.config_digest:
        raise NativeLaunchError("request execution object digest differs")
    checkpoint_inputs = [item for item in request.inputs if item.purpose == "checkpoint"]
    if checkpoint_inputs or restore_claim is not None or source_request is not None:
        if not checkpoint_inputs or restore_claim is None or source_request is None:
            raise NativeLaunchError("checkpoint restore requires source and bound claim")
        from llm_research_os.execution.native_reviewed_checkpoint import verify_native_restore

        verify_native_restore(
            claim=restore_claim, source=source_request, target=request, plane=plane
        )
    require_authorized_execution_binding(
        plane.store,
        spec,
        registry,
        project_id=request.project_id,
        experiment_revision=plane.experiment_revision,
        planned_task_id=request.task_id,
        event_id=request.authorization_event_id,
        sequence=request.authorization_sequence,
        image_digest=request.code.bundle_digest,
        config_digest=request.config_digest,
        workflow_id=request.workflow_id,
    )
    diagnosis = check_before_user_code(
        request=request,
        store=plane.store,
        artifacts=plane.artifacts,
        workspace=workspace,
        grant_token=grant_token,
        hmac_key=plane.hmac_key,
        now=plane.clock(),
    )
    if diagnosis.outcome != "ready":
        raise NativeLaunchError(f"prepared material is not ready: {diagnosis.reason_code}")
    manifest = _manifest(workspace, diagnosis.receipt_digest)
    frame = (
        canonical_json(
            {
                "root": str(workspace.resolve()),
                "entrypoint": request.code.entrypoint,
                "files": manifest,
            }
        ).encode()
        + b"\n"
    )
    if len(frame) > 16_384:
        raise NativeLaunchError("runner input exceeds its fixed limit")
    fold = plane.rebuild()
    grant = fold.grant(diagnosis.grant_id or "")
    queued = fold.queued_work(request.task_id, request.attempt_id)
    if (
        grant is None
        or queued is None
        or (
            grant.worker_id != request.worker_id
            or grant.run_id != request.run_id
            or grant.attempt_id != request.attempt_id
            or queued.run_id != request.run_id
            or queued.runtime != WORKER_RUNTIME_NATIVE_REVIEWED
            or queued.image_media_type != IMAGE_MEDIA_NATIVE_REVIEWED
            or queued.image_digest != request.code.bundle_digest
            or queued.config_digest != request.config_digest
            or queued.config != execution_object(request)
            or queued.inputs != {}
        )
    ):
        raise NativeLaunchError("queued native work does not match reviewed request")
    run = RunControl(plane.store, project_id=request.project_id, run_id=request.run_id)
    if run.rebuild().snapshot is not None:
        raise NativeLaunchError("Run already exists; an Attempt cannot be redispatched")
    intent = _write_intent(state_dir, request, restore_claim=restore_claim)
    claimed = False
    started = False
    child: subprocess.Popen[bytes] | None = None
    try:
        _lifecycle(
            run,
            request,
            "run.queued",
            {
                "workflowId": request.workflow_id,
                "specDigest": request.spec_digest,
                "registryDigest": request.registry_digest,
                "planDigest": request.plan_digest,
                "decisionDigest": request.decision_digest,
                "authorizationEventId": request.authorization_event_id,
                "authorizationSequence": request.authorization_sequence,
                "maxAttempts": 1,
            },
        )
        _lifecycle(run, request, "run.started", {})
        _lifecycle(
            run,
            request,
            "attempt.queued",
            {
                "ordinal": 1,
                "retryOf": None,
                "retryDecisionId": None,
            },
            attempt=True,
        )
        claim = plane.poll(worker_id=request.worker_id, grant_token=grant_token)
        if (
            claim is None
            or claim.resumed
            or claim.cancel_requested
            or (claim.config_digest != request.config_digest or claim.grant_id != grant.grant_id)
        ):
            raise NativeLaunchError("native claim is unavailable or has already been consumed")
        claimed = True
        _lifecycle(run, request, "attempt.started", {}, attempt=True)
        started = True
        child = subprocess.Popen(  # noqa: S603 - fixed trusted runner, no shell
            [sys.executable, "-I", "-B", str(Path(__file__).with_name("native_reviewed_child.py"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env={"PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"},
            start_new_session=True,
            close_fds=True,
        )
        # Save identity before releasing the child. EOF on this pipe refuses import.
        save_execution_identity(
            state_dir / "identities",
            ExecutionIdentity(
                lease_id=claim.lease_id,
                kind="posix-pg",
                pid=child.pid,
                pgid=child.pid,
                start_token=posix_start_token(child.pid),
                container_id=None,
                docker_executable=None,
            ),
        )
        _sync_identity(state_dir / "identities", claim.lease_id)
        interpreter = NativeReviewedInterpreterIdentity.model_validate_json(
            (workspace / "material/environment/interpreter").read_bytes()
        )
        if _launched_interpreter_digest(child.pid) != interpreter.executable_digest:
            raise NativeLaunchError("launched interpreter does not match reviewed bytes")
        if child.stdin is None:
            raise NativeLaunchError("runner start barrier is unavailable")
        child.stdin.write(frame)
        child.stdin.close()
        output, diagnostic, code = _collect(child, request)
        if observe_process_group(child.pid, child.pid) != OBSERVATION_EXITED:
            raise NativeLaunchError("reviewed process group has not been observed stopped")
        if run_cancel_requested(
            plane.store,
            project_id=request.project_id,
            run_id=request.run_id,
            attempt_id=request.attempt_id,
        ):
            from llm_research_os.execution.native_reviewed_recovery import (
                reconcile_reviewed_native,
            )

            cancellation = reconcile_reviewed_native(
                request=request, plane=plane, state_dir=state_dir, grant_token=grant_token
            )
            if cancellation.disposition == "cancelled":
                raise NativeLaunchError("reviewed cancellation was observed")
            raise NativeLaunchError("reviewed cancellation outcome is uncertain")
        if code != 0:
            plane.fail(
                worker_id=request.worker_id,
                grant_token=grant_token,
                lease_id=claim.lease_id,
                reason_code="native-task-failed",
            )
            _lifecycle(
                run,
                request,
                "attempt.failed",
                {
                    "reasonCode": "native-task-failed",
                    "retryHint": "not-retryable",
                },
                attempt=True,
            )
            _lifecycle(run, request, "run.failed", {"reasonCode": "native-task-failed"})
            detail = diagnostic.decode(errors="replace")[:200]
            raise NativeLaunchError(f"reviewed task exited with status {code}: {detail}")
        result = json.loads(output)
        payload = canonical_json(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeReviewedTaskOutput",
                "requestDigest": request_digest(request),
                "taskId": request.task_id,
                "runId": request.run_id,
                "attemptId": request.attempt_id,
                "output": result,
            }
        ).encode()
        if len(payload) > request.limits.artifact_bytes:
            raise NativeLaunchError("task artifact exceeds its reviewed bound")
        artifact = plane.artifacts.put_bytes(payload, limit=request.limits.artifact_bytes)
        result_digest = content_digest(json.loads(payload))
        plane.complete(
            worker_id=request.worker_id,
            grant_token=grant_token,
            lease_id=claim.lease_id,
            result_digest=result_digest,
            artifact_digest=artifact.digest,
        )
        _lifecycle(run, request, "attempt.succeeded", {}, attempt=True)
        _lifecycle(run, request, "run.completed", {})
        return NativeTaskResult(claim.lease_id, artifact.digest, result_digest, result)
    except Exception:
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            if child.poll() is None:
                child.wait()
        consumed = claimed
        if not consumed:
            recorded = plane.rebuild().grant(grant.grant_id)
            consumed = recorded is not None and recorded.consumed_lease_id is not None
        if consumed:
            try:
                snapshot = run.rebuild().snapshot
                if snapshot is not None and not started:
                    _lifecycle(run, request, "attempt.started", {}, attempt=True)
                    snapshot = run.rebuild().snapshot
                if snapshot is not None and snapshot.status.value == "running":
                    _lifecycle(
                        run,
                        request,
                        "attempt.unknown",
                        {
                            "reasonCode": "native-outcome-uncertain",
                        },
                        attempt=True,
                    )
            except Exception as exc:
                raise NativeLaunchError(
                    "outcome uncertain and lifecycle persistence failed; inspect launch intent"
                ) from exc
        raise
    finally:
        # Intent is intentionally retained for both terminal and uncertain outcomes.
        _ = intent


def _write_intent(
    state_dir: Path,
    request: NativeReviewedExecutionRequest,
    *,
    restore_claim: NativeRestoreClaim | None = None,
) -> Path:
    if state_dir.is_symlink():
        raise NativeLaunchError("launch state directory cannot be a symlink")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    identity = f"{request.project_id}:{request.run_id}:{request.attempt_id}"
    name = hashlib.sha256(identity.encode()).hexdigest()
    path = state_dir / f"{name}.intent"
    document: dict[str, object] = {
        "requestDigest": request_digest(request),
        "runId": request.run_id,
        "attemptId": request.attempt_id,
    }
    if restore_claim is not None:
        document["restore"] = restore_claim.model_dump(mode="json", by_alias=True)
    payload = canonical_json(document).encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise NativeLaunchError(
            "launch intent already exists; Attempt cannot be relaunched"
        ) from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return path


def _manifest(workspace: Path, receipt_digest: str | None) -> dict[str, str]:
    """Pin every prepared file before grant consumption and child creation."""
    try:
        receipt = NativeReviewedPreparationReceipt.model_validate_json(
            (workspace / "receipt.json").read_bytes()
        )
    except (OSError, ValidationError):
        raise NativeLaunchError("prepared receipt changed before launch") from None
    document = receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    if content_digest(document) != receipt_digest:
        raise NativeLaunchError("prepared receipt changed before launch")
    files: dict[str, str] = {}
    for row in receipt.files:
        relative = row.relative_path
        payload = _read_file(workspace, relative)
        if payload is None or _payload_digest(row, payload) != row.digest:
            raise NativeLaunchError("prepared file changed before launch")
        files[relative] = "sha256:" + hashlib.sha256(payload).hexdigest()
    return files


def _sync_identity(identity_dir: Path, lease_id: str) -> None:
    from llm_research_os.workers.supervise import identity_path

    fd = os.open(identity_path(identity_dir, lease_id), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(identity_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _launched_interpreter_digest(pid: int) -> str:
    """Check the actual image on Linux procfs, else rehash the pinned path."""
    digest = hashlib.sha256()
    count = 0
    try:
        stream = open(f"/proc/{pid}/exe", "rb")  # noqa: SIM115 - context below
    except (FileNotFoundError, PermissionError):
        # Some isolated Linux runners hide other processes' procfs entries.
        # The child still waits behind the barrier during this recheck.
        if pid <= 0:
            raise NativeLaunchError("child process identity is unavailable") from None
        return _runtime_file_digest(Path(sys.executable))
    with stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > 128 * 1024 * 1024:
                raise NativeLaunchError("launched interpreter is too large")
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _lifecycle(
    run: RunControl,
    request: NativeReviewedExecutionRequest,
    event_type: str,
    payload: dict[str, Any],
    *,
    attempt: bool = False,
) -> None:
    data: dict[str, Any] = {
        "schemaVersion": "v0alpha1",
        "actor": {"id": request.worker_id, "kind": "system"},
        "projectId": request.project_id,
        "experimentRevision": int(request.revision_id),
        "runId": request.run_id,
        "payload": payload,
        "evidenceRefs": [],
    }
    if attempt:
        data["attemptId"] = request.attempt_id
    run.append(
        {
            "specversion": "1.0",
            "id": f"evt.native.{request.run_id}.{request.attempt_id}.{event_type}",
            "source": f"https://researchos.dev/projects/{request.project_id}",
            "type": event_type,
            "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "subject": request.run_id,
            "dataschema": RESEARCH_EVENT_SCHEMA_ID,
            "datacontenttype": "application/json",
            "streamid": request.project_id,
            "data": data,
        }
    )


def _collect(
    child: subprocess.Popen[bytes],
    request: NativeReviewedExecutionRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[bytes, bytes, int]:
    if child.stdout is None or child.stderr is None:
        raise NativeLaunchError("runner pipes are unavailable")
    bounds = {child.stdout: request.limits.stdout_bytes, child.stderr: request.limits.stderr_bytes}
    captured: dict[Any, bytearray] = {pipe: bytearray() for pipe in bounds}
    deadline = time.monotonic() + request.limits.wall_time_seconds
    with selectors.DefaultSelector() as selector:
        for pipe in bounds:
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            if cancelled is not None and cancelled():
                raise NativeLaunchError("reviewed cancellation is requested")
            if time.monotonic() >= deadline:
                raise NativeLaunchError("reviewed wall-clock limit exceeded")
            for key, _ in selector.select(timeout=min(0.25, max(0, deadline - time.monotonic()))):
                pipe = cast(BufferedReader, key.fileobj)
                chunk = pipe.read1(65536)
                if not chunk:
                    selector.unregister(pipe)
                else:
                    captured[pipe].extend(chunk)
                    if len(captured[pipe]) > bounds[pipe]:
                        raise NativeLaunchError("reviewed diagnostic/output bound exceeded")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NativeLaunchError("reviewed wall-clock limit exceeded")
    if cancelled is None:
        code = child.wait(timeout=remaining)
    else:
        while True:
            if cancelled():
                raise NativeLaunchError("reviewed cancellation is requested")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeLaunchError("reviewed wall-clock limit exceeded")
            try:
                code = child.wait(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    return bytes(captured[child.stdout]), bytes(captured[child.stderr]), code
