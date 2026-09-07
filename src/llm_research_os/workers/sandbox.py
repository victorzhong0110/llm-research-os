"""Host-python sandbox for a CAS-pinned brick. Not NativeProcessRuntime (ADR-0008)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.workers.errors import WorkerSandboxError

BRICK_REQUEST = {
    "apiVersion": "researchos.dev/v0alpha1",
    "kind": "PythonBrickRequest",
    "config": {},
    "inputs": {},
}
MAX_SANDBOX_WALL_SECONDS = 5
MAX_SANDBOX_OUTPUT_BYTES = 65_536
_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR")


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
    timeout_seconds: int = MAX_SANDBOX_WALL_SECONDS,
) -> SandboxResult:
    """Run one JSON-stdio brick in an isolated temp dir. Network is not kernel-enforced."""

    if type(timeout_seconds) is not int or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise WorkerSandboxError("sandbox timeout must be a positive int", code="sandbox-timeout")
    script = _materialize_brick(artifacts, image_digest)
    workspace = script.parent
    try:
        payload = json.dumps(BRICK_REQUEST, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-B", "-I", str(script)],
            input=payload,
            capture_output=True,
            timeout=timeout_seconds,
            env=_sandbox_env(workspace),
            cwd=workspace,
            check=False,
            close_fds=True,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.timeout",
        )
    except OSError:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.lost",
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    if completed.returncode < 0:
        return SandboxResult(
            disposition=SandboxDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="worker.process.lost",
        )
    if completed.returncode != 0:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=completed.stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.failed",
        )
    stdout = completed.stdout
    if len(stdout) > MAX_SANDBOX_OUTPUT_BYTES:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=stdout[:MAX_SANDBOX_OUTPUT_BYTES],
            result_digest=None,
            reason_code="worker.brick.output-too-large",
        )
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
