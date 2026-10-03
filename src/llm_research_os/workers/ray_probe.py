"""Finite Ray Jobs resource probes; never project-task launch or Run acceptance."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from llm_research_os.canonical import canonical_json
from llm_research_os.execution.native_transfer import _directory

RAY_PROBE_VERSION = "2.59.0"
_PROBE_MARKER = "RESEARCHOS_RAY_PROBE="
_STATUS = frozenset({"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "STOPPED"})
_CPU_SOURCE = """import json,platform,sys
value=sum(i*i for i in range(64))
print('RESEARCHOS_RAY_PROBE='+json.dumps({'device':'cpu','value':value,'python':sys.version.split()[0],'platform':platform.system()},sort_keys=True))
"""
_CUDA_SOURCE = """import json,platform,sys,torch
if not torch.cuda.is_available():
    raise SystemExit('CUDA is unavailable in the Ray job')
x=torch.ones((32,32),device='cuda')
value=float((x@x).sum().item())
torch.cuda.synchronize()
print('RESEARCHOS_RAY_PROBE='+json.dumps({'device':'cuda','value':value,'python':sys.version.split()[0],'platform':platform.system(),'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0)},sort_keys=True))
"""


class RayProbeError(ValueError):
    """Refused or interrupted probe; messages never expose credentials or backend bodies."""


@dataclass(frozen=True, slots=True)
class RayProbeObservation:
    submission_id: str
    backend_status: str
    result: dict[str, Any] | None = None
    # Backend status is not a host process-group observation or a project Run fact.
    project_task_starts: Literal[0] = 0
    lifecycle_facts_appended: Literal[0] = 0


@dataclass(frozen=True, slots=True)
class RayJobsProbe:
    endpoint: str
    token: str = field(repr=False)
    timeout_seconds: int = 10

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or re.fullmatch(r"[0-9a-f]{64}", self.token) is None
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 10
        ):
            raise RayProbeError("Ray probe requires a token-authenticated loopback endpoint")

    def submit_once(
        self, *, name: str, device: Literal["cpu", "cuda"], state_root: Path
    ) -> RayProbeObservation:
        """Submit only a fixed diagnostic, once; ambiguous POSTs retain durable intent."""
        binding = self._binding(name, device)
        with _probe_lock(state_root, binding["submission_id"]) as root:
            intent = binding["submission_id"] + ".intent"
            payload = canonical_json(binding).encode()
            if _existing_intent(root, intent, payload):
                return self._observe(binding)
            status, version = self._call("GET", "/api/version")
            if (
                status != 200
                or version.get("ray_version") != RAY_PROBE_VERSION
                or version.get("version") != "4"
            ):
                raise RayProbeError("Ray probe server version is unsupported")
            status, _ = self._call("GET", "/api/jobs/" + binding["submission_id"])
            if status != 404:
                raise RayProbeError("Ray probe identity is already present or unavailable")
            descriptor = os.open(
                intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(root)
            request = {
                key: binding[key]
                for key in ("submission_id", "entrypoint", "metadata", "runtime_env")
            }
            request.update(entrypoint_num_cpus=1, entrypoint_num_gpus=int(device == "cuda"))
            try:
                status, response = self._call("POST", "/api/jobs/", request)
                if status != 200 or response.get("submission_id") != binding["submission_id"]:
                    return RayProbeObservation(binding["submission_id"], "UNKNOWN")
                return self._observe(binding)
            except RayProbeError:
                return RayProbeObservation(binding["submission_id"], "UNKNOWN")

    def observe(
        self, *, name: str, device: Literal["cpu", "cuda"], state_root: Path
    ) -> RayProbeObservation:
        binding = self._binding(name, device)
        with _probe_lock(state_root, binding["submission_id"]) as root:
            if not _existing_intent(
                root, binding["submission_id"] + ".intent", canonical_json(binding).encode()
            ):
                raise RayProbeError("Ray probe intent is missing")
            return self._observe(binding)

    def request_stop(self, *, name: str, device: Literal["cpu", "cuda"], state_root: Path) -> bool:
        """Request vendor cancellation; a true response is not an observed stop."""
        binding = self._binding(name, device)
        with _probe_lock(state_root, binding["submission_id"]) as root:
            if not _existing_intent(
                root, binding["submission_id"] + ".intent", canonical_json(binding).encode()
            ):
                raise RayProbeError("Ray probe intent is missing")
            observation = self._observe(binding)
            if observation.backend_status != "UNKNOWN":
                status, response = self._call(
                    "POST", "/api/jobs/" + binding["submission_id"] + "/stop", {}
                )
                if status == 200 and type(response.get("stopped")) is bool:
                    return response["stopped"] is True
            return False

    def _binding(self, name: str, device: str) -> dict[str, Any]:
        if (
            type(name) is not str
            or type(device) is not str
            or re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) is None
            or device not in {"cpu", "cuda"}
        ):
            raise RayProbeError("Ray probe identity or device is invalid")
        source = _CPU_SOURCE if device == "cpu" else _CUDA_SOURCE
        command = "python -c " + shlex.quote(source)
        digest = hashlib.sha256(source.encode()).hexdigest()
        return {
            "submission_id": "researchos-probe-" + hashlib.sha256(name.encode()).hexdigest(),
            "entrypoint": command,
            "metadata": {"researchos.scope": "resource-probe", "researchos.source": digest},
            "runtime_env": {},
            "endpoint": self.endpoint.rstrip("/"),
            "tokenFingerprint": hashlib.sha256(self.token.encode()).hexdigest(),
            "device": device,
            "rayVersion": RAY_PROBE_VERSION,
        }

    def _observe(self, binding: dict[str, Any]) -> RayProbeObservation:
        ident = binding["submission_id"]
        status, info = self._call("GET", "/api/jobs/" + ident)
        if status == 404:
            # Cluster history loss or pre-submit interruption is never permission to resubmit.
            return RayProbeObservation(ident, "UNKNOWN")
        if (
            status != 200
            or info.get("submission_id") != ident
            or info.get("entrypoint") != binding["entrypoint"]
            or info.get("metadata") != binding["metadata"]
            or info.get("runtime_env") != {}
            or type(info.get("status")) is not str
            or info.get("status") not in _STATUS
        ):
            raise RayProbeError("Ray probe observation binding differs")
        backend_status = str(info["status"])
        result = None
        if backend_status == "SUCCEEDED":
            status, logs = self._call("GET", "/api/jobs/" + ident + "/logs", limit=65536)
            if status != 200 or type(logs.get("logs")) is not str:
                raise RayProbeError("Ray probe result is unavailable")
            result = _result(logs["logs"], binding["device"])
        return RayProbeObservation(ident, backend_status, result)

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, limit: int = 16384
    ) -> tuple[int, dict[str, Any]]:
        parsed = urlparse(self.endpoint)
        connection = HTTPConnection("127.0.0.1", parsed.port, timeout=self.timeout_seconds)
        try:
            connection.request(
                method,
                path,
                body=None if body is None else canonical_json(body).encode(),
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            if response.getheader("Content-Encoding") or response.getheader("Transfer-Encoding"):
                raise RayProbeError("Ray probe response encoding is unsupported")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise RayProbeError("Ray probe response exceeds its bound")
            raw = response.read(limit + 1)
            if len(raw) > limit or (length is not None and len(raw) != int(length)):
                raise RayProbeError("Ray probe response is interrupted or oversized")
            # Ray returns plain-text bodies for missing/refused jobs; never echo them.
            if response.status != 200:
                return response.status, {}
            document = json.loads(raw)
            if type(document) is not dict:
                raise RayProbeError("Ray probe response is invalid")
            return response.status, document
        except (OSError, ValueError, RecursionError):
            raise RayProbeError("Ray probe transport or response is unavailable") from None
        finally:
            connection.close()


def _result(logs: str, device: str) -> dict[str, Any]:
    lines = [
        line[len(_PROBE_MARKER) :] for line in logs.splitlines() if line.startswith(_PROBE_MARKER)
    ]
    if len(lines) != 1:
        raise RayProbeError("Ray probe result marker is missing or ambiguous")
    try:
        result = json.loads(lines[0])
        fields = {"device", "value", "python", "platform"}
        if device == "cuda":
            fields |= {"torch", "cuda", "gpu"}
        if (
            type(result) is not dict
            or set(result) != fields
            or result["device"] != device
            or type(result["value"]) not in {int, float}
            or result["value"] != (85344 if device == "cpu" else 32768)
            or any(
                type(result[key]) is not str or not 1 <= len(result[key]) <= 256
                for key in fields - {"value"}
            )
        ):
            raise ValueError("probe result differs")
        return result
    except (ValueError, RecursionError):
        raise RayProbeError("Ray probe result is invalid") from None


@contextmanager
def _probe_lock(state_root: Path, ident: str) -> Iterator[int]:
    with _directory(state_root, create=False) as root:
        _private(os.fstat(root), regular=False)
        descriptor = os.open(
            ident + ".lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=root,
        )
        try:
            _private(os.fstat(descriptor), regular=True)
            if os.fstat(descriptor).st_size != 0:
                raise RayProbeError("Ray probe lock is invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RayProbeError("Ray probe is busy") from None
            yield root
        finally:
            os.close(descriptor)


def _private(info: os.stat_result, *, regular: bool) -> None:
    if (
        info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or (regular and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))
    ):
        raise RayProbeError("Ray probe state is not private or regular")


def _existing_intent(root: int, name: str, expected: bytes) -> bool:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        _private(info, regular=True)
        if info.st_size > 4096 or os.read(descriptor, 4097) != expected:
            raise RayProbeError("Ray probe intent binding differs")
        return True
    finally:
        os.close(descriptor)
