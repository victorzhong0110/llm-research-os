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
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.training.gpu_bind import bind_ms_swift_gpu_command, plan_document_digest
from llm_research_os.training.requests import TrainingBackendPlan, WslCudaTrainingPlan
from llm_research_os.training.wsl_bind import bind_ms_swift_wsl_cuda_command
from llm_research_os.training.wsl_bind import plan_document_digest as wsl_plan_document_digest
from llm_research_os.workers.errors import WorkerSandboxError
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
GPU_CONTAINER_HOME = "/tmp"  # noqa: S108  existing tmpfs; passwd HOME is /nonexistent
GPU_HF_HOME = "/tmp/hf"  # noqa: S108
GPU_HF_DATASETS_CACHE = "/tmp/hf/datasets"  # noqa: S108
GPU_CACHE_ENV: tuple[str, ...] = (
    f"HOME={GPU_CONTAINER_HOME}",
    f"HF_HOME={GPU_HF_HOME}",
    f"HF_DATASETS_CACHE={GPU_HF_DATASETS_CACHE}",
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


@dataclass(frozen=True, slots=True)
class GpuLaunchPreparation:
    docker_argv: tuple[str, ...]
    command_argv: tuple[str, ...]
    executed: bool
    gpu: str


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
        f"/tmp:rw,noexec,nosuid,size={policy.tmpfs_bytes}",  # noqa: S108  container path
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

    policy = parse_gpu_launch_policy(
        image_digest=image_digest,
        config=dict(config or {}),
        inputs=dict(inputs or {}),
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
    _prepare_gpu_output_root(output_dir)
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
            report = _cuda_training_report(output_dir, profile=policy.profile)
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
            command_argv, digest = bind_ms_swift_wsl_cuda_command(wsl_plan)
            plan_digest = wsl_plan_document_digest(wsl_plan)
        else:
            gpu_plan = TrainingBackendPlan.model_validate(document)
            command_argv, digest = bind_ms_swift_gpu_command(gpu_plan)
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
    return command_argv, digest


def _prepare_gpu_output_root(output_dir: Path) -> None:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise WorkerSandboxError("GPU output path is invalid", code="gpu-mount-forbidden")
    output_dir.chmod(0o775)
    (output_dir / "tmp").mkdir(exist_ok=True)
    (output_dir / "tmp").chmod(0o775)


def _cuda_training_report(output: Path, *, profile: str) -> dict[str, object]:
    checkpoints = _checkpoint_dirs(output)
    if not checkpoints:
        raise WorkerSandboxError(
            "GPU training produced no checkpoint",
            code="gpu-checkpoint-missing",
        )
    latest = checkpoints[-1]
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
    first = checkpoints[0]
    last = checkpoints[-1]
    first_adapter = next(
        (_file_digest(first, name) for name in _ADAPTER_NAMES if (first / name).is_file()),
        None,
    )
    last_adapter = next(
        (_file_digest(last, name) for name in _ADAPTER_NAMES if (last / name).is_file()),
        None,
    )
    updated = (
        first_adapter is not None
        and last_adapter is not None
        and (len(checkpoints) == 1 or first_adapter != last_adapter)
    )
    if not updated and len(checkpoints) > 1:
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
        "parametersUpdated": True if len(checkpoints) == 1 else updated,
        "checkpoint": {
            "path": latest.name,
            "optimizer": _has_any(latest, _OPTIMIZER_NAMES),
            "scheduler": _has_any(latest, _SCHEDULER_NAMES),
            "rng": _has_any(latest, _RNG_NAMES),
            "globalStep": global_step,
            "adapterDigest": last_adapter,
        },
        "resumeEvidence": {
            "optimizer": _has_any(latest, _OPTIMIZER_NAMES),
            "scheduler": _has_any(latest, _SCHEDULER_NAMES),
            "rng": _has_any(latest, _RNG_NAMES),
            "globalStep": global_step,
        },
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


def _has_any(directory: Path, names: tuple[str, ...]) -> bool:
    return any((directory / name).is_file() for name in names)


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
