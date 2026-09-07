"""Independent GPU OCI launch profile. Does not relax the CPU OCI shape.

This adapter prepares a digest-pinned docker argv for one authorized
ms-swift plan. It MUST NOT start a container or claim a GPU run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.training.gpu_bind import bind_ms_swift_gpu_command, plan_document_digest
from llm_research_os.training.requests import TrainingBackendPlan
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.sandbox import SandboxDisposition, SandboxResult

GPU_NETWORK_DENIED: Literal["denied"] = "denied"
GPU_DEVICE: Literal["nvidia.com/gpu=0"] = "nvidia.com/gpu=0"
GPU_ACCELERATOR = "cuda"
GPU_CONTAINER_USER = "65534:65534"
GPU_DATA_MOUNT: Literal["/work/data"] = "/work/data"
GPU_MODEL_MOUNT: Literal["/work/model"] = "/work/model"
GPU_OUTPUT_MOUNT: Literal["/work/output"] = "/work/output"
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
_GPU_LAUNCH_KEYS = frozenset(
    {
        "network",
        "device",
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
    memory_bytes: int
    pids_limit: int
    cpu_millis: int
    wall_time_seconds: int
    disk_bytes: int
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
    return GpuLaunchPolicy(
        network=GPU_NETWORK_DENIED,
        device=GPU_DEVICE,
        memory_bytes=_positive_int(
            config.get("memoryBytes", DEFAULT_GPU_MEMORY_BYTES),
            field="memoryBytes",
            maximum=MAX_GPU_MEMORY_BYTES,
        ),
        pids_limit=_positive_int(
            config.get("pidsLimit", DEFAULT_GPU_PIDS),
            field="pidsLimit",
            maximum=MAX_GPU_PIDS,
        ),
        cpu_millis=_positive_int(
            config.get("cpuMillis", DEFAULT_GPU_CPU_MILLIS),
            field="cpuMillis",
            maximum=MAX_GPU_CPU_MILLIS,
        ),
        wall_time_seconds=_positive_int(
            config.get("wallTimeSeconds", DEFAULT_GPU_WALL_SECONDS),
            field="wallTimeSeconds",
            maximum=MAX_GPU_WALL_SECONDS,
        ),
        disk_bytes=_positive_int(
            config.get("diskBytes", DEFAULT_GPU_DISK_BYTES),
            field="diskBytes",
            maximum=MAX_GPU_DISK_BYTES,
        ),
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
        "/tmp:rw,noexec,nosuid,size=16777216",  # noqa: S108  container path, not host tempfile
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


def command_digest_of(argv: tuple[str, ...]) -> str:
    return content_digest({"argv": list(argv)})


def _positive_int(value: object, *, field: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise WorkerSandboxError(f"GPU {field} exceeds the closed limit", code="gpu-resource-limit")
    return value
