"""One fixed Ray CPU driver for reviewed native work; backend status is observation only."""

from __future__ import annotations

import hashlib
import os
import shlex
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.native_reviewed import parse_native_reviewed_request
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_transfer import _directory
from llm_research_os.workers.native_executor import (
    RemoteNativeResult,
    _exists,
    _name,
    _read,
    _write,
    execute_remote_native,
    reconcile_remote_native,
)
from llm_research_os.workers.native_state import private_state_lock
from llm_research_os.workers.native_worker import private_native_client
from llm_research_os.workers.ray_probe import RAY_PROBE_VERSION, RayJobsProbe, RayProbeError

_STATUS = frozenset({"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "STOPPED"})


@dataclass(frozen=True, slots=True)
class RayNativeObservation:
    submission_id: str
    backend_status: str


@dataclass(frozen=True, slots=True)
class RayNativeJob:
    backend: RayJobsProbe
    request: NativeReviewedExecutionRequest
    credential_path: Path
    artifacts_root: Path
    workspace: Path
    staging_root: Path
    state_root: Path
    ray_state_root: Path

    def _binding(self) -> dict[str, Any]:
        binding = _local_binding(
            self.request,
            self.credential_path,
            self.artifacts_root,
            self.workspace,
            self.staging_root,
            self.state_root,
            self.ray_state_root,
        )
        return {
            **binding,
            "rayEndpoint": self.backend.endpoint.rstrip("/"),
            "rayTokenFingerprint": hashlib.sha256(self.backend.token.encode()).hexdigest(),
            "rayVersion": RAY_PROBE_VERSION,
        }

    def submit_once(self) -> RayNativeObservation:
        binding = self._binding()
        with private_state_lock(self.ray_state_root, binding["submissionId"]) as root:
            name = binding["submissionId"] + ".intent"
            if _exists(root, name):
                _same_intent(root, name, binding)
                return self._observe(binding)
            status, version = self.backend._call("GET", "/api/version")
            if (
                status != 200
                or version.get("ray_version") != RAY_PROBE_VERSION
                or version.get("version") != "4"
            ):
                raise RayProbeError("Ray native server version is unsupported")
            status, _ = self.backend._call("GET", "/api/jobs/" + binding["submissionId"])
            if status != 404:
                raise RayProbeError("Ray native identity is already present or unavailable")
            # TM-078: persist before the only POST, including refusal/lost response.
            _write(root, name, binding)
            payload = _vendor_job(binding)
            try:
                status, response = self.backend._call("POST", "/api/jobs/", payload)
                if status != 200 or response.get("submission_id") != binding["submissionId"]:
                    return RayNativeObservation(binding["submissionId"], "UNKNOWN")
                return self._observe(binding)
            except RayProbeError:
                return RayNativeObservation(binding["submissionId"], "UNKNOWN")

    def observe(self) -> RayNativeObservation:
        binding = self._binding()
        with private_state_lock(self.ray_state_root, binding["submissionId"]) as root:
            _same_intent(root, binding["submissionId"] + ".intent", binding)
            return self._observe(binding)

    def _observe(self, binding: dict[str, Any]) -> RayNativeObservation:
        ident = binding["submissionId"]
        status, info = self.backend._call("GET", "/api/jobs/" + ident)
        if status == 404:
            return RayNativeObservation(ident, "UNKNOWN")
        expected = _vendor_job(binding)
        if (
            status != 200
            or any(
                info.get(key) != value
                for key, value in expected.items()
                if key not in {"entrypoint_num_cpus", "entrypoint_num_gpus"}
            )
            or any(
                info[key] != expected[key]
                for key in ("entrypoint_num_cpus", "entrypoint_num_gpus")
                if key in info
            )
            or type(info.get("status")) is not str
            or info["status"] not in _STATUS
        ):
            raise RayProbeError("Ray native observation binding differs")
        return RayNativeObservation(ident, info["status"])

    def reconcile(self) -> RemoteNativeResult:
        """Observe on the compute host outside Ray; never submit/poll/create a process."""
        binding = self._binding()
        with private_state_lock(self.ray_state_root, binding["submissionId"]) as root:
            _same_intent(root, binding["submissionId"] + ".intent", binding)
            return reconcile_remote_native(
                private_native_client(self.credential_path),
                artifacts=LocalArtifactStore(self.artifacts_root),
                state_root=self.state_root,
                request=self.request,
            )


def _local_binding(
    request: NativeReviewedExecutionRequest,
    credential: Path,
    artifacts: Path,
    workspace: Path,
    staging: Path,
    state: Path,
    ray_state: Path,
) -> dict[str, Any]:
    paths = tuple(
        p.absolute() for p in (credential, artifacts, workspace, staging, state, ray_state)
    )
    if any(
        len(str(p)) > 1024 or ".." in p.parts or any(c in str(p) for c in "\n\r\x00") for p in paths
    ) or any(
        a.is_relative_to(b) for i, a in enumerate(paths) for j, b in enumerate(paths) if i != j
    ):
        raise RayProbeError("Ray native paths are invalid or overlap")
    client = private_native_client(credential)
    if client.worker_id != request.worker_id:
        raise RayProbeError("Ray native Worker differs")
    return {
        "scope": "reviewed-native-cpu",
        "resources": {"entrypoint_num_cpus": 1, "entrypoint_num_gpus": 0},
        "submissionId": "researchos-ray-" + _name(request),
        "request": request.model_dump(mode="json", by_alias=True, exclude_none=True),
        "credential": str(paths[0]),
        "artifacts": str(paths[1]),
        "workspace": str(paths[2]),
        "staging": str(paths[3]),
        "state": str(paths[4]),
        "rayState": str(paths[5]),
        "origin": client.base_url.rstrip("/"),
        "tlsFingerprint": client.tls_fingerprint,
        "workerId": client.worker_id,
        "grantFingerprint": hashlib.sha256(client.grant_token.encode()).hexdigest(),
        "host": socket.gethostname(),
        "uid": os.getuid(),
        "python": sys.executable,
        "driverDigest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _same_intent(root: int, name: str, binding: dict[str, Any]) -> None:
    if _read(root, name) != binding:
        raise RayProbeError("Ray native intent binding differs")


def _vendor_job(binding: dict[str, Any]) -> dict[str, Any]:
    digest = content_digest(binding)
    return {
        "submission_id": binding["submissionId"],
        "entrypoint": shlex.join(
            [
                binding["python"],
                "-I",
                "-m",
                "llm_research_os.workers.ray_native_job",
                str(Path(binding["rayState"]) / (binding["submissionId"] + ".intent")),
                digest,
            ]
        ),
        "metadata": {"researchos.scope": "reviewed-native-cpu", "researchos.binding": digest},
        "runtime_env": {},
        **binding["resources"],
    }


def run_driver(path: Path, digest: str) -> RemoteNativeResult:
    with _directory(path.absolute().parent, create=False) as root:
        info = os.fstat(root)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RayProbeError("Ray native intent parent is not private")
        binding = _read(root, path.name)
    if content_digest(binding) != digest:
        raise RayProbeError("Ray native driver binding differs")
    request = parse_native_reviewed_request(canonical_json(binding.get("request")).encode())
    names = ("credential", "artifacts", "workspace", "staging", "state", "rayState")
    if any(type(binding.get(key)) is not str for key in names):
        raise RayProbeError("Ray native driver paths are invalid")
    paths = tuple(Path(binding[key]) for key in names)
    local = _local_binding(request, *paths)
    if (
        set(binding) != set(local) | {"rayEndpoint", "rayTokenFingerprint", "rayVersion"}
        or any(binding[key] != value for key, value in local.items())
        or path.absolute() != paths[-1] / (local["submissionId"] + ".intent")
        or binding["rayVersion"] != RAY_PROBE_VERSION
    ):
        raise RayProbeError("Ray native driver context differs")
    return execute_remote_native(
        private_native_client(paths[0]),
        artifacts=LocalArtifactStore(paths[1]),
        workspace=paths[2],
        staging_root=paths[3],
        state_root=paths[4],
        expected_request=request,
    )


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2:
            raise RayProbeError("Ray native driver arguments are invalid")
        result = run_driver(Path(argv[0]), argv[1])
        # Do not stream task logs, credentials or unverified Ray results.
        return 0 if result.disposition == "completed" and result.receipt is not None else 1
    except Exception:
        print("Ray native driver refused or interrupted; observe retained intent", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
