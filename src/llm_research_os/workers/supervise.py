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
OBSERVATION_RUNNING: Literal["running"] = "running"
OBSERVATION_EXITED: Literal["exited"] = "exited"
OBSERVATION_UNKNOWN: Literal["unknown"] = "unknown"
ProcessObservation = Literal["running", "exited", "unknown"]
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

    fields = _proc_stat_fields(pid)
    if fields is None or len(fields) < 20:
        return None
    return fields[19]


def observe_process(pid: int) -> ProcessObservation:
    """running, exited, or unknown. Failed probes MUST NOT become exited."""

    if pid <= 0:
        return OBSERVATION_UNKNOWN
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return OBSERVATION_EXITED
    except PermissionError:
        return OBSERVATION_RUNNING
    except OSError:
        return OBSERVATION_UNKNOWN
    fields = _proc_stat_fields(pid)
    if fields is not None:
        return _state_observation(fields[0] if fields else "")
    if _procfs_present():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return OBSERVATION_EXITED
        except OSError:
            return OBSERVATION_UNKNOWN
        return OBSERVATION_UNKNOWN
    return _ps_observe_process(pid)


def process_still_running(pid: int) -> bool:
    """True only when observation is running. Unknown is not running."""

    return observe_process(pid) == OBSERVATION_RUNNING


def observe_process_group(pgid: int | None, leader_pid: int | None) -> ProcessObservation:
    """Group is running if any member runs. Empty confirmed group is exited."""

    if pgid is None and leader_pid is None:
        return OBSERVATION_UNKNOWN
    if pgid is not None:
        present = _process_group_present(pgid)
        if present is False:
            if leader_pid is None:
                return OBSERVATION_EXITED
            leader = observe_process(leader_pid)
            if leader == OBSERVATION_RUNNING:
                return OBSERVATION_RUNNING
            if leader == OBSERVATION_UNKNOWN:
                return OBSERVATION_UNKNOWN
            return OBSERVATION_EXITED
        members = list_process_group(pgid)
        if members is None:
            if present is True:
                return OBSERVATION_RUNNING
            if leader_pid is None:
                return OBSERVATION_UNKNOWN
            leader = observe_process(leader_pid)
            if leader == OBSERVATION_RUNNING:
                return OBSERVATION_RUNNING
            return OBSERVATION_UNKNOWN
        if not members:
            if leader_pid is None:
                return OBSERVATION_EXITED
            return observe_process(leader_pid)
        states = [observe_process(member) for member in members]
        if any(state == OBSERVATION_RUNNING for state in states):
            return OBSERVATION_RUNNING
        if any(state == OBSERVATION_UNKNOWN for state in states):
            return OBSERVATION_UNKNOWN
        return OBSERVATION_EXITED
    if leader_pid is None:
        return OBSERVATION_UNKNOWN
    return observe_process(leader_pid)


def _process_group_present(pgid: int) -> bool | None:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


def list_process_group(pgid: int) -> frozenset[int] | None:
    """Member pids, empty if none, or None when the probe cannot be interpreted."""

    if pgid <= 0:
        return None
    proc_members = _proc_group_members(pgid)
    if proc_members is not None:
        return proc_members
    if _procfs_present():
        return None
    return _pgrep_group_members(pgid)


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
    if not _identity_may_be_signaled(identity):
        return UNOBSERVED
    target = pgid if pgid is not None else pid
    if target is None:
        return UNOBSERVED
    if not _signal_group(target, pid, signal.SIGTERM):
        return _observed_if_group_exited(pgid, pid)
    if _wait_group_exited(pgid, pid):
        return OBSERVED_STOP
    if not _signal_group(target, pid, signal.SIGKILL):
        return _observed_if_group_exited(pgid, pid)
    if _wait_group_exited(pgid, pid):
        return OBSERVED_STOP
    return UNOBSERVED


def _identity_may_be_signaled(identity: ExecutionIdentity) -> bool:
    """False when a live pid cannot be matched to the recorded start token."""

    pid = identity.pid
    token = identity.start_token
    if pid is None or token is None:
        return True
    state = observe_process(pid)
    if state == OBSERVATION_EXITED:
        return True
    if state != OBSERVATION_RUNNING:
        return False
    current = posix_start_token(pid)
    return current is not None and current == token


def _observed_if_group_exited(pgid: int | None, pid: int | None) -> str:
    return OBSERVED_STOP if observe_process_group(pgid, pid) == OBSERVATION_EXITED else UNOBSERVED


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


def _wait_group_exited(
    pgid: int | None,
    pid: int | None,
    timeout: float = _STOP_WAIT_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if observe_process_group(pgid, pid) == OBSERVATION_EXITED:
            return True
        time.sleep(0.05)
    return observe_process_group(pgid, pid) == OBSERVATION_EXITED


def _procfs_present() -> bool:
    return _proc_root().is_dir()


def _proc_root() -> Path:
    return Path("/proc")


def _proc_stat_fields(pid: int) -> tuple[str, ...] | None:
    path = _proc_root() / str(pid) / "stat"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    if not fields:
        return None
    return tuple(fields)


def _state_observation(state: str) -> ProcessObservation:
    if state == "":
        return OBSERVATION_UNKNOWN
    if state[:1] in {"Z", "X"}:
        return OBSERVATION_EXITED
    return OBSERVATION_RUNNING


def _ps_observe_process(pid: int) -> ProcessObservation:
    executable = shutil.which("ps")
    if executable is None:
        return OBSERVATION_UNKNOWN
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, "-p", str(pid), "-o", "state="],
            check=False,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _recheck_kill(pid, OBSERVATION_UNKNOWN)
    if completed.returncode != 0:
        return _recheck_kill(pid, OBSERVATION_UNKNOWN)
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if text == "":
        return _recheck_kill(pid, OBSERVATION_UNKNOWN)
    observation = _state_observation(text)
    if observation == OBSERVATION_UNKNOWN:
        return _recheck_kill(pid, OBSERVATION_UNKNOWN)
    return observation


def _recheck_kill(pid: int, fallback: ProcessObservation) -> ProcessObservation:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return OBSERVATION_EXITED
    except PermissionError:
        return OBSERVATION_RUNNING
    except OSError:
        return OBSERVATION_UNKNOWN
    return fallback


def _proc_group_members(pgid: int) -> frozenset[int] | None:
    proc = _proc_root()
    if not proc.is_dir():
        return None
    members: set[int] = set()
    try:
        entries = list(proc.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fields = _proc_stat_fields(int(entry.name))
        if fields is None or len(fields) < 3:
            continue
        try:
            group = int(fields[2])
        except ValueError:
            continue
        if group == pgid:
            members.add(int(entry.name))
    return frozenset(members)


def _pgrep_group_members(pgid: int) -> frozenset[int] | None:
    executable = shutil.which("pgrep")
    argv: list[str]
    if executable is not None:
        argv = [executable, "-g", str(pgid)]
    else:
        ps = shutil.which("ps")
        if ps is None:
            return None
        argv = [ps, "-g", str(pgid), "-o", "pid="]
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            check=False,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = completed.stdout.decode("utf-8", errors="replace")
    if completed.returncode not in {0, 1}:
        return None
    if completed.returncode == 1 and text.strip() == "":
        return frozenset()
    members: set[int] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "" or not stripped.isdigit():
            continue
        members.add(int(stripped))
    if completed.returncode == 0 and not members:
        return None
    return frozenset(members)


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
