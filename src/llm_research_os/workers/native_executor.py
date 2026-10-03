"""Worker-local reviewed native execution through controller HTTPS, without DB/key copies."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, MAX_WORKER_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_runtime import (
    NativeLaunchError,
    _collect,
    _launched_interpreter_digest,
    _manifest,
)
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_NATIVE_REVIEWED,
    WORKER_RUNTIME_NATIVE_REVIEWED,
)
from llm_research_os.workers.native_material_documents import NativeMaterialIndex
from llm_research_os.workers.native_outcome_client import publish_native_outcome
from llm_research_os.workers.native_outcome_documents import (
    NativeOutcomeReceipt,
    NativeOutcomeRequest,
)
from llm_research_os.workers.native_preparation import prepare_remote_native
from llm_research_os.workers.native_start_client import publish_native_start
from llm_research_os.workers.native_start_documents import LeaseIdentifier, NativeStartRequest
from llm_research_os.workers.native_state import private_state_lock
from llm_research_os.workers.native_transfer import _origin
from llm_research_os.workers.supervise import (
    OBSERVATION_EXITED,
    OBSERVATION_RUNNING,
    OBSERVED_STOP,
    ExecutionIdentity,
    observe_and_stop,
    observe_process,
    observe_process_group,
    posix_start_token,
)


@dataclass(frozen=True, slots=True)
class RemoteNativeResult:
    disposition: str
    lease_id: str
    output: Any = None
    receipt: NativeOutcomeReceipt | None = None


def execute_remote_native(
    client: WorkerClient,
    *,
    artifacts: LocalArtifactStore,
    workspace: Path,
    staging_root: Path,
    state_root: Path,
) -> RemoteNativeResult:
    """Only a fresh claim can create a child; uncertain intent is retained forever."""
    _origin(client)
    if client.tls_fingerprint is None:
        raise WorkerError("native execution requires a TLS pin", code="tls-required")
    roots = tuple(p.absolute() for p in (artifacts.root, workspace, staging_root, state_root))
    if any(a.is_relative_to(b) for i, a in enumerate(roots) for j, b in enumerate(roots) if i != j):
        raise WorkerError("native executor roots overlap", code="native-state-invalid")
    index = NativeMaterialIndex.model_validate(client.fetch_native_material_index())
    request = index.request
    name = _name(request)
    with private_state_lock(state_root, name) as root:
        if _exists(root, name + ".intent"):
            raise WorkerError(
                "native launch intent exists; observe only", code="native-intent-exists"
            )
        prepared = prepare_remote_native(
            client, artifacts=artifacts, workspace=workspace, staging_root=staging_root
        )
        if (
            prepared.request_digest != request_digest(request)
            or prepared.grant_id != index.grant_id
        ):
            raise WorkerError("native preparation changed", code="native-execution-binding")
        manifest = _manifest(
            workspace,
            content_digest(prepared.model_dump(mode="json", by_alias=True, exclude_none=True)),
        )
        frame = (
            canonical_json(
                {
                    "root": str(workspace.absolute()),
                    "entrypoint": request.code.entrypoint,
                    "files": manifest,
                }
            ).encode()
            + b"\n"
        )
        if len(frame) > 16384:
            raise WorkerError(
                "native runner frame exceeds its bound", code="native-execution-binding"
            )
        intent = {
            "request": request.model_dump(mode="json", by_alias=True, exclude_none=True),
            "requestDigest": request_digest(request),
            "grantId": index.grant_id,
            "origin": client.base_url.rstrip("/"),
            "tlsFingerprint": client.tls_fingerprint,
            "workerId": client.worker_id,
            "tokenFingerprint": hashlib.sha256(client.grant_token.encode()).hexdigest(),
        }
        _write(root, name + ".intent", intent)
        claim = client.poll()
        if (
            claim is None
            or claim.get("resumed") is not False
            or claim.get("cancelRequested") is not False
            or any(
                claim.get(key) != value
                for key, value in {
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "attemptId": request.attempt_id,
                    "imageDigest": request.code.bundle_digest,
                    "configDigest": request.config_digest,
                    "config": execution_object(request),
                    "runtime": WORKER_RUNTIME_NATIVE_REVIEWED,
                    "imageMediaType": IMAGE_MEDIA_NATIVE_REVIEWED,
                    "inputs": {},
                }.items()
            )
        ):
            raise WorkerError(
                "native claim is not a fresh bound claim", code="native-claim-unavailable"
            )
        try:
            lease_id = TypeAdapter(LeaseIdentifier).validate_python(claim.get("leaseId"))
        except ValidationError:
            raise WorkerError("native lease is invalid", code="native-claim-unavailable") from None
        _write(root, name + ".claim", {"leaseId": lease_id})
        # Recheck host/material/live authority after consuming, before creating the blocked child.
        if (
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging_root
            )
            != prepared
        ):
            raise WorkerError("native preparation changed", code="native-execution-binding")
        child = subprocess.Popen(  # noqa: S603 - fixed reviewed runner, no shell
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).parents[1] / "execution/native_reviewed_child.py"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env={"PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"},
            start_new_session=True,
            close_fds=True,
        )
        identity = ExecutionIdentity(
            lease_id=lease_id,
            kind="posix-pg",
            pid=child.pid,
            pgid=child.pid,
            start_token=posix_start_token(child.pid),
            container_id=None,
            docker_executable=None,
        )
        start: NativeStartRequest | None = None
        monitor: _Monitor | None = None
        output = None
        phase = "unknown"
        observation = "unknown"
        try:
            if identity.start_token is None:
                raise WorkerError(
                    "native process identity is unavailable", code="native-execution-unobserved"
                )
            identity_doc = {
                "leaseId": lease_id,
                "pid": child.pid,
                "pgid": child.pid,
                "startToken": identity.start_token,
                "kind": "posix-pg",
            }
            _write(root, name + ".identity", identity_doc)
            interpreter = json.loads((workspace / "material/environment/interpreter").read_bytes())
            if _launched_interpreter_digest(child.pid) != interpreter["executableDigest"]:
                raise WorkerError("native interpreter differs", code="native-execution-binding")
            start = NativeStartRequest.model_validate(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "NativeStartRequest",
                    "leaseId": lease_id,
                    "preparation": prepared.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    "identityDigest": content_digest(identity_doc),
                }
            )
            _write(
                root,
                name + ".start",
                start.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            publish_native_start(client, start)
            # Pin workspace bytes again; child independently verifies/freeze-loads every module.
            if (
                _manifest(
                    workspace,
                    content_digest(
                        prepared.model_dump(mode="json", by_alias=True, exclude_none=True)
                    ),
                )
                != manifest
            ):
                raise WorkerError(
                    "native material changed at barrier", code="native-execution-binding"
                )
            if child.stdin is None:
                raise WorkerError("native barrier is unavailable", code="native-execution-binding")
            monitor = _Monitor(client, request, lease_id)
            live = monitor.check()
            if not live or monitor.stop_requested.is_set():
                raise WorkerError(
                    "native authority changed at barrier", code="native-barrier-refused"
                )
            monitor.start()
            child.stdin.write(frame)
            child.stdin.close()
            captured, _, code = _collect(child, request, cancelled=monitor.stop_requested.is_set)
            observation = observe_process_group(child.pid, child.pid)
            if observation != OBSERVATION_EXITED:
                phase = "unknown"
            elif monitor.cancel_requested.is_set():
                phase = "cancelled"
            elif monitor.authority_unavailable.is_set():
                phase = "unknown"
            elif code != 0:
                phase = "failed"
            else:
                output = json.loads(captured)
                phase = "completed"
        except (WorkerError, NativeLaunchError, OSError, ValueError, subprocess.SubprocessError):
            # Never invent stop from a signal acknowledgement; use the recorded identity observer.
            if child.stdin is not None:
                with contextlib.suppress(OSError, ValueError):
                    child.stdin.close()
            if identity.start_token is not None:
                stopped = observe_and_stop(identity)
                observation = "exited" if stopped == OBSERVED_STOP else "unknown"
                if observation == "exited":
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        child.wait(timeout=3)
            else:
                # Reap the still-owned blocked child; this proves no process-group stop.
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
            phase = (
                "cancelled"
                if observation == "exited"
                and monitor is not None
                and monitor.cancel_requested.is_set()
                else "unknown"
            )
        finally:
            if monitor is not None:
                monitor.stop()
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    with contextlib.suppress(OSError):
                        pipe.close()
        if start is None:
            return RemoteNativeResult("unknown", lease_id)
        if phase == "completed":
            payload = canonical_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "NativeReviewedTaskOutput",
                    "requestDigest": request_digest(request),
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "attemptId": request.attempt_id,
                    "output": output,
                }
            ).encode()
            result_bound = min(request.limits.artifact_bytes, MAX_WORKER_PUT_BYTES)
            if len(payload) > result_bound:
                phase = "failed"
            else:
                record = artifacts.put_bytes(payload, limit=result_bound)
                _write(root, name + ".result", {"digest": record.digest, "sizeBytes": len(payload)})
        outcome = NativeOutcomeRequest.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeOutcomeRequest",
                "start": start.model_dump(mode="json", by_alias=True, exclude_none=True),
                "observation": observation,
                "outcome": phase,
            }
        )
        _write(
            root,
            name + ".outcome",
            outcome.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        return _publish(client, artifacts, root, name, outcome, output)


def reconcile_remote_native(
    client: WorkerClient,
    *,
    artifacts: LocalArtifactStore,
    state_root: Path,
    request: NativeReviewedExecutionRequest,
) -> RemoteNativeResult:
    """Observe/replay only persisted state; never prepare, poll, or create a process."""
    name = _name(request)
    with private_state_lock(state_root, name) as root:
        intent = _read(root, name + ".intent")
        if (
            intent.get("requestDigest") != request_digest(request)
            or intent.get("request")
            != request.model_dump(mode="json", by_alias=True, exclude_none=True)
            or intent.get("workerId") != client.worker_id
            or intent.get("origin") != client.base_url.rstrip("/")
            or intent.get("tlsFingerprint") != client.tls_fingerprint
            or intent.get("tokenFingerprint")
            != hashlib.sha256(client.grant_token.encode()).hexdigest()
        ):
            raise WorkerError("native recovery intent differs", code="native-execution-binding")
        claim = _read(root, name + ".claim") if _exists(root, name + ".claim") else {}
        if not _exists(root, name + ".start") or not _exists(root, name + ".identity"):
            return RemoteNativeResult("unknown", claim.get("leaseId", ""))
        start = NativeStartRequest.model_validate(_read(root, name + ".start"))
        if (
            start.preparation.request_digest != request_digest(request)
            or start.preparation.grant_id != intent.get("grantId")
            or claim != {"leaseId": start.lease_id}
        ):
            raise WorkerError("native recovery start differs", code="native-execution-binding")
        identity_doc = _read(root, name + ".identity")
        if (
            content_digest(identity_doc) != start.identity_digest
            or identity_doc.get("leaseId") != start.lease_id
            or set(identity_doc) != {"leaseId", "pid", "pgid", "startToken", "kind"}
            or type(identity_doc.get("pid")) is not int
            or type(identity_doc.get("pgid")) is not int
            or type(identity_doc.get("startToken")) is not str
            or identity_doc.get("kind") != "posix-pg"
            or identity_doc["pid"] <= 0
            or identity_doc["pgid"] != identity_doc["pid"]
            or not identity_doc["startToken"]
        ):
            raise WorkerError("native recovery identity differs", code="native-execution-binding")
        pid, pgid = identity_doc["pid"], identity_doc["pgid"]
        observed = observe_process_group(pgid, pid)
        if (
            observed == OBSERVATION_RUNNING
            and posix_start_token(pid) != identity_doc["startToken"]
            and observe_process(pid) != OBSERVATION_EXITED
        ):
            observed = "unknown"
        # Heartbeat is transport liveness/cancel intent, never an observed stop.
        if observed == OBSERVATION_RUNNING and client.heartbeat(lease_id=start.lease_id):
            identity = ExecutionIdentity(
                start.lease_id, "posix-pg", pid, pgid, identity_doc["startToken"], None, None
            )
            observed = "exited" if observe_and_stop(identity) == OBSERVED_STOP else "unknown"
            if observed == OBSERVATION_EXITED:
                cancelled = NativeOutcomeRequest.model_validate(
                    {
                        "apiVersion": "researchos.dev/v0alpha1",
                        "kind": "NativeOutcomeRequest",
                        "start": start.model_dump(mode="json", by_alias=True, exclude_none=True),
                        "observation": "exited",
                        "outcome": "cancelled",
                    }
                )
                if not _exists(root, name + ".cancelled"):
                    _write(
                        root,
                        name + ".cancelled",
                        cancelled.model_dump(mode="json", by_alias=True, exclude_none=True),
                    )
                return _publish(client, artifacts, root, name, cancelled)
        if _exists(root, name + ".cancelled"):
            cancelled = NativeOutcomeRequest.model_validate(_read(root, name + ".cancelled"))
            if cancelled.start != start or cancelled.outcome != "cancelled":
                raise WorkerError("native cancellation differs", code="native-execution-binding")
            if observed != OBSERVATION_EXITED:
                return RemoteNativeResult("unknown", start.lease_id)
            return _publish(client, artifacts, root, name, cancelled)
        if _exists(root, name + ".outcome"):
            outcome = NativeOutcomeRequest.model_validate(_read(root, name + ".outcome"))
            if outcome.start != start:
                raise WorkerError(
                    "native recovery outcome differs", code="native-execution-binding"
                )
            if outcome.outcome != "unknown" and observed != OBSERVATION_EXITED:
                return RemoteNativeResult("unknown", start.lease_id)
            return _publish(client, artifacts, root, name, outcome)
        outcome = NativeOutcomeRequest.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeOutcomeRequest",
                "start": start.model_dump(mode="json", by_alias=True, exclude_none=True),
                "observation": observed,
                "outcome": "unknown",
            }
        )
        receipt = publish_native_outcome(client, outcome)
        return RemoteNativeResult(receipt.disposition, start.lease_id, receipt=receipt)


def _publish(
    client: WorkerClient,
    artifacts: LocalArtifactStore,
    root: int,
    name: str,
    outcome: NativeOutcomeRequest,
    output: Any = None,
) -> RemoteNativeResult:
    if outcome.outcome == "completed":
        original = NativeReviewedExecutionRequest.model_validate(
            _read(root, name + ".intent")["request"]
        )
        bound = min(original.limits.artifact_bytes, MAX_WORKER_PUT_BYTES)
        result = _read(root, name + ".result")
        if (
            set(result) != {"digest", "sizeBytes"}
            or type(result["sizeBytes"]) is not int
            or not 0 < result["sizeBytes"] <= bound
            or type(result["digest"]) is not str
            or DIGEST_PATTERN.fullmatch(result["digest"]) is None
        ):
            raise WorkerError("native result record differs", code="native-execution-binding")
        with artifacts.open(result["digest"]) as stream:
            if os.fstat(stream.fileno()).st_size != result["sizeBytes"]:
                raise WorkerError("native result bytes differ", code="native-execution-binding")
            payload = stream.read(result["sizeBytes"] + 1)
        if (
            len(payload) != result["sizeBytes"]
            or "sha256:" + hashlib.sha256(payload).hexdigest() != result["digest"]
        ):
            raise WorkerError("native result bytes differ", code="native-execution-binding")
        try:
            client.upload_native_output(lease_id=outcome.start.lease_id, payload=payload)
        except WorkerError as exc:
            if exc.code != "transfer-refused" or outcome.observation != "exited":
                raise
            # A refusal is not cancellation. Only the controller's bound cancel
            # prerequisite can settle this already-observed exit as cancelled.
            cancelled = outcome.model_copy(update={"outcome": "cancelled"})
            try:
                receipt = publish_native_outcome(client, cancelled)
            except WorkerError:
                raise exc from None
            if not _exists(root, name + ".cancelled"):
                _write(
                    root,
                    name + ".cancelled",
                    cancelled.model_dump(mode="json", by_alias=True, exclude_none=True),
                )
            return RemoteNativeResult(receipt.disposition, outcome.start.lease_id, receipt=receipt)

        output = json.loads(payload)["output"]
    receipt = publish_native_outcome(client, outcome)
    return RemoteNativeResult(receipt.disposition, outcome.start.lease_id, output, receipt)


class _Monitor:
    def __init__(
        self, client: WorkerClient, request: NativeReviewedExecutionRequest, lease_id: str
    ):
        self.client, self.request = client, request
        self.lease_id = lease_id
        self.cancel_requested = threading.Event()
        self.authority_unavailable = threading.Event()
        self.stop_requested = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="native-heartbeat")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.done.set()
        self.thread.join(timeout=0.1)

    def check(self) -> bool:
        try:
            if self.client.heartbeat(lease_id=self.lease_id):
                self.cancel_requested.set()
                self.stop_requested.set()
            elif self.client.fetch_native_request() != self.request.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ):
                self.authority_unavailable.set()
                self.stop_requested.set()
        except WorkerError as exc:
            if exc.code != "http-disconnect":
                self.authority_unavailable.set()
                self.stop_requested.set()
            return False
        return not self.stop_requested.is_set()

    def _run(self) -> None:
        while not self.done.is_set():
            self.check()
            if self.done.wait(0.5):
                return


def _name(request: NativeReviewedExecutionRequest) -> str:
    return (
        "native-"
        + hashlib.sha256(
            f"{request.project_id}:{request.run_id}:{request.attempt_id}".encode()
        ).hexdigest()
    )


def _exists(root: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _write(root: int, name: str, document: dict[str, Any]) -> None:
    payload = canonical_json(document).encode()
    if len(payload) > 65536:
        raise WorkerError("native state exceeds its bound", code="native-state-invalid")
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(root)


def _read(root: int, name: str) -> dict[str, Any]:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except OSError:
        raise WorkerError("native state is unavailable", code="native-state-invalid") from None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > 65536
        ):
            raise WorkerError("native state is unsafe", code="native-state-invalid")
        value = json.loads(os.read(descriptor, 65537))
        if type(value) is not dict:
            raise WorkerError("native state is invalid", code="native-state-invalid")
        return value
    except (OSError, ValueError, RecursionError):
        raise WorkerError("native state is invalid", code="native-state-invalid") from None
    finally:
        os.close(descriptor)
