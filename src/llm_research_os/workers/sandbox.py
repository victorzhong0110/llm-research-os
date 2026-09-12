"""Host-python sandbox for a CAS-pinned brick. Not NativeProcessRuntime (ADR-0008).

This is not a kernel sandbox (TM-043). Network and filesystem isolation are not
enforced. Byte limits apply while pipes are read. POSIX process groups are
reaped after the parent exits or when a bound is exceeded.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.secrets.redaction import message_without_secrets
from llm_research_os.workers.binding import MAX_BRICK_REQUEST_JSON_BYTES, brick_stdin_document
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.supervise import (
    KIND_OCI,
    KIND_POSIX,
    OBSERVED_STOP,
    UNOBSERVED,
    ExecutionIdentity,
    observe_and_stop,
    posix_start_token,
    save_execution_identity,
)

MAX_SANDBOX_WALL_SECONDS = 5
MAX_SANDBOX_OUTPUT_BYTES = 65_536
MAX_SANDBOX_DIAGNOSTICS_CHARS = 2_048
_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR")
_READ_CHUNK = 4_096
_REAP_WAIT_SECONDS = 2
_CANCEL_POLL_SECONDS = 0.2


class SandboxDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    disposition: SandboxDisposition
    stdout: bytes
    result_digest: str | None
    reason_code: str
    diagnostics: str | None = None


def execute_python_brick(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    timeout_seconds: int = MAX_SANDBOX_WALL_SECONDS,
    identity_dir: Path | None = None,
    lease_id: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> SandboxResult:
    """Run one JSON-stdio brick in a temp dir. Isolation is not kernel-enforced."""

    if type(timeout_seconds) is not int or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise WorkerSandboxError("sandbox timeout must be a positive int", code="sandbox-timeout")
    try:
        payload = json.dumps(
            brick_stdin_document(config=config, inputs=inputs),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="worker.brick.invalid-json",
        )
    if len(payload) > MAX_BRICK_REQUEST_JSON_BYTES:
        raise WorkerSandboxError(
            "python brick request exceeds size limit",
            code="brick-request-too-large",
        )
    script = _materialize_brick(artifacts, image_digest)
    workspace = script.parent
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    identity: ExecutionIdentity | None = None
    try:
        try:
            process = subprocess.Popen(  # noqa: S603
                [sys.executable, "-B", "-I", str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_sandbox_env(workspace),
                cwd=workspace,
                close_fds=True,
                start_new_session=os.name == "posix",
            )
        except OSError:
            return SandboxResult(
                disposition=SandboxDisposition.UNKNOWN,
                stdout=b"",
                result_digest=None,
                reason_code="worker.process.lost",
            )
        pgid = _process_group(process)
        identity = _record_posix_identity(identity_dir, lease_id, process, pgid)
        return _run_bounded(
            process,
            payload,
            timeout_seconds,
            pgid,
            secret_values=(),
            should_cancel=should_cancel,
            identity=identity,
        )
    finally:
        if process is not None:
            _reap_process_group(process, pgid)
        shutil.rmtree(workspace, ignore_errors=True)


def _record_posix_identity(
    identity_dir: Path | None,
    lease_id: str | None,
    process: subprocess.Popen[bytes],
    pgid: int | None,
) -> ExecutionIdentity | None:
    if identity_dir is None or lease_id is None or process.pid is None:
        return None
    identity = ExecutionIdentity(
        lease_id=lease_id,
        kind=KIND_POSIX,
        pid=process.pid,
        pgid=pgid,
        start_token=posix_start_token(process.pid),
        container_id=None,
        docker_executable=None,
    )
    save_execution_identity(identity_dir, identity)
    return identity


def _run_bounded(
    process: subprocess.Popen[bytes],
    payload: bytes,
    timeout_seconds: int,
    pgid: int | None,
    *,
    secret_values: tuple[str, ...] = (),
    should_cancel: Callable[[], bool] | None = None,
    identity: ExecutionIdentity | None = None,
) -> SandboxResult:
    overflow = threading.Event()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    try:
        if process.stdin is not None:
            process.stdin.write(payload)
            process.stdin.close()
    except OSError:
        _reap_process_group(process, pgid)
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.lost",
        )
    stdout_thread = threading.Thread(
        target=_read_bounded,
        args=(process.stdout, stdout_chunks, overflow, process, pgid),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_bounded,
        args=(process.stderr, stderr_chunks, overflow, process, pgid),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    cancelled = False
    if should_cancel is None:
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
    else:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            if should_cancel():
                cancelled = True
                break
            try:
                process.wait(timeout=min(_CANCEL_POLL_SECONDS, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    if cancelled:
        return _finish_cancelled(
            process,
            pgid,
            identity,
            stdout_thread,
            stderr_thread,
            stderr_chunks,
            secret_values,
        )
    _reap_process_group(process, pgid)
    stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
    stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
    stdout = b"".join(stdout_chunks)
    diagnostics = _redacted_diagnostics(stderr_chunks, secret_values)
    if timed_out:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.timeout",
            diagnostics=diagnostics,
        )
    if overflow.is_set():
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.output-too-large",
            diagnostics=diagnostics,
        )
    returncode = process.poll()
    if returncode is None or returncode < 0:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.lost",
            diagnostics=diagnostics,
        )
    if returncode != 0:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.failed",
            diagnostics=diagnostics,
        )
    return _parse_report(stdout)


def _finish_cancelled(
    process: subprocess.Popen[bytes],
    pgid: int | None,
    identity: ExecutionIdentity | None,
    stdout_thread: threading.Thread,
    stderr_thread: threading.Thread,
    stderr_chunks: list[bytes],
    secret_values: tuple[str, ...],
) -> SandboxResult:
    container_observed = False
    if identity is not None and identity.kind == KIND_OCI:
        outcome = observe_and_stop(identity)
        if outcome == UNOBSERVED:
            stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
            stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
            return SandboxResult(
                disposition=SandboxDisposition.UNKNOWN,
                stdout=b"",
                result_digest=None,
                reason_code=UNOBSERVED,
                diagnostics=_redacted_diagnostics(stderr_chunks, secret_values),
            )
        container_observed = outcome == OBSERVED_STOP
    _reap_process_group(process, pgid)
    stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
    stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
    diagnostics = _redacted_diagnostics(stderr_chunks, secret_values)
    if container_observed or process.poll() is not None:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="cancel-observed",
            diagnostics=diagnostics,
        )
    return SandboxResult(
        disposition=SandboxDisposition.UNKNOWN,
        stdout=b"",
        result_digest=None,
        reason_code=UNOBSERVED,
        diagnostics=diagnostics,
    )


def _redacted_diagnostics(
    chunks: list[bytes],
    secret_values: tuple[str, ...],
) -> str | None:
    if not chunks:
        return None
    text = b"".join(chunks).decode("utf-8", errors="replace")[:MAX_SANDBOX_DIAGNOSTICS_CHARS]
    if text == "":
        return None
    return message_without_secrets(text, *secret_values)


def _read_bounded(
    stream: BinaryIO | None,
    chunks: list[bytes],
    overflow: threading.Event,
    process: subprocess.Popen[bytes],
    pgid: int | None,
) -> None:
    if stream is None:
        return
    total = 0
    try:
        while True:
            data = stream.read(_READ_CHUNK)
            if not data:
                break
            if overflow.is_set():
                continue
            if total + len(data) > MAX_SANDBOX_OUTPUT_BYTES:
                remain = MAX_SANDBOX_OUTPUT_BYTES - total
                if remain > 0:
                    chunks.append(data[:remain])
                overflow.set()
                _reap_process_group(process, pgid)
                break
            chunks.append(data)
            total += len(data)
    except OSError:
        return


def _process_group(process: subprocess.Popen[bytes]) -> int | None:
    if os.name != "posix" or process.pid is None:
        return None
    try:
        return os.getpgid(process.pid)
    except OSError:
        return process.pid


def _reap_process_group(process: subprocess.Popen[bytes], pgid: int | None) -> None:
    target = pgid
    if target is None:
        target = _process_group(process)
    caller_pgid: int | None = None
    if os.name == "posix":
        with contextlib.suppress(OSError):
            caller_pgid = os.getpgid(0)
    # A child spawned without start_new_session shares pytest's group.
    # killpg(self) SIGKILLs the test runner and GitHub jobs look hung.
    if os.name == "posix" and target is not None and target != caller_pgid:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(target, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=_REAP_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            process.kill()


def _parse_report(stdout: bytes) -> SandboxResult:
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="worker.brick.invalid-json",
        )
    if type(document) is not dict or document.get("kind") != "PythonBrickReport":
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="worker.brick.invalid-report",
        )
    if document.get("status") != "ok":
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="worker.brick.failed",
        )
    return SandboxResult(
        disposition=SandboxDisposition.SUCCEEDED,
        stdout=stdout,
        result_digest=content_digest(document),
        reason_code="worker.brick.ok",
    )


def _materialize_brick(artifacts: LocalArtifactStore, image_digest: str) -> Path:
    handle = artifacts.open(image_digest)
    try:
        payload = handle.read(MAX_SANDBOX_OUTPUT_BYTES + 1)
    finally:
        handle.close()
    if len(payload) > MAX_SANDBOX_OUTPUT_BYTES:
        raise WorkerSandboxError("python brick exceeds size limit", code="brick-too-large")
    workspace = Path(tempfile.mkdtemp(prefix="researchos-sandbox-"))
    script = workspace / "task.py"
    script.write_bytes(payload)
    return script


def _sandbox_env(workspace: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _PASSTHROUGH:
        value = os.environ.get(key)
        if type(value) is str and value != "":
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["HOME"] = str(workspace)
    env["TMPDIR"] = str(workspace)
    return env
