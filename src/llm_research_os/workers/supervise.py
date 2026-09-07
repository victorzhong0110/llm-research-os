"""Observed stop of a recorded execution identity (ADR-0050).

Cancel request is not observed stop. A start token rejects PID reuse.
Container stop is not cloud-instance stop (billing).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_research_os.artifacts.store import DIGEST_PATTERN
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN
from llm_research_os.workers.errors import WorkerError

KIND_POSIX: Literal["posix-pg"] = "posix-pg"
KIND_OCI: Literal["oci-container"] = "oci-container"
OBSERVED_STOP = "observed-stop"
UNOBSERVED = "execution-unobserved"
CLOUD_INSTANCE_STOP = "cloud-instance-stop"
_IDENTITY_MODE = 0o600
_IDENTITY_DIR_MODE = 0o700
_STOP_WAIT_SECONDS = 3
_OCI_STOP_SECONDS = 2


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    lease_id: str
    kind: Literal["posix-pg", "oci-container"]
    pid: int | None
    pgid: int | None
    start_token: str | None
    container_id: str | None
    docker_executable: str | None


@dataclass(frozen=True, slots=True)
class PendingComplete:
    """Local receipt after artifact upload, before work.completed (ADR-0051)."""

    lease_id: str
    result_digest: str
    artifact_digest: str


def identity_path(identity_dir: Path, lease_id: str) -> Path:
    hex_id = lease_id.encode("utf-8").hex()
    return identity_dir / f"{hex_id}.json"


def save_execution_identity(identity_dir: Path, identity: ExecutionIdentity) -> Path:
    identity_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(identity_dir, _IDENTITY_DIR_MODE)
    path = identity_path(identity_dir, identity.lease_id)
    document = {
        "leaseId": identity.lease_id,
        "kind": identity.kind,
        "pid": identity.pid,
        "pgid": identity.pgid,
        "startToken": identity.start_token,
        "containerId": identity.container_id,
        "dockerExecutable": identity.docker_executable,
    }
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(encoded)
    os.chmod(path, _IDENTITY_MODE)
    return path


def load_execution_identity(identity_dir: Path, lease_id: str) -> ExecutionIdentity | None:
    path = identity_path(identity_dir, lease_id)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(document) is not dict:
        return None
    kind = document.get("kind")
    if kind not in {KIND_POSIX, KIND_OCI}:
        return None
    return ExecutionIdentity(
        lease_id=lease_id,
        kind=kind,
        pid=_optional_int(document.get("pid")),
        pgid=_optional_int(document.get("pgid")),
        start_token=_optional_str(document.get("startToken")),
        container_id=_optional_str(document.get("containerId")),
        docker_executable=_optional_str(document.get("dockerExecutable")),
    )


def posix_start_token(pid: int) -> str | None:
    """Linux starttime from /proc. None on Darwin — PID-only is weaker."""

    path = Path(f"/proc/{pid}/stat")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    if len(fields) < 20:
        return None
    return fields[19]


def process_still_running(pid: int) -> bool:
    """True when the pid is a live, non-zombie process."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    path = Path(f"/proc/{pid}/stat")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _ps_process_running(pid)
    close = text.rfind(")")
    if close < 0:
        return True
    fields = text[close + 1 :].split()
    if not fields:
        return True
    return fields[0] not in {"Z", "X"}


def _ps_process_running(pid: int) -> bool:
    """Darwin/other hosts without /proc: treat zombie as not running."""

    executable = shutil.which("ps")
    if executable is None:
        return True
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, "-p", str(pid), "-o", "state="],
            check=False,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if completed.returncode != 0:
        return False
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if text == "":
        return False
    return text[:1] not in {"Z", "X"}


def observe_and_stop(identity: ExecutionIdentity | None) -> str:
    """Stop the recorded executor and confirm. Never stops a cloud instance."""

    if identity is None:
        return UNOBSERVED
    if identity.kind == KIND_OCI:
        return _stop_oci_container(identity)
    if identity.kind == KIND_POSIX:
        return _stop_posix_group(identity)
    return UNOBSERVED


def drop_execution_identity(identity_dir: Path, lease_id: str) -> None:
    path = identity_path(identity_dir, lease_id)
    with suppress(OSError):
        path.unlink()


def pending_complete_path(identity_dir: Path, lease_id: str) -> Path:
    hex_id = lease_id.encode("utf-8").hex()
    return identity_dir / f"{hex_id}.pending.json"


def save_pending_complete(identity_dir: Path, pending: PendingComplete) -> Path:
    identity_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(identity_dir, _IDENTITY_DIR_MODE)
    path = pending_complete_path(identity_dir, pending.lease_id)
    document = {
        "leaseId": pending.lease_id,
        "resultDigest": pending.result_digest,
        "artifactDigest": pending.artifact_digest,
    }
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(encoded)
    os.chmod(path, _IDENTITY_MODE)
    return path


def load_pending_complete(identity_dir: Path, lease_id: str) -> PendingComplete | None:
    path = pending_complete_path(identity_dir, lease_id)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(document) is not dict:
        return None
    result_digest = document.get("resultDigest")
    artifact_digest = document.get("artifactDigest")
    if type(result_digest) is not str or type(artifact_digest) is not str:
        return None
    if re.fullmatch(SEMANTIC_DIGEST_PATTERN, result_digest) is None:
        return None
    if DIGEST_PATTERN.fullmatch(artifact_digest) is None:
        return None
    return PendingComplete(
        lease_id=lease_id,
        result_digest=result_digest,
        artifact_digest=artifact_digest,
    )


def drop_pending_complete(identity_dir: Path, lease_id: str) -> None:
    path = pending_complete_path(identity_dir, lease_id)
    with suppress(OSError):
        path.unlink()


def refuse_cloud_instance_stop(action: str) -> None:
    """Cloud VM stop/destroy is a billing action, not container stop."""

    if action == CLOUD_INSTANCE_STOP:
        raise WorkerError(
            "cloud instance stop is not container stop",
            code="cloud-instance-stop-forbidden",
        )


def _optional_int(value: object) -> int | None:
    if type(value) is int and not isinstance(value, bool) and value > 0:
        return value
    return None


def _optional_str(value: object) -> str | None:
    if type(value) is str and value != "":
        return value
    return None


def _stop_posix_group(identity: ExecutionIdentity) -> str:
    pgid = identity.pgid
    pid = identity.pid
    if pgid is None and pid is None:
        return UNOBSERVED
    if pid is not None and identity.start_token is not None:
        current = posix_start_token(pid)
        if current is not None and current != identity.start_token:
            return UNOBSERVED
    target = pgid if pgid is not None else pid
    if target is None:
        return UNOBSERVED
    if not _signal_group(target, pid, signal.SIGTERM):
        return OBSERVED_STOP if pid is None or not process_still_running(pid) else UNOBSERVED
    wait_pid = pid if pid is not None else target
    if _wait_pid_gone(wait_pid):
        return OBSERVED_STOP
    if not _signal_group(target, pid, signal.SIGKILL):
        return OBSERVED_STOP if not process_still_running(wait_pid) else UNOBSERVED
    if _wait_pid_gone(wait_pid):
        return OBSERVED_STOP
    return UNOBSERVED


def _signal_group(target: int, pid: int | None, sig: signal.Signals) -> bool:
    """Send sig to the process group. False means the group is already gone."""

    try:
        os.killpg(target, sig)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        if pid is None:
            return False
        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return False


def _wait_pid_gone(pid: int, timeout: float = _STOP_WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_still_running(pid):
            return True
        time.sleep(0.05)
    return not process_still_running(pid)


def _stop_oci_container(identity: ExecutionIdentity) -> str:
    container_id = identity.container_id
    executable = identity.docker_executable
    if container_id is None or executable is None:
        return UNOBSERVED
    running = inspect_container_running(executable, container_id)
    if running is None:
        return UNOBSERVED
    if running is False:
        remove_oci_container(executable, container_id)
        return OBSERVED_STOP
    _docker(["stop", "-t", str(_OCI_STOP_SECONDS), container_id], executable)
    running = inspect_container_running(executable, container_id)
    if running is False:
        remove_oci_container(executable, container_id)
        return OBSERVED_STOP
    _docker(["kill", container_id], executable)
    running = inspect_container_running(executable, container_id)
    if running is False:
        remove_oci_container(executable, container_id)
        return OBSERVED_STOP
    return UNOBSERVED


def inspect_container_running(executable: str, container_id: str) -> bool | None:
    completed = _docker(
        ["inspect", "--format", "{{.State.Running}}", container_id],
        executable,
    )
    if completed is None or completed.returncode != 0:
        return None
    text = completed.stdout.decode("utf-8", errors="replace").strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def remove_oci_container(executable: str, container_id: str) -> None:
    _docker(["rm", "-f", container_id], executable)


def _docker(args: list[str], executable: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(  # noqa: S603
            [executable, *args],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
