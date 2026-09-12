"""Independent GPU OCI launch profile. Does not relax the CPU OCI shape.

``prepare_gpu_launch`` / ``execute_gpu_training`` bind and validate. They
MUST NOT start a container. ``run_gpu_training`` is the authorized Worker
execution entry and may start docker.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.training.gpu_bind import (
    ResumeMode,
    bind_ms_swift_gpu_command,
    plan_document_digest,
    resume_loads,
)
from llm_research_os.training.requests import TrainingBackendPlan, WslCudaTrainingPlan
from llm_research_os.training.wsl_bind import bind_ms_swift_wsl_cuda_command
from llm_research_os.training.wsl_bind import plan_document_digest as wsl_plan_document_digest
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.gpu_restore_observe import (
    CONTAINER_PYTHONPATH,
    OBSERVE_ENV,
    OBSERVE_FILENAME,
    OBSERVE_KIND,
)
from llm_research_os.workers.sandbox import (
    SandboxDisposition,
    SandboxResult,
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

GPU_NETWORK_DENIED: Literal["denied"] = "denied"
GPU_DEVICE: Literal["nvidia.com/gpu=0"] = "nvidia.com/gpu=0"
GPU_ACCELERATOR = "cuda"
GPU_CONTAINER_USER = "65534:65534"
GPU_CONTAINER_UID = 65534
GPU_CONTAINER_GID = 65534
GPU_CONTAINER_HOME = "/tmp"  # noqa: S108  existing tmpfs; passwd HOME is /nonexistent
GPU_HF_HOME = "/tmp/hf"  # noqa: S108
GPU_HF_DATASETS_CACHE = "/tmp/hf/datasets"  # noqa: S108
GPU_CACHE_ENV: tuple[str, ...] = (
    f"HOME={GPU_CONTAINER_HOME}",
    f"HF_HOME={GPU_HF_HOME}",
    f"HF_DATASETS_CACHE={GPU_HF_DATASETS_CACHE}",
    f"PYTHONPATH={CONTAINER_PYTHONPATH}",
    f"{OBSERVE_ENV}=1",
)
GPU_DATA_MOUNT: Literal["/work/data"] = "/work/data"
GPU_MODEL_MOUNT: Literal["/work/model"] = "/work/model"
GPU_OUTPUT_MOUNT: Literal["/work/output"] = "/work/output"
GPU_PROFILE_AUTODL: Literal["autodl-4090"] = "autodl-4090"
GPU_PROFILE_WSL2: Literal["wsl2-cuda-laptop-8g"] = "wsl2-cuda-laptop-8g"
DEFAULT_GPU_MEMORY_BYTES = 17_179_869_184
MAX_GPU_MEMORY_BYTES = 25_769_803_776
DEFAULT_GPU_PIDS = 256
MAX_GPU_PIDS = 512
DEFAULT_GPU_CPU_MILLIS = 4000
MAX_GPU_CPU_MILLIS = 8000
DEFAULT_GPU_WALL_SECONDS = 2700
MAX_GPU_WALL_SECONDS = 2700
DEFAULT_GPU_DISK_BYTES = 8_589_934_592
MAX_GPU_DISK_BYTES = 34_359_738_368
DEFAULT_GPU_TMPFS_BYTES = 16_777_216
WSL_GPU_MEMORY_BYTES = 3_221_225_472
MAX_WSL_GPU_MEMORY_BYTES = 4_294_967_296
DEFAULT_WSL_GPU_PIDS = 256
MAX_WSL_GPU_PIDS = 256
DEFAULT_WSL_GPU_CPU_MILLIS = 4000
MAX_WSL_GPU_CPU_MILLIS = 6000
DEFAULT_WSL_GPU_WALL_SECONDS = 1800
MAX_WSL_GPU_WALL_SECONDS = 1800
DEFAULT_WSL_GPU_DISK_BYTES = 8_589_934_592
MAX_WSL_GPU_DISK_BYTES = 17_179_869_184
DEFAULT_WSL_GPU_TMPFS_BYTES = 268_435_456
GPU_OUTPUT_DIR_MODE = 0o755
GPU_OUTPUT_FILE_MODE = 0o644
GPU_OUTPUT_PROBE_TIMEOUT_SECONDS = 30
GPU_OUTPUT_PROBE_DIRNAME = ".researchos-perm-probe"
GPU_OUTPUT_PROBE_MARKER = "gpu-output-probe-ok"
GPU_OUTPUT_PROBE_SOURCE = """\
import pathlib

root = pathlib.Path("/work/output")
observe = root / ".researchos"
probe = root / ".researchos-perm-probe"
payload = b"researchos-probe"

def roundtrip(directory):
    directory.mkdir(parents=True, exist_ok=True)
    src = directory / ".probe-write"
    dst = directory / ".probe-renamed"
    src.write_bytes(payload)
    if src.read_bytes() != payload:
        raise SystemExit(2)
    src.rename(dst)
    if dst.read_bytes() != payload:
        raise SystemExit(2)
    dst.unlink()

try:
    roundtrip(root)
    roundtrip(observe)
    roundtrip(probe)
    probe.rmdir()
except OSError:
    raise SystemExit(2)

for ckpt in sorted(root.glob("checkpoint-*")):
    if ckpt.is_symlink() or not ckpt.is_dir():
        continue
    readable = False
    for child in ckpt.iterdir():
        if child.is_file() and not child.is_symlink():
            try:
                with child.open("rb") as handle:
                    handle.read(1)
                readable = True
                break
            except OSError:
                continue
    if not readable:
        raise SystemExit(3)

print("gpu-output-probe-ok")
"""
_SETFACL = ("/usr/bin/setfacl", "-m")
_SUDO = "/usr/bin/sudo"
_ADAPTER_NAMES = ("adapter_model.safetensors", "adapter_model.bin")
_OPTIMIZER_NAMES = ("optimizer.pt", "optimizer.bin")
_SCHEDULER_NAMES = ("scheduler.pt", "scheduler.bin")
_RNG_NAMES = ("rng_state.pth", "rng_state.bin")
_GPU_LAUNCH_KEYS = frozenset(
    {
        "network",
        "device",
        "profile",
        "memoryBytes",
        "pidsLimit",
        "cpuMillis",
        "wallTimeSeconds",
        "diskBytes",
        "dataMount",
        "modelMount",
        "outputMount",
        "commandDigest",
        "resume",
        "checkpoint",
    }
)
_FORBIDDEN_GPU_KEYS = frozenset(
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


class _DockerExecutable(Protocol):
    @property
    def executable(self) -> str: ...


@dataclass(frozen=True, slots=True)
class GpuLaunchPolicy:
    network: Literal["denied"]
    device: Literal["nvidia.com/gpu=0"]
    profile: Literal["autodl-4090", "wsl2-cuda-laptop-8g"]
    memory_bytes: int
    pids_limit: int
    cpu_millis: int
    wall_time_seconds: int
    disk_bytes: int
    tmpfs_bytes: int
    data_mount: Literal["/work/data"]
    model_mount: Literal["/work/model"]
    output_mount: Literal["/work/output"]
    command_digest: str
    plan_digest: str
    plan_artifact_digest: str
    resume: Literal["none", "full-checkpoint", "adapter-only"]
    checkpoint: str | None


@dataclass(frozen=True, slots=True)
class GpuLaunchPreparation:
    docker_argv: tuple[str, ...]
    command_argv: tuple[str, ...]
    executed: bool
    gpu: str


def _parse_gpu_resume(
    config: Mapping[str, object],
) -> tuple[Literal["none", "full-checkpoint", "adapter-only"], str | None]:
    resume = config.get("resume", "none")
    checkpoint = config.get("checkpoint")
    parsed: Literal["none", "full-checkpoint", "adapter-only"]
    if resume == "full-checkpoint":
        parsed = "full-checkpoint"
    elif resume == "adapter-only":
        parsed = "adapter-only"
    elif resume == "none":
        parsed = "none"
    else:
        raise WorkerSandboxError("GPU resume mode is invalid", code="resume-overlay-conflict")
    if parsed == "none":
        if checkpoint is not None:
            raise WorkerSandboxError(
                "checkpoint path is forbidden when resume is none",
                code="resume-overlay-conflict",
            )
        return parsed, None
    prefix = f"{GPU_OUTPUT_MOUNT}/"
    if type(checkpoint) is not str or not checkpoint.startswith(prefix):
        raise WorkerSandboxError(
            "resume checkpoint is not under the authorized output mount",
            code="gpu-mount-forbidden",
        )
    return parsed, checkpoint


def parse_gpu_launch_policy(
    *,
    image_digest: str,
    config: Mapping[str, object],
    inputs: Mapping[str, object],
) -> GpuLaunchPolicy:
    """Freeze the closed GPU launch shape. Does not start a container."""

    if ":" in image_digest and not image_digest.startswith("sha256:"):
        raise WorkerSandboxError("OCI image tags are forbidden", code="oci-image-tag-forbidden")
    if DIGEST_PATTERN.fullmatch(image_digest) is None:
        raise WorkerSandboxError("GPU image digest is invalid", code="oci-image-tag-forbidden")
    forbidden = _FORBIDDEN_GPU_KEYS.intersection(config)
    if forbidden:
        raise WorkerSandboxError(
            "GPU launch requested a forbidden host mapping",
            code="gpu-mount-forbidden",
        )
    unknown = set(config) - _GPU_LAUNCH_KEYS
    if unknown:
        raise WorkerSandboxError(
            "GPU launch requested a forbidden host mapping",
            code="gpu-mount-forbidden",
        )
    network = config.get("network", GPU_NETWORK_DENIED)
    if network != GPU_NETWORK_DENIED:
        raise WorkerSandboxError("GPU network must be denied", code="gpu-network-forbidden")
    device = config.get("device")
    if device != GPU_DEVICE:
        raise WorkerSandboxError("GPU device is not authorized", code="gpu-device-forbidden")
    command = config.get("commandDigest")
    if type(command) is not str or re.fullmatch(SEMANTIC_DIGEST_PATTERN, command) is None:
        raise WorkerSandboxError("GPU command digest is invalid", code="execution-binding-mismatch")
    plan_digest = inputs.get("planDigest")
    if type(plan_digest) is not str or re.fullmatch(SEMANTIC_DIGEST_PATTERN, plan_digest) is None:
        raise WorkerSandboxError("GPU plan digest is invalid", code="execution-binding-mismatch")
    plan_artifact = inputs.get("planArtifactDigest")
    if type(plan_artifact) is not str or DIGEST_PATTERN.fullmatch(plan_artifact) is None:
        raise WorkerSandboxError(
            "GPU plan artifact digest is invalid",
            code="execution-binding-mismatch",
        )
    data_mount = config.get("dataMount", GPU_DATA_MOUNT)
    model_mount = config.get("modelMount", GPU_MODEL_MOUNT)
    output_mount = config.get("outputMount", GPU_OUTPUT_MOUNT)
    if data_mount != GPU_DATA_MOUNT or model_mount != GPU_MODEL_MOUNT:
        raise WorkerSandboxError("GPU mount is not authorized", code="gpu-mount-forbidden")
    if output_mount != GPU_OUTPUT_MOUNT:
        raise WorkerSandboxError("GPU mount is not authorized", code="gpu-mount-forbidden")
    resume, resume_checkpoint = _parse_gpu_resume(config)
    profile = config.get("profile", GPU_PROFILE_AUTODL)
    if profile == GPU_PROFILE_WSL2:
        closed_profile: Literal["autodl-4090", "wsl2-cuda-laptop-8g"] = GPU_PROFILE_WSL2
        memory_default, memory_max = WSL_GPU_MEMORY_BYTES, MAX_WSL_GPU_MEMORY_BYTES
        pids_default, pids_max = DEFAULT_WSL_GPU_PIDS, MAX_WSL_GPU_PIDS
        cpu_default, cpu_max = DEFAULT_WSL_GPU_CPU_MILLIS, MAX_WSL_GPU_CPU_MILLIS
        wall_default, wall_max = DEFAULT_WSL_GPU_WALL_SECONDS, MAX_WSL_GPU_WALL_SECONDS
        disk_default, disk_max = DEFAULT_WSL_GPU_DISK_BYTES, MAX_WSL_GPU_DISK_BYTES
        tmpfs_bytes = DEFAULT_WSL_GPU_TMPFS_BYTES
    elif profile == GPU_PROFILE_AUTODL:
        closed_profile = GPU_PROFILE_AUTODL
        memory_default, memory_max = DEFAULT_GPU_MEMORY_BYTES, MAX_GPU_MEMORY_BYTES
        pids_default, pids_max = DEFAULT_GPU_PIDS, MAX_GPU_PIDS
        cpu_default, cpu_max = DEFAULT_GPU_CPU_MILLIS, MAX_GPU_CPU_MILLIS
        wall_default, wall_max = DEFAULT_GPU_WALL_SECONDS, MAX_GPU_WALL_SECONDS
        disk_default, disk_max = DEFAULT_GPU_DISK_BYTES, MAX_GPU_DISK_BYTES
        tmpfs_bytes = DEFAULT_GPU_TMPFS_BYTES
    else:
        raise WorkerSandboxError("GPU profile is not authorized", code="gpu-resource-limit")
    return GpuLaunchPolicy(
        network=GPU_NETWORK_DENIED,
        device=GPU_DEVICE,
        profile=closed_profile,
        memory_bytes=_positive_int(
            config.get("memoryBytes", memory_default),
            field="memoryBytes",
            maximum=memory_max,
        ),
        pids_limit=_positive_int(
            config.get("pidsLimit", pids_default),
            field="pidsLimit",
            maximum=pids_max,
        ),
        cpu_millis=_positive_int(
            config.get("cpuMillis", cpu_default),
            field="cpuMillis",
            maximum=cpu_max,
        ),
        wall_time_seconds=_positive_int(
            config.get("wallTimeSeconds", wall_default),
            field="wallTimeSeconds",
            maximum=wall_max,
        ),
        disk_bytes=_positive_int(
            config.get("diskBytes", disk_default),
            field="diskBytes",
            maximum=disk_max,
        ),
        tmpfs_bytes=tmpfs_bytes,
        data_mount=GPU_DATA_MOUNT,
        model_mount=GPU_MODEL_MOUNT,
        output_mount=GPU_OUTPUT_MOUNT,
        command_digest=command,
        plan_digest=plan_digest,
        plan_artifact_digest=plan_artifact,
        resume=resume,
        checkpoint=resume_checkpoint,
    )


def prepare_gpu_launch(
    *,
    image_digest: str,
    policy: GpuLaunchPolicy,
    command_argv: tuple[str, ...],
    data_dir: Path,
    model_dir: Path,
    output_dir: Path,
    advertised_accelerators: tuple[str, ...] = (),
    executable: str = "docker",
) -> GpuLaunchPreparation:
    """Build docker argv for the authorized GPU shape. MUST NOT start docker."""

    if GPU_ACCELERATOR not in advertised_accelerators:
        raise WorkerSandboxError(
            "worker does not advertise the authorized GPU accelerator",
            code="accelerator-missing",
        )
    actual_command = command_digest_of(command_argv)
    if actual_command != policy.command_digest:
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    if command_argv[:2] != ("swift", "sft"):
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    if "--output_dir" not in command_argv:
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    output_index = command_argv.index("--output_dir") + 1
    if command_argv[output_index] != policy.output_mount:
        raise WorkerSandboxError(
            "GPU output location is not the authorized mount",
            code="gpu-mount-forbidden",
        )
    argv = gpu_docker_argv(
        executable,
        image_digest=image_digest,
        policy=policy,
        command_argv=command_argv,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
    )
    if "--privileged" in argv:
        raise WorkerSandboxError(
            "GPU launch requested a forbidden host mapping",
            code="gpu-mount-forbidden",
        )
    gpus_at = argv.index("--gpus")
    if argv[gpus_at + 1] != "device=0":
        raise WorkerSandboxError(
            "GPU launch requested a forbidden host mapping",
            code="gpu-device-forbidden",
        )
    return GpuLaunchPreparation(
        docker_argv=tuple(argv),
        command_argv=command_argv,
        executed=False,
        gpu="not-run",
    )


def gpu_docker_argv(
    executable: str,
    *,
    image_digest: str,
    policy: GpuLaunchPolicy,
    command_argv: tuple[str, ...],
    data_dir: Path,
    model_dir: Path,
    output_dir: Path,
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
        GPU_CONTAINER_USER,
        "--security-opt",
        "no-new-privileges",
        "--gpus",
        "device=0",
        "--memory",
        str(policy.memory_bytes),
        "--memory-swap",
        str(policy.memory_bytes),
        "--pids-limit",
        str(policy.pids_limit),
        "--cpus",
        f"{policy.cpu_millis / 1000:.3f}",
        "--tmpfs",
        f"/tmp:rw,exec,nosuid,size={policy.tmpfs_bytes}",  # noqa: S108  Triton loads .so from tmpfs
        *[item for value in GPU_CACHE_ENV for item in ("--env", value)],
        "--mount",
        f"type=bind,src={data_dir},dst={policy.data_mount},readonly",
        "--mount",
        f"type=bind,src={model_dir},dst={policy.model_mount},readonly",
        "--mount",
        f"type=bind,src={output_dir},dst={policy.output_mount}",
        image_digest,
        *command_argv,
    ]
    if cidfile is not None:
        argv[2:2] = ["--cidfile", str(cidfile)]
    return argv


def execute_gpu_training(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    advertised_accelerators: tuple[str, ...] = (),
    data_dir: Path | None = None,
    model_dir: Path | None = None,
    output_dir: Path | None = None,
) -> SandboxResult:
    """Validate the GPU execution object. MUST NOT start a container."""

    policy = parse_gpu_launch_policy(
        image_digest=image_digest,
        config=dict(config or {}),
        inputs=dict(inputs or {}),
    )
    with artifacts.open(policy.plan_artifact_digest) as handle:
        payload = handle.read()
    try:
        plan = TrainingBackendPlan.model_validate_json(payload)
    except ValidationError as exc:
        raise WorkerSandboxError(
            "GPU plan artifact is not a pinned training-backend plan",
            code="execution-binding-mismatch",
        ) from exc
    if plan_document_digest(plan) != policy.plan_digest:
        raise WorkerSandboxError(
            "GPU plan artifact does not match the authorized plan digest",
            code="execution-binding-mismatch",
        )
    command_argv, digest = bind_ms_swift_gpu_command(plan)
    if digest != policy.command_digest:
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    if data_dir is None or model_dir is None or output_dir is None:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="gpu-not-run",
        )
    prepare_gpu_launch(
        image_digest=image_digest,
        policy=policy,
        command_argv=command_argv,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
        advertised_accelerators=advertised_accelerators,
    )
    return SandboxResult(
        disposition=SandboxDisposition.FAILED,
        stdout=b"",
        result_digest=None,
        reason_code="gpu-not-run",
    )


def run_gpu_training(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    advertised_accelerators: tuple[str, ...] = (),
    data_dir: Path | None = None,
    model_dir: Path | None = None,
    output_dir: Path | None = None,
    identity_dir: Path | None = None,
    lease_id: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> SandboxResult:
    """Start the authorized GPU container. Plan/bind receipts stay not-run."""

    from llm_research_os.workers.oci import discover_oci_backend, require_pinned_docker_image

    try:
        policy = parse_gpu_launch_policy(
            image_digest=image_digest,
            config=dict(config or {}),
            inputs=dict(inputs or {}),
        )
    except WorkerSandboxError as exc:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code=exc.code,
        )
    command_argv, digest = _authorized_gpu_command(artifacts, policy)
    if digest != policy.command_digest:
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    if data_dir is None or model_dir is None or output_dir is None:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="gpu-host-dirs-missing",
        )
    prepare_gpu_launch(
        image_digest=image_digest,
        policy=policy,
        command_argv=command_argv,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
        advertised_accelerators=advertised_accelerators,
    )
    backend = discover_oci_backend()
    if backend is None:
        raise WorkerSandboxError("OCI runtime is not available", code="oci-runtime-missing")
    require_pinned_docker_image(backend, image_digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        _prepare_gpu_output_root(output_dir)
        probe_gpu_output_permissions(
            backend=backend,
            image_digest=image_digest,
            data_dir=data_dir,
            model_dir=model_dir,
            output_dir=output_dir,
        )
    except WorkerSandboxError as exc:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code=exc.code,
        )
    baseline = snapshot_gpu_checkpoints(output_dir)
    cid_root = Path(tempfile.mkdtemp(prefix="researchos-gpu-cid-"))
    cidfile = cid_root / "cid"
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    identity: ExecutionIdentity | None = None
    argv = gpu_docker_argv(
        backend.executable,
        image_digest=image_digest,
        policy=policy,
        command_argv=command_argv,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
        cidfile=cidfile,
    )
    try:
        try:
            process = subprocess.Popen(  # noqa: S603
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=output_dir,
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
        if container_id is None:
            identity = None
        else:
            identity = ExecutionIdentity(
                lease_id=lease_id if lease_id is not None else "unbound",
                kind=KIND_OCI,
                pid=process.pid,
                pgid=pgid,
                start_token=None,
                container_id=container_id,
                docker_executable=backend.executable,
            )
            if identity_dir is not None and lease_id is not None:
                save_execution_identity(identity_dir, identity)
        result = _run_bounded(
            process,
            b"",
            policy.wall_time_seconds,
            pgid,
            should_cancel=should_cancel,
            identity=identity,
        )
        training_finished = (
            result.disposition is SandboxDisposition.SUCCEEDED
            or result.reason_code
            in {
                "worker.brick.invalid-json",
                "worker.brick.invalid-report",
            }
        )
        if training_finished:
            report = _cuda_training_report(
                output_dir,
                profile=policy.profile,
                resume_mode=policy.resume,
                checkpoint_path=policy.checkpoint,
                baseline=baseline,
            )
            payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            digest_value = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
            return SandboxResult(
                disposition=SandboxDisposition.SUCCEEDED,
                stdout=payload.encode("utf-8"),
                result_digest=digest_value,
                reason_code="ok",
            )
        return result
    finally:
        if identity is not None and identity.container_id is not None:
            remove_oci_container(backend.executable, identity.container_id)
        elif cidfile.is_file():
            leftover = cidfile.read_text(encoding="utf-8").strip()
            if leftover:
                remove_oci_container(backend.executable, leftover)
        if process is not None:
            _reap_process_group(process, pgid)
        shutil.rmtree(cid_root, ignore_errors=True)


def _authorized_gpu_command(
    artifacts: LocalArtifactStore,
    policy: GpuLaunchPolicy,
) -> tuple[tuple[str, ...], str]:
    with artifacts.open(policy.plan_artifact_digest) as handle:
        payload = handle.read()
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerSandboxError(
            "GPU plan artifact is not a pinned training-backend plan",
            code="execution-binding-mismatch",
        ) from exc
    if type(document) is not dict:
        raise WorkerSandboxError(
            "GPU plan artifact is not a pinned training-backend plan",
            code="execution-binding-mismatch",
        )
    kind = document.get("kind")
    try:
        if kind == "WslCudaTrainingPlan":
            wsl_plan = WslCudaTrainingPlan.model_validate(document)
            command_argv, digest = bind_ms_swift_wsl_cuda_command(
                wsl_plan,
                resume_mode=policy.resume,
                checkpoint_path=policy.checkpoint,
            )
            plan_digest = wsl_plan_document_digest(wsl_plan)
        else:
            gpu_plan = TrainingBackendPlan.model_validate(document)
            command_argv, digest = bind_ms_swift_gpu_command(
                gpu_plan,
                resume_mode=policy.resume,
                checkpoint_path=policy.checkpoint,
            )
            plan_digest = plan_document_digest(gpu_plan)
    except ValidationError as exc:
        raise WorkerSandboxError(
            "GPU plan artifact is not a pinned training-backend plan",
            code="execution-binding-mismatch",
        ) from exc
    if plan_digest != policy.plan_digest:
        raise WorkerSandboxError(
            "GPU plan artifact does not match the authorized plan digest",
            code="execution-binding-mismatch",
        )
    if kind == "WslCudaTrainingPlan" and policy.profile != GPU_PROFILE_WSL2:
        raise WorkerSandboxError(
            "WSL CUDA plan requires the laptop resource profile",
            code="gpu-resource-limit",
        )
    if digest != policy.command_digest:
        raise WorkerSandboxError(
            "GPU command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    return command_argv, digest


def gpu_container_uid_gid() -> tuple[int, int]:
    left, right = GPU_CONTAINER_USER.split(":", 1)
    uid = int(left)
    gid = int(right)
    if uid != GPU_CONTAINER_UID or gid != GPU_CONTAINER_GID:
        raise WorkerSandboxError(
            "GPU container user must be 65534:65534",
            code="gpu-output-unwritable",
        )
    return uid, gid


def preflight_gpu_output_before_claim(
    *,
    image_digest: str,
    data_dir: Path,
    model_dir: Path,
    output_dir: Path,
) -> None:
    """Prepare ownership and probe as UID 65534 before poll/claim."""

    from llm_research_os.workers.oci import discover_oci_backend, require_pinned_docker_image

    backend = discover_oci_backend()
    if backend is None:
        raise WorkerSandboxError("OCI runtime is not available", code="oci-runtime-missing")
    require_pinned_docker_image(backend, image_digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    _prepare_gpu_output_root(output_dir)
    probe_gpu_output_permissions(
        backend=backend,
        image_digest=image_digest,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
    )


def gpu_output_probe_argv(
    executable: str,
    *,
    image_digest: str,
    data_dir: Path,
    model_dir: Path,
    output_dir: Path,
) -> list[str]:
    """Closed file-ops probe: same user, mounts, and read-only root as training.

    Does not load a model, request a GPU, or touch args.json.
    """

    return [
        executable,
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--user",
        GPU_CONTAINER_USER,
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,size=16777216",  # noqa: S108  probe tmpfs; not the training tmpfs
        "--env",
        f"HOME={GPU_CONTAINER_HOME}",
        "--mount",
        f"type=bind,src={data_dir},dst={GPU_DATA_MOUNT},readonly",
        "--mount",
        f"type=bind,src={model_dir},dst={GPU_MODEL_MOUNT},readonly",
        "--mount",
        f"type=bind,src={output_dir},dst={GPU_OUTPUT_MOUNT}",
        "--entrypoint",
        "python3",
        image_digest,
        "-I",
        "-c",
        GPU_OUTPUT_PROBE_SOURCE,
    ]


def probe_gpu_output_permissions(
    *,
    backend: _DockerExecutable,
    image_digest: str,
    data_dir: Path,
    model_dir: Path,
    output_dir: Path,
) -> None:
    """Create/write/rename/unlink probe files as 65534 inside the pinned image."""

    executable = backend.executable
    if type(executable) is not str or executable == "":
        raise WorkerSandboxError("OCI runtime is not available", code="oci-runtime-missing")
    argv = gpu_output_probe_argv(
        executable,
        image_digest=image_digest,
        data_dir=data_dir,
        model_dir=model_dir,
        output_dir=output_dir,
    )
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            check=False,
            capture_output=True,
            timeout=GPU_OUTPUT_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerSandboxError(
            "GPU output probe did not complete",
            code="gpu-output-unwritable",
        ) from exc
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = " ".join(completed.stderr.decode("utf-8", errors="replace").split())[:200]
    if completed.returncode == 3:
        raise WorkerSandboxError(
            "GPU source checkpoint is not readable by the container user",
            code="gpu-checkpoint-unreadable",
        )
    if completed.returncode != 0 or GPU_OUTPUT_PROBE_MARKER not in stdout:
        suffix = f": {stderr}" if stderr else ""
        raise WorkerSandboxError(
            "GPU output is not writable by the container user" + suffix,
            code="gpu-output-unwritable",
        )
    leftover = output_dir / GPU_OUTPUT_PROBE_DIRNAME
    if leftover.exists():
        raise WorkerSandboxError(
            "GPU output probe left leftover files",
            code="gpu-output-unwritable",
        )


def _prepare_gpu_output_root(output_dir: Path) -> None:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise WorkerSandboxError("GPU output path is invalid", code="gpu-mount-forbidden")
    uid, gid = gpu_container_uid_gid()
    if not _owned_or_granted(output_dir, uid, gid):
        raise WorkerSandboxError(
            "GPU output is not writable by the container user",
            code="gpu-output-unwritable",
        )
    _clear_world_write(output_dir)
    _ensure_gpu_dir(output_dir / "tmp")
    _install_restore_observe(output_dir)
    _write_host_code_identity(output_dir)
    _apply_gpu_output_ownership(_gpu_output_owned_paths(output_dir))


def _gpu_output_owned_paths(output_dir: Path) -> tuple[Path, ...]:
    candidates = (
        output_dir,
        output_dir / "tmp",
        output_dir / ".researchos",
        output_dir / ".researchos" / "gpu_restore_observe.py",
        output_dir / ".researchos" / "sitecustomize.py",
        output_dir / "researchos-code-identity.json",
    )
    return tuple(
        path
        for path in candidates
        if path.exists() and not path.is_symlink() and not _is_checkpoint_path(path, output_dir)
    )


def _is_checkpoint_path(path: Path, output_dir: Path) -> bool:
    try:
        relative = path.resolve().relative_to(output_dir.resolve())
    except ValueError:
        return False
    return any(part.startswith("checkpoint-") for part in relative.parts)


def _apply_gpu_output_ownership(paths: tuple[Path, ...]) -> None:
    uid, gid = gpu_container_uid_gid()
    for path in paths:
        if not _owned_or_granted(path, uid, gid):
            raise WorkerSandboxError(
                "GPU output is not writable by the container user",
                code="gpu-output-unwritable",
            )
        _clear_world_write(path)


def _owned_or_granted(path: Path, uid: int, gid: int) -> bool:
    try:
        stat_result = path.stat()
    except OSError:
        return False
    if stat_result.st_uid == uid and stat_result.st_gid == gid:
        return True
    return _grant_container_user_write(path, uid, gid)


def _grant_container_user_write(path: Path, uid: int, gid: int) -> bool:
    host_uid = os.geteuid() if hasattr(os, "geteuid") else -1
    if host_uid == 0:
        try:
            os.chown(path, uid, gid)
            return True
        except OSError:
            pass
    if _setfacl_user(path, uid):
        return True
    try:
        os.chown(path, uid, gid)
        return True
    except OSError:
        pass
    return _sudo_chown(path, uid, gid)


def _sudo_run(argv: tuple[str, ...], *, payload: bytes | None = None) -> bool:
    try:
        completed = subprocess.run(  # noqa: S603
            [_SUDO, "-n", *argv],
            check=False,
            capture_output=True,
            input=payload,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _sudo_chown(path: Path, uid: int, gid: int) -> bool:
    return _sudo_run(("/usr/bin/chown", f"{uid}:{gid}", str(path)))


def _setfacl_user(path: Path, uid: int) -> bool:
    spec = f"u:{uid}:rwx" if path.is_dir() else f"u:{uid}:rw"
    argv = [*_SETFACL, spec, str(path)]
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _ensure_gpu_dir(path: Path) -> None:
    try:
        path.mkdir(exist_ok=True)
    except OSError:
        if not _sudo_run(("/usr/bin/mkdir", "-p", str(path))):
            raise WorkerSandboxError(
                "GPU output is not writable by the container user",
                code="gpu-output-unwritable",
            ) from None
    uid, gid = gpu_container_uid_gid()
    if not _owned_or_granted(path, uid, gid):
        raise WorkerSandboxError(
            "GPU output is not writable by the container user",
            code="gpu-output-unwritable",
        )
    _clear_world_write(path)


def _install_bytes(path: Path, payload: bytes) -> None:
    try:
        path.write_bytes(payload)
        path.chmod(GPU_OUTPUT_FILE_MODE)
        return
    except OSError:
        pass
    if not _sudo_run(("/usr/bin/tee", str(path)), payload=payload):
        raise WorkerSandboxError(
            "GPU output is not writable by the container user",
            code="gpu-output-unwritable",
        )
    uid, gid = gpu_container_uid_gid()
    if not _sudo_chown(path, uid, gid):
        raise WorkerSandboxError(
            "GPU output is not writable by the container user",
            code="gpu-output-unwritable",
        )
    _sudo_run(("/usr/bin/chmod", "644", str(path)))


def _clear_world_write(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise WorkerSandboxError(
            "GPU output is not writable by the container user",
            code="gpu-output-unwritable",
        ) from exc
    if mode & 0o002 == 0:
        return
    wanted = GPU_OUTPUT_DIR_MODE if path.is_dir() else GPU_OUTPUT_FILE_MODE
    try:
        path.chmod(wanted)
        mode = path.stat().st_mode & 0o777
    except OSError:
        if _sudo_run(("/usr/bin/chmod", f"{wanted:o}", str(path))):
            try:
                mode = path.stat().st_mode & 0o777
            except OSError as exc:
                raise WorkerSandboxError(
                    "GPU output must not be world-writable",
                    code="gpu-output-unwritable",
                ) from exc
        else:
            raise WorkerSandboxError(
                "GPU output must not be world-writable",
                code="gpu-output-unwritable",
            ) from None
    if mode & 0o002:
        raise WorkerSandboxError(
            "GPU output must not be world-writable",
            code="gpu-output-unwritable",
        )


def _install_restore_observe(output_dir: Path) -> None:
    dest = output_dir / ".researchos"
    _ensure_gpu_dir(dest)
    source = Path(__file__).with_name("gpu_restore_observe.py")
    _install_bytes(dest / "gpu_restore_observe.py", source.read_bytes())
    _install_bytes(
        dest / "sitecustomize.py",
        b"import gpu_restore_observe\n\ngpu_restore_observe.install()\n",
    )


def _path_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _observe_identity() -> dict[str, object]:
    observe = Path(__file__).with_name("gpu_restore_observe.py")
    gpu = Path(__file__).resolve()
    return {
        "gpuModule": str(gpu),
        "gpuDigest": _path_digest(gpu),
        "observeModule": str(observe.resolve()),
        "observeDigest": _path_digest(observe),
        "python": sys.executable,
        "pythonPath": os.environ.get("PYTHONPATH"),
    }


def _write_host_code_identity(output_dir: Path) -> None:
    payload = {"kind": "GpuCodeIdentity", **_observe_identity()}
    path = output_dir / "researchos-code-identity.json"
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    _install_bytes(path, encoded.encode("utf-8"))


def snapshot_gpu_checkpoints(output: Path) -> dict[str, dict[str, object]]:
    """Record checkpoint digests before docker starts. Leftovers must not count."""

    snapshots: dict[str, dict[str, object]] = {}
    for directory in _checkpoint_dirs(output):
        snapshots[directory.name] = _checkpoint_fingerprint(directory)
    return snapshots


def _cuda_training_report(
    output: Path,
    *,
    profile: str,
    resume_mode: ResumeMode = "none",
    checkpoint_path: str | None = None,
    baseline: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    checkpoints = _checkpoint_dirs(output)
    if not checkpoints:
        raise WorkerSandboxError(
            "GPU training produced no checkpoint",
            code="gpu-checkpoint-missing",
        )
    this_run = _this_run_checkpoints(output, baseline)
    if baseline is not None and not this_run:
        raise WorkerSandboxError(
            "GPU training wrote no new checkpoint",
            code="gpu-checkpoint-stale",
        )
    scored = this_run if this_run else checkpoints
    latest = scored[-1]
    state = _trainer_state(latest)
    global_step = state.get("global_step")
    if type(global_step) is not int or global_step < 1:
        raise WorkerSandboxError(
            "GPU trainer global_step is missing",
            code="gpu-checkpoint-missing",
        )
    losses = _losses(state)
    if not losses or any(not math.isfinite(item) for item in losses):
        raise WorkerSandboxError("GPU training loss is not finite", code="gpu-loss-invalid")
    source_dir = _host_checkpoint_dir(output, checkpoint_path)
    source_adapter = (
        None
        if source_dir is None
        else next(
            (
                _file_digest(source_dir, name)
                for name in _ADAPTER_NAMES
                if (source_dir / name).is_file()
            ),
            None,
        )
    )
    first = scored[0]
    last = scored[-1]
    first_adapter = next(
        (_file_digest(first, name) for name in _ADAPTER_NAMES if (first / name).is_file()),
        None,
    )
    last_adapter = next(
        (_file_digest(last, name) for name in _ADAPTER_NAMES if (last / name).is_file()),
        None,
    )
    compare_first = source_adapter if source_adapter is not None else first_adapter
    if len(scored) == 1 and source_adapter is None:
        parameters_updated: bool | None = None
    else:
        parameters_updated = (
            compare_first is not None and last_adapter is not None and compare_first != last_adapter
        )
        if parameters_updated is not True:
            raise WorkerSandboxError(
                "GPU adapter bytes did not change",
                code="gpu-parameters-unchanged",
            )
    return {
        "kind": "WslCudaTrainingReport",
        "status": "ok",
        "executed": True,
        "gpu": "cuda",
        "platform": "windows-wsl2-docker-engine",
        "profile": profile,
        "globalStep": global_step,
        "losses": losses,
        "lossFinite": True,
        "parametersUpdated": parameters_updated,
        "checkpoint": {
            "path": latest.name,
            "optimizer": _has_any(latest, _OPTIMIZER_NAMES),
            "scheduler": _has_any(latest, _SCHEDULER_NAMES),
            "rng": _has_any(latest, _RNG_NAMES),
            "globalStep": global_step,
            "adapterDigest": last_adapter,
        },
        "resumeEvidence": {
            "kind": "checkpoint-state-files",
            "optimizer": _state_file(latest, _OPTIMIZER_NAMES),
            "scheduler": _state_file(latest, _SCHEDULER_NAMES),
            "rng": _state_file(latest, _RNG_NAMES),
            "trainerState": _state_file(latest, ("trainer_state.json",)),
            "globalStep": global_step,
        },
        "restore": _restore_record(
            output,
            resume_mode=resume_mode,
            checkpoint_path=checkpoint_path,
            to_step=global_step,
            this_run=this_run,
            latest=latest,
        ),
    }


def _checkpoint_dirs(output: Path) -> list[Path]:
    found = [path for path in output.glob("checkpoint-*") if path.is_dir()]
    return sorted(found, key=lambda path: _checkpoint_index(path.name))


def _checkpoint_index(name: str) -> int:
    suffix = name.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else 0


def _trainer_state(checkpoint: Path) -> dict[str, object]:
    path = checkpoint / "trainer_state.json"
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return document if type(document) is dict else {}


def _losses(state: Mapping[str, object]) -> list[float]:
    log_history = state.get("log_history")
    if type(log_history) is not list:
        return []
    values: list[float] = []
    for item in log_history:
        if type(item) is not dict:
            continue
        loss = item.get("loss")
        if type(loss) is float:
            values.append(loss)
        elif type(loss) is int:
            values.append(float(loss))
    return values


def _file_digest(directory: Path, name: str) -> str:
    payload = (directory / name).read_bytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _named_digest(directory: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        if (directory / name).is_file():
            return _file_digest(directory, name)
    return None


def _checkpoint_fingerprint(directory: Path) -> dict[str, object]:
    state_path = directory / "trainer_state.json"
    mtime_ns = state_path.stat().st_mtime_ns if state_path.is_file() else 0
    return {
        "adapter": _named_digest(directory, _ADAPTER_NAMES),
        "optimizer": _named_digest(directory, _OPTIMIZER_NAMES),
        "scheduler": _named_digest(directory, _SCHEDULER_NAMES),
        "rng": _named_digest(directory, _RNG_NAMES),
        "trainerState": _named_digest(directory, ("trainer_state.json",)),
        "mtimeNs": mtime_ns,
    }


def _this_run_checkpoints(
    output: Path, baseline: Mapping[str, Mapping[str, object]] | None
) -> list[Path]:
    current = _checkpoint_dirs(output)
    if baseline is None:
        return []
    produced: list[Path] = []
    for directory in current:
        before = baseline.get(directory.name)
        after = _checkpoint_fingerprint(directory)
        if before is None:
            produced.append(directory)
            continue
        digest_keys = ("adapter", "optimizer", "scheduler", "rng", "trainerState")
        if any(before.get(key) != after.get(key) for key in digest_keys):
            produced.append(directory)
            continue
        before_mtime = before.get("mtimeNs")
        after_mtime = after.get("mtimeNs")
        if type(before_mtime) is int and type(after_mtime) is int and after_mtime > before_mtime:
            produced.append(directory)
    return produced


def _logging_step_markers(output: Path) -> tuple[str, ...]:
    path = output / "logging.jsonl"
    if not path.is_file():
        return ()
    markers: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for line in lines:
        if not line.strip():
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(document) is not dict:
            continue
        marker = document.get("global_step/max_steps")
        if type(marker) is str and marker != "":
            markers.append(marker)
    return tuple(markers)


def _has_any(directory: Path, names: tuple[str, ...]) -> bool:
    return any((directory / name).is_file() for name in names)


def _state_file(directory: Path, names: tuple[str, ...]) -> dict[str, object]:
    for name in names:
        if (directory / name).is_file():
            return {"present": True, "name": name}
    return {"present": False, "name": None}


def _host_checkpoint_dir(output: Path, mount_path: str | None) -> Path | None:
    prefix = f"{GPU_OUTPUT_MOUNT}/"
    if mount_path is None or not mount_path.startswith(prefix):
        return None
    directory = output / mount_path[len(prefix) :]
    if directory.is_dir():
        return directory
    return None


def _restore_record(
    output: Path,
    *,
    resume_mode: ResumeMode,
    checkpoint_path: str | None,
    to_step: int,
    this_run: list[Path],
    latest: Path,
) -> dict[str, object]:
    if resume_mode == "none":
        return {
            "executed": False,
            "status": "unverified",
            "source": None,
            "requestedLoads": [],
            "observedLoads": {},
            "fromStep": None,
            "toStep": None,
            "loadBasis": None,
            "thisRunCheckpoints": [path.name for path in this_run],
            "sourceDigest": None,
            "observeIdentity": _observe_identity(),
        }
    requested = list(resume_loads(resume_mode))
    load_basis = (
        "argv --resume_from_checkpoint (requested)"
        if resume_mode == "full-checkpoint"
        else "argv --adapters (requested)"
    )
    source_dir = _host_checkpoint_dir(output, checkpoint_path)
    from_step: int | None = None
    source_digest: dict[str, object] | None = None
    if source_dir is not None:
        step = _trainer_state(source_dir).get("global_step")
        if type(step) is int:
            from_step = step
        source_digest = {
            "adapter": _named_digest(source_dir, _ADAPTER_NAMES),
            "optimizer": _named_digest(source_dir, _OPTIMIZER_NAMES),
            "scheduler": _named_digest(source_dir, _SCHEDULER_NAMES),
            "rng": _named_digest(source_dir, _RNG_NAMES),
            "trainerState": _named_digest(source_dir, ("trainer_state.json",)),
        }
    observed = _observe_restore_loads(
        output,
        requested=requested,
        from_step=from_step,
        to_step=to_step,
        source_digest=source_digest,
        this_run=this_run,
        latest=latest,
    )
    verified = [name for name, item in observed.items() if item.get("status") == "verified"]
    if requested and set(verified) >= set(requested):
        status = "verified"
    elif verified:
        status = "partial"
    else:
        status = "unverified"
    return {
        "executed": True,
        "status": status,
        "source": checkpoint_path,
        "requestedLoads": requested,
        "observedLoads": observed,
        "fromStep": from_step,
        "toStep": to_step,
        "loadBasis": load_basis,
        "thisRunCheckpoints": [path.name for path in this_run],
        "sourceDigest": source_digest,
        "observeIdentity": _observe_identity(),
    }


def _observe_restore_loads(
    output: Path,
    *,
    requested: list[str],
    from_step: int | None,
    to_step: int,
    source_digest: dict[str, object] | None,
    this_run: list[Path],
    latest: Path,
) -> dict[str, dict[str, object]]:
    observed: dict[str, dict[str, object]] = {}
    markers = _logging_step_markers(output)
    expected = f"{from_step + 1}/{to_step}" if type(from_step) is int else None
    latest_fp = _checkpoint_fingerprint(latest)
    produced_latest = latest in this_run
    for name in requested:
        if name == "global_step":
            if expected is not None and markers[:1] == (expected,):
                observed[name] = {
                    "status": "verified",
                    "basis": "logging.jsonl global_step/max_steps",
                    "detail": expected,
                }
            elif type(from_step) is int and from_step < to_step:
                observed[name] = {
                    "status": "unverified",
                    "basis": "step-growth-only",
                    "detail": f"{from_step}->{to_step}",
                }
            else:
                observed[name] = {
                    "status": "unverified",
                    "basis": "missing-logging-marker",
                    "detail": None,
                }
            continue
        if name == "weights":
            source_adapter = None if source_digest is None else source_digest.get("adapter")
            latest_adapter = latest_fp.get("adapter")
            if (
                produced_latest
                and type(source_adapter) is str
                and type(latest_adapter) is str
                and source_adapter != latest_adapter
            ):
                observed[name] = {
                    "status": "verified",
                    "basis": "source-adapter-digest vs this-run checkpoint",
                    "detail": latest.name,
                }
            else:
                observed[name] = {
                    "status": "unverified",
                    "basis": "no-this-run-adapter-diff",
                    "detail": None,
                }
            continue
        record = _observe_loaded(output, name)
        if record is not None:
            observed[name] = {
                "status": "verified",
                "basis": "trainer-load-hook",
                "detail": record["sourcePath"],
                "sourceDigest": record["sourceDigest"],
                "after": record["after"],
            }
        else:
            observed[name] = {
                "status": "unverified",
                "basis": "no-trainer-load-hook",
                "detail": None,
            }
    return observed


def _observe_loaded(output: Path, name: str) -> dict[str, object] | None:
    path = output / OBSERVE_FILENAME
    if not path.is_file():
        return None
    chosen: dict[str, object] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(document) is not dict:
            continue
        if document.get("kind") != OBSERVE_KIND:
            continue
        if document.get("phase") != "loaded":
            continue
        if document.get("name") != name:
            continue
        source = document.get("sourcePath")
        digest = document.get("sourceDigest")
        after = document.get("after")
        if type(source) is not str or source == "":
            continue
        if type(digest) is not str or not digest.startswith("sha256:"):
            continue
        if type(after) is not dict or not after:
            continue
        chosen = document
    return chosen


def command_digest_of(argv: tuple[str, ...]) -> str:
    return content_digest({"argv": list(argv)})


def _wait_cidfile(path: Path, timeout: float = 5.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        time.sleep(0.05)
    return None


def _positive_int(value: object, *, field: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise WorkerSandboxError(f"GPU {field} exceeds the closed limit", code="gpu-resource-limit")
    return value
