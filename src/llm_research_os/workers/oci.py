"""OCIContainerRuntime adapter. Image identity is an immutable digest (ADR-0008).

Host Python remains a trusted helper (TM-043). This adapter is not a mock of a
container: a missing docker daemon or runc fails closed. Docker on macOS runs a
Linux VM and is not a Darwin kernel-namespace proof.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.secrets.models import SecretRef
from llm_research_os.secrets.resolve import SecretResolutionError, resolve_secret
from llm_research_os.workers.binding import MAX_BRICK_REQUEST_JSON_BYTES, brick_stdin_document
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.sandbox import (
    MAX_SANDBOX_WALL_SECONDS,
    SandboxDisposition,
    SandboxResult,
    _materialize_brick,
    _process_group,
    _reap_process_group,
    _run_bounded,
)
from llm_research_os.workers.supervise import (
    KIND_OCI,
    ExecutionIdentity,
    remove_oci_container,
    save_execution_identity,
)

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DOCKER_INFO_TIMEOUT = 3
_DOCKER_INSPECT_TIMEOUT = 5
_CIDFILE_WAIT_SECONDS = 2
DEFAULT_OCI_MEMORY_BYTES = 134_217_728
MAX_OCI_MEMORY_BYTES = 268_435_456
DEFAULT_OCI_PIDS = 64
MAX_OCI_PIDS = 128
DEFAULT_OCI_CPU_MILLIS = 1000
MAX_OCI_CPU_MILLIS = 2000
MAX_OCI_SECRETS = 8
MAX_OCI_WALL_SECONDS = 30
OCI_NETWORK_DENIED: Literal["denied"] = "denied"
OCI_CONTAINER_USER = "65534:65534"
OCI_INPUT_DIR_MODE = 0o755
OCI_INPUT_FILE_MODE = 0o444
OCI_REQUIRED_ENV = "RESEARCHOS_OCI_REQUIRED"
_CPU_LAUNCH_KEYS = frozenset(
    {"network", "memoryBytes", "pidsLimit", "cpuMillis", "wallTimeSeconds", "secrets"}
)
_FORBIDDEN_LAUNCH_KEYS = frozenset(
    {
        "capAdd",
        "devices",
        "gpus",
        "ipc",
        "mounts",
        "networkMode",
        "pid",
        "ports",
        "privileged",
        "seccomp",
        "shmSize",
        "uts",
        "volumes",
    }
)


@dataclass(frozen=True, slots=True)
class OciBackend:
    kind: Literal["docker"]
    executable: str


@dataclass(frozen=True, slots=True)
class OciSecretSlot:
    env: str
    ref: SecretRef


@dataclass(frozen=True, slots=True)
class OciLaunchPolicy:
    network: Literal["denied"]
    memory_bytes: int
    pids_limit: int
    cpu_millis: int
    wall_time_seconds: int
    secrets: tuple[OciSecretSlot, ...]
    brick_digest: str


def discover_oci_backend() -> OciBackend | None:
    """Return a live docker engine. A CLI without a daemon is not a runtime."""

    executable = shutil.which("docker")
    if executable is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            timeout=_DOCKER_INFO_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    version = completed.stdout.decode("utf-8", errors="replace").strip()
    if version == "":
        return None
    return OciBackend(kind="docker", executable=executable)


def oci_integration_required() -> bool:
    """True in the designated Linux OCI CI job. Ordinary pytest may skip."""

    return os.environ.get(OCI_REQUIRED_ENV) == "1"


def prepare_oci_input_root(workspace: Path) -> None:
    """Make `/in` traversable by UID 65534 without world-writable bits or root.

    `tempfile.mkdtemp` is mode 0700. Bind-mounting that directory at `/in` for
    `--user 65534:65534` yields EACCES (`worker.brick.failed`) on Linux docker.
    Host-python sandboxes keep 0700. Do not chmod 0777 and do not run as root.
    """

    workspace.chmod(OCI_INPUT_DIR_MODE)
    for child in workspace.iterdir():
        if child.is_file() and not child.is_symlink():
            child.chmod(OCI_INPUT_FILE_MODE)
    dir_mode = workspace.stat().st_mode & 0o777
    if dir_mode != OCI_INPUT_DIR_MODE or dir_mode & 0o002:
        raise WorkerSandboxError(
            "OCI input root must be 0755 and not world-writable",
            code="oci-mount-forbidden",
        )


def parse_oci_launch_policy(
    *,
    image_digest: str,
    config: Mapping[str, object],
    inputs: Mapping[str, object],
) -> OciLaunchPolicy:
    """Freeze the closed CPU OCI launch shape. Does not start a container."""

    if DIGEST_PATTERN.fullmatch(image_digest) is None:
        raise WorkerSandboxError("OCI image digest is invalid", code="oci-image-tag-forbidden")
    if ":" in image_digest and not image_digest.startswith("sha256:"):
        raise WorkerSandboxError("OCI image tags are forbidden", code="oci-image-tag-forbidden")
    forbidden = _FORBIDDEN_LAUNCH_KEYS.intersection(config)
    if forbidden:
        raise WorkerSandboxError(
            "OCI launch requested a forbidden host mapping",
            code="oci-mount-forbidden",
        )
    unknown = set(config) - _CPU_LAUNCH_KEYS
    if unknown:
        raise WorkerSandboxError(
            "OCI launch requested a forbidden host mapping",
            code="oci-mount-forbidden",
        )
    network = config.get("network", OCI_NETWORK_DENIED)
    if network != OCI_NETWORK_DENIED:
        raise WorkerSandboxError("OCI network must be denied", code="oci-network-forbidden")
    memory_bytes = _positive_int(
        config.get("memoryBytes", DEFAULT_OCI_MEMORY_BYTES),
        field="memoryBytes",
        maximum=MAX_OCI_MEMORY_BYTES,
    )
    pids_limit = _positive_int(
        config.get("pidsLimit", DEFAULT_OCI_PIDS),
        field="pidsLimit",
        maximum=MAX_OCI_PIDS,
    )
    cpu_millis = _positive_int(
        config.get("cpuMillis", DEFAULT_OCI_CPU_MILLIS),
        field="cpuMillis",
        maximum=MAX_OCI_CPU_MILLIS,
    )
    wall_time_seconds = _positive_int(
        config.get("wallTimeSeconds", MAX_SANDBOX_WALL_SECONDS),
        field="wallTimeSeconds",
        maximum=MAX_OCI_WALL_SECONDS,
    )
    brick = inputs.get("brickDigest")
    if type(brick) is not str or DIGEST_PATTERN.fullmatch(brick) is None:
        raise WorkerSandboxError("OCI brick digest is invalid", code="execution-binding-mismatch")
    return OciLaunchPolicy(
        network=OCI_NETWORK_DENIED,
        memory_bytes=memory_bytes,
        pids_limit=pids_limit,
        cpu_millis=cpu_millis,
        wall_time_seconds=wall_time_seconds,
        secrets=_parse_secret_slots(config.get("secrets", [])),
        brick_digest=brick,
    )


def execute_oci_python_brick(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
    backend: OciBackend | None = None,
    identity_dir: Path | None = None,
    lease_id: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> SandboxResult:
    """Run one JSON-stdio brick inside a digest-pinned OCI image."""

    request_config = dict(config or {})
    request_inputs = dict(inputs or {})
    try:
        payload = json.dumps(
            brick_stdin_document(config=request_config, inputs=request_inputs),
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
    policy = parse_oci_launch_policy(
        image_digest=image_digest,
        config=request_config,
        inputs=request_inputs,
    )
    resolved_backend = backend if backend is not None else discover_oci_backend()
    if resolved_backend is None:
        raise WorkerSandboxError("OCI runtime is not available", code="oci-runtime-missing")
    require_pinned_docker_image(resolved_backend, image_digest)
    secret_env = _resolve_secret_env(policy.secrets, environ)
    script = _materialize_brick(artifacts, policy.brick_digest)
    workspace = script.parent
    prepare_oci_input_root(workspace)
    cid_root = Path(tempfile.mkdtemp(prefix="researchos-oci-cid-"))
    cidfile = cid_root / "cid"
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    identity: ExecutionIdentity | None = None
    argv = _docker_run_argv(
        resolved_backend.executable,
        image_digest=image_digest,
        workspace=workspace,
        policy=policy,
        secret_env=secret_env,
        cidfile=cidfile,
    )
    try:
        try:
            process = subprocess.Popen(  # noqa: S603
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
        container_id = _wait_cidfile(cidfile)
        identity = _record_oci_identity(
            identity_dir,
            lease_id,
            process,
            pgid,
            container_id=container_id,
            executable=resolved_backend.executable,
        )
        return _run_bounded(
            process,
            payload,
            policy.wall_time_seconds,
            pgid,
            secret_values=tuple(secret_env.values()),
            should_cancel=should_cancel,
            identity=identity,
        )
    finally:
        if identity is not None and identity.container_id is not None:
            remove_oci_container(resolved_backend.executable, identity.container_id)
        elif cidfile.is_file():
            leftover = cidfile.read_text(encoding="utf-8").strip()
            if leftover:
                remove_oci_container(resolved_backend.executable, leftover)
        if process is not None:
            _reap_process_group(process, pgid)
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(cid_root, ignore_errors=True)


def require_pinned_docker_image(backend: OciBackend, image_digest: str) -> None:
    """Refuse tags and require the digest to identify a local image. Never pull."""

    try:
        completed = subprocess.run(  # noqa: S603
            [backend.executable, "image", "inspect", "--format", "{{json .}}", image_digest],
            check=False,
            capture_output=True,
            timeout=_DOCKER_INSPECT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerSandboxError("OCI image is not available", code="oci-image-missing") from exc
    if completed.returncode != 0:
        raise WorkerSandboxError("OCI image is not available", code="oci-image-missing")
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerSandboxError("OCI image inspect is invalid", code="oci-image-missing") from exc
    if type(document) is not dict:
        raise WorkerSandboxError("OCI image inspect is invalid", code="oci-image-missing")
    identities = _image_identities(document)
    if image_digest not in identities:
        raise WorkerSandboxError(
            "OCI image digest does not match the local image",
            code="oci-image-mismatch",
        )


def _image_identities(document: dict[str, object]) -> frozenset[str]:
    identities: set[str] = set()
    image_id = document.get("Id")
    if type(image_id) is str and DIGEST_PATTERN.fullmatch(image_id) is not None:
        identities.add(image_id)
    digests = document.get("RepoDigests")
    if type(digests) is list:
        for item in digests:
            if type(item) is not str or "@sha256:" not in item:
                continue
            digest = "sha256:" + item.rsplit("@sha256:", 1)[1]
            if DIGEST_PATTERN.fullmatch(digest) is not None:
                identities.add(digest)
    return frozenset(identities)


def _docker_run_argv(
    executable: str,
    *,
    image_digest: str,
    workspace: Path,
    policy: OciLaunchPolicy,
    secret_env: Mapping[str, str],
    cidfile: Path | None = None,
) -> list[str]:
    argv = [
        executable,
        "run",
        "-i",
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--user",
        OCI_CONTAINER_USER,
        "--security-opt",
        "no-new-privileges",
        "--memory",
        str(policy.memory_bytes),
        "--memory-swap",
        str(policy.memory_bytes),
        "--pids-limit",
        str(policy.pids_limit),
        "--cpus",
        f"{policy.cpu_millis / 1000:.3f}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16777216",  # noqa: S108  container path, not host tempfile
        "--tmpfs",
        "/out:rw,noexec,nosuid,size=8388608",
        "--mount",
        f"type=bind,src={workspace},dst=/in,readonly",
    ]
    if cidfile is not None:
        argv[2:2] = ["--cidfile", str(cidfile)]
    for name, value in secret_env.items():
        argv.extend(["-e", f"{name}={value}"])
    argv.extend([image_digest, "python", "-B", "-I", "/in/task.py"])
    return argv


def _wait_cidfile(path: Path, timeout: float = _CIDFILE_WAIT_SECONDS) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        time.sleep(0.05)
    return None


def _record_oci_identity(
    identity_dir: Path | None,
    lease_id: str | None,
    process: subprocess.Popen[bytes],
    pgid: int | None,
    *,
    container_id: str | None,
    executable: str,
) -> ExecutionIdentity | None:
    if container_id is None:
        return None
    identity = ExecutionIdentity(
        lease_id=lease_id if lease_id is not None else "unbound",
        kind=KIND_OCI,
        pid=process.pid,
        pgid=pgid,
        start_token=None,
        container_id=container_id,
        docker_executable=executable,
    )
    if identity_dir is not None and lease_id is not None:
        save_execution_identity(identity_dir, identity)
    return identity


def _parse_secret_slots(value: object) -> tuple[OciSecretSlot, ...]:
    if value in (None, []):
        return ()
    if type(value) is not list:
        raise WorkerSandboxError(
            "OCI secrets must be a JSON array",
            code="oci-secret-forbidden",
        )
    if len(value) > MAX_OCI_SECRETS:
        raise WorkerSandboxError(
            "OCI secrets exceed the closed list limit",
            code="oci-secret-forbidden",
        )
    slots: list[OciSecretSlot] = []
    names: set[str] = set()
    for item in value:
        if type(item) is not dict:
            raise WorkerSandboxError("OCI secret slot is invalid", code="oci-secret-forbidden")
        extra = set(item).difference({"env", "secretRef"})
        if extra:
            raise WorkerSandboxError("OCI secret slot is invalid", code="oci-secret-forbidden")
        env = item.get("env")
        if type(env) is not str or _ENV_NAME.fullmatch(env) is None:
            raise WorkerSandboxError("OCI secret env name is invalid", code="oci-secret-forbidden")
        if env in names:
            raise WorkerSandboxError(
                "OCI secret env names must be unique",
                code="oci-secret-forbidden",
            )
        try:
            ref = SecretRef.model_validate(item.get("secretRef"))
        except (TypeError, ValueError) as exc:
            raise WorkerSandboxError(
                "OCI secretRef is invalid",
                code="oci-secret-forbidden",
            ) from exc
        names.add(env)
        slots.append(OciSecretSlot(env=env, ref=ref))
    return tuple(slots)


def _resolve_secret_env(
    slots: tuple[OciSecretSlot, ...],
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for slot in slots:
        try:
            resolved[slot.env] = resolve_secret(slot.ref, environ=environ)
        except SecretResolutionError as exc:
            raise WorkerSandboxError(
                "OCI secret is not available",
                code="oci-secret-forbidden",
            ) from exc
    return resolved


def _positive_int(value: object, *, field: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise WorkerSandboxError(f"OCI {field} exceeds the closed limit", code="oci-resource-limit")
    return value
