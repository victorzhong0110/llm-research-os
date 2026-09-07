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
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.workers.binding import MAX_BRICK_REQUEST_JSON_BYTES, brick_stdin_document
from llm_research_os.workers.errors import WorkerSandboxError

MAX_SANDBOX_WALL_SECONDS = 5
MAX_SANDBOX_OUTPUT_BYTES = 65_536
_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR")
_READ_CHUNK = 4_096
_REAP_WAIT_SECONDS = 2


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


def execute_python_brick(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    timeout_seconds: int = MAX_SANDBOX_WALL_SECONDS,
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
        return _run_bounded(process, payload, timeout_seconds, pgid)
    finally:
        if process is not None:
            _reap_process_group(process, pgid)
        shutil.rmtree(workspace, ignore_errors=True)


def _run_bounded(
    process: subprocess.Popen[bytes],
    payload: bytes,
    timeout_seconds: int,
    pgid: int | None,
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
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
    _reap_process_group(process, pgid)
    stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
    stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
    stdout = b"".join(stdout_chunks)
    if timed_out:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.timeout",
        )
    if overflow.is_set():
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.output-too-large",
        )
    returncode = process.poll()
    if returncode is None or returncode < 0:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.lost",
        )
    if returncode != 0:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.failed",
        )
    return _parse_report(stdout)


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
    if os.name == "posix" and target is not None:
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
