"""Independent macOS/MPS native-process training profile.

This is not NativeProcessRuntime (ADR-0008 / ADR-0034) and does not inherit
OCI isolation (TM-045 / TM-057). Isolation is a POSIX process group, a
minimal environment allowlist, a closed workspace cwd, offline Hub flags,
and a wall-time bound. There is no namespace, cgroup, seccomp, or mount
jail. CPU fallback is fail-closed unless the probe reports MPS.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, content_digest
from llm_research_os.training.checkpoint import (
    MAX_MPS_CHECKPOINT_FILES,
    MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
    MAX_MPS_SNAPSHOT_FILE_BYTES,
    collect_output_artifacts,
    list_tree_files,
    tree_digest,
)
from llm_research_os.training.mps_bind import (
    MPS_MODEL_DIR,
    MPS_OUTPUT_DIR,
    bind_ms_swift_mps_command,
    plan_document_digest,
)
from llm_research_os.training.requests import MacMpsTrainingPlan
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.sandbox import (
    SandboxDisposition,
    SandboxResult,
    _process_group,
    _reap_process_group,
)
from llm_research_os.workers.supervise import (
    KIND_POSIX,
    OBSERVED_STOP,
    UNOBSERVED,
    ExecutionIdentity,
    observe_and_stop,
    posix_start_token,
    save_execution_identity,
)

MPS_ACCELERATOR = "mps"
MPS_NETWORK_DENIED: Literal["denied"] = "denied"
MPS_ISOLATION: Literal["process-group"] = "process-group"
DEFAULT_MPS_WALL_SECONDS = 1800
MAX_MPS_WALL_SECONDS = 1800
MPS_REQUIRED_ENV = "RESEARCHOS_MPS_REQUIRED"
MPS_PYTHON_ENV = "RESEARCHOS_MPS_PYTHON"
MPS_DATA_ENV = "RESEARCHOS_MPS_DATA_DIR"
MPS_MODEL_ENV = "RESEARCHOS_MPS_MODEL_DIR"
MPS_OUTPUT_ENV = "RESEARCHOS_MPS_OUTPUT_DIR"
MPS_TMPDIR = "/tmp"  # noqa: S108  AF_UNIX path limit; not a tempfile API
_MPS_LAUNCH_KEYS = frozenset(
    {
        "network",
        "accDevice",
        "isolation",
        "commandDigest",
        "wallTimeSeconds",
        "resume",
        "checkpoint",
    }
)
_MPS_INPUT_KEYS = frozenset({"planDigest", "planArtifactDigest", "datasetDigest", "modelDigest"})
_FORBIDDEN_MPS_KEYS = frozenset(
    {
        "capAdd",
        "device",
        "devices",
        "docker",
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
_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR")
_CANCEL_POLL_SECONDS = 0.2
_REAP_WAIT_SECONDS = 2
_OPTIMIZER_NAMES = ("optimizer.pt", "optimizer.bin")
_SCHEDULER_NAMES = ("scheduler.pt", "scheduler.bin")
_RNG_NAMES = ("rng_state.pth", "rng_state.bin", "rng_state_0.pth")
_ADAPTER_NAMES = ("adapter_model.safetensors", "adapter_model.bin", "adapter_model.pt")
_FALLBACK_RE = re.compile(r"not currently implemented for the MPS device|falling back to cpu", re.I)


@dataclass(frozen=True, slots=True)
class MpsLaunchPolicy:
    network: Literal["denied"]
    acc_device: Literal["mps"]
    isolation: Literal["process-group"]
    wall_time_seconds: int
    command_digest: str
    plan_digest: str
    plan_artifact_digest: str
    dataset_digest: str
    model_digest: str
    resume: Literal["none", "full-checkpoint", "adapter-only"]
    checkpoint: str | None


@dataclass(frozen=True, slots=True)
class MpsEnvironmentReceipt:
    kind: Literal["MacMpsEnvironment"]
    backend_id: str
    backend_version: str
    python: str
    torch: str
    accelerator: str
    stub: bool


def mps_integration_required() -> bool:
    return os.environ.get(MPS_REQUIRED_ENV) == "1"


def live_environment_document(swift: Path) -> dict[str, object]:
    """Probe the extras interpreter. CPU fallback is not an MPS environment."""

    probe = _probe_device(
        swift,
        MpsEnvironmentReceipt(
            kind="MacMpsEnvironment",
            backend_id="ms-swift",
            backend_version="4.5.2",
            python="probe",
            torch="probe",
            accelerator=MPS_ACCELERATOR,
            stub=False,
        ),
    )
    if probe["device"] != MPS_ACCELERATOR:
        raise WorkerSandboxError(
            "MPS is not available; CPU fallback is not authorized",
            code="mps-unavailable",
        )
    shim = _sitecustomize_digest(swift)
    if shim is None:
        raise WorkerSandboxError(
            "MPS sitecustomize shim is missing",
            code="mps-runtime-missing",
        )
    return {
        "kind": "MacMpsEnvironment",
        "backendId": "ms-swift",
        "backendVersion": "4.5.2",
        "python": probe["python"],
        "torch": probe["torch"],
        "accelerator": MPS_ACCELERATOR,
        "stub": False,
        "probeDevice": probe["device"],
        "cpuFallbackRule": "probe device must be mps; any other device is mps-unavailable",
        "deviceMapArgv": "absent",
        "weightLoad": "cpu-then-trainer-mps",
        "tmpdir": MPS_TMPDIR,
        "sitecustomizeDigest": shim,
        "pytorchMpsFallback": "1",
    }


def parse_mps_launch_policy(
    *,
    image_digest: str,
    config: Mapping[str, object],
    inputs: Mapping[str, object],
) -> MpsLaunchPolicy:
    if DIGEST_PATTERN.fullmatch(image_digest) is None:
        raise WorkerSandboxError("MPS environment digest is invalid", code="mps-env-invalid")
    forbidden = _FORBIDDEN_MPS_KEYS.intersection(config)
    if forbidden:
        raise WorkerSandboxError(
            "MPS launch requested a forbidden host mapping",
            code="mps-isolation-forbidden",
        )
    unknown = set(config) - _MPS_LAUNCH_KEYS
    if unknown:
        raise WorkerSandboxError(
            "MPS launch requested an unknown config key",
            code="mps-isolation-forbidden",
        )
    network = config.get("network")
    acc_device = config.get("accDevice")
    isolation = config.get("isolation")
    command = config.get("commandDigest")
    plan_digest = inputs.get("planDigest")
    plan_artifact = inputs.get("planArtifactDigest")
    if network != MPS_NETWORK_DENIED:
        raise WorkerSandboxError("MPS network must be denied", code="mps-isolation-forbidden")
    if acc_device != MPS_ACCELERATOR:
        raise WorkerSandboxError("MPS accelerator must be mps", code="accelerator-missing")
    if isolation != MPS_ISOLATION:
        raise WorkerSandboxError(
            "MPS isolation must be process-group",
            code="mps-isolation-forbidden",
        )
    if type(command) is not str or re.fullmatch(SEMANTIC_DIGEST_PATTERN, command) is None:
        raise WorkerSandboxError(
            "MPS command digest is invalid",
            code="execution-binding-mismatch",
        )
    if type(plan_digest) is not str or re.fullmatch(SEMANTIC_DIGEST_PATTERN, plan_digest) is None:
        raise WorkerSandboxError(
            "MPS plan digest is invalid",
            code="execution-binding-mismatch",
        )
    if type(plan_artifact) is not str or DIGEST_PATTERN.fullmatch(plan_artifact) is None:
        raise WorkerSandboxError(
            "MPS plan artifact digest is invalid",
            code="execution-binding-mismatch",
        )
    wall = config.get("wallTimeSeconds", DEFAULT_MPS_WALL_SECONDS)
    if type(wall) is not int or isinstance(wall, bool) or wall < 1 or wall > MAX_MPS_WALL_SECONDS:
        raise WorkerSandboxError("MPS wall time is invalid", code="mps-resource-limit")
    extra_inputs = set(inputs) - _MPS_INPUT_KEYS
    if extra_inputs:
        raise WorkerSandboxError(
            "MPS launch requested an unknown input key",
            code="mps-isolation-forbidden",
        )
    dataset_digest = inputs.get("datasetDigest")
    model_digest = inputs.get("modelDigest")
    if (
        type(dataset_digest) is not str
        or re.fullmatch(SEMANTIC_DIGEST_PATTERN, dataset_digest) is None
    ):
        raise WorkerSandboxError(
            "MPS dataset digest is invalid",
            code="execution-binding-mismatch",
        )
    if type(model_digest) is not str or re.fullmatch(SEMANTIC_DIGEST_PATTERN, model_digest) is None:
        raise WorkerSandboxError(
            "MPS model digest is invalid",
            code="execution-binding-mismatch",
        )
    resume = config.get("resume", "none")
    checkpoint = config.get("checkpoint")
    parsed_resume: Literal["none", "full-checkpoint", "adapter-only"]
    if resume == "full-checkpoint":
        parsed_resume = "full-checkpoint"
    elif resume == "adapter-only":
        parsed_resume = "adapter-only"
    elif resume == "none":
        parsed_resume = "none"
    else:
        raise WorkerSandboxError("MPS resume mode is invalid", code="resume-overlay-conflict")
    resume_checkpoint: str | None = None
    if parsed_resume == "none":
        if checkpoint is not None:
            raise WorkerSandboxError(
                "checkpoint path is forbidden when resume is none",
                code="resume-overlay-conflict",
            )
    else:
        if type(checkpoint) is not str or not checkpoint.startswith("output/"):
            raise WorkerSandboxError(
                "resume checkpoint is not under the authorized output mount",
                code="mps-isolation-forbidden",
            )
        resume_checkpoint = checkpoint
    return MpsLaunchPolicy(
        network="denied",
        acc_device="mps",
        isolation="process-group",
        wall_time_seconds=wall,
        command_digest=command,
        plan_digest=plan_digest,
        plan_artifact_digest=plan_artifact,
        dataset_digest=dataset_digest,
        model_digest=model_digest,
        resume=parsed_resume,
        checkpoint=resume_checkpoint,
    )


def execute_mps_training(
    artifacts: LocalArtifactStore,
    image_digest: str,
    *,
    config: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    advertised_accelerators: tuple[str, ...] = (),
    data_dir: Path | None = None,
    model_dir: Path | None = None,
    output_dir: Path | None = None,
    interpreter: Path | None = None,
    identity_dir: Path | None = None,
    lease_id: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    timeout_seconds: int | None = None,
) -> SandboxResult:
    """Run the authorized native ms-swift argv. Does not claim OCI isolation."""

    policy = parse_mps_launch_policy(
        image_digest=image_digest,
        config=dict(config or {}),
        inputs=dict(inputs or {}),
    )
    if MPS_ACCELERATOR not in advertised_accelerators:
        raise WorkerSandboxError(
            "worker does not advertise the authorized MPS accelerator",
            code="accelerator-missing",
        )
    with artifacts.open(policy.plan_artifact_digest) as handle:
        plan_payload = handle.read()
    try:
        plan = MacMpsTrainingPlan.model_validate_json(plan_payload)
    except ValidationError as exc:
        raise WorkerSandboxError(
            "MPS plan artifact is not a closed Mac/MPS training plan",
            code="execution-binding-mismatch",
        ) from exc
    if plan_document_digest(plan) != policy.plan_digest:
        raise WorkerSandboxError(
            "MPS plan artifact does not match the authorized plan digest",
            code="execution-binding-mismatch",
        )
    command_argv, digest = bind_ms_swift_mps_command(
        plan,
        resume_mode=policy.resume,
        checkpoint_path=policy.checkpoint,
    )
    if digest != policy.command_digest:
        raise WorkerSandboxError(
            "MPS command is not the authorized plan argv",
            code="execution-binding-mismatch",
        )
    with artifacts.open(image_digest) as handle:
        env_payload = handle.read()
    environment = _parse_environment(env_payload)
    data = _resolve_dir(data_dir, MPS_DATA_ENV, "data")
    model = _resolve_dir(model_dir, MPS_MODEL_ENV, "model")
    output = _resolve_dir(output_dir, MPS_OUTPUT_ENV, "output")
    swift = _resolve_swift(interpreter)
    workspace = _require_workspace(model, data, output)
    dataset_file = data / "sft.jsonl"
    if not dataset_file.is_file():
        raise WorkerSandboxError("MPS dataset file is missing", code="snapshot-path-invalid")
    expected_data = tree_digest(
        list_tree_files(
            data,
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_SNAPSHOT_FILE_BYTES,
        )
    )
    if expected_data != policy.dataset_digest:
        raise WorkerSandboxError(
            "MPS dataset tree digest does not match the authorized binding",
            code="execution-binding-mismatch",
        )
    expected_model = tree_digest(
        list_tree_files(
            model,
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_SNAPSHOT_FILE_BYTES,
        )
    )
    if expected_model != policy.model_digest:
        raise WorkerSandboxError(
            "MPS model tree digest does not match the authorized binding",
            code="execution-binding-mismatch",
        )
    probe = _probe_device(swift, environment)
    if probe["device"] != "mps":
        raise WorkerSandboxError(
            "MPS is not available; CPU fallback is not authorized",
            code="mps-unavailable",
        )
    output.mkdir(parents=True, exist_ok=True)
    wall = policy.wall_time_seconds if timeout_seconds is None else timeout_seconds
    if type(wall) is not int or isinstance(wall, bool) or wall < 1:
        raise WorkerSandboxError("MPS wall time is invalid", code="mps-resource-limit")
    log_path = output / "train.log"
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    identity: ExecutionIdentity | None = None
    started = time.monotonic()
    peak_rss = 0
    try:
        with log_path.open("wb") as log:
            try:
                process = subprocess.Popen(  # noqa: S603
                    list(command_argv),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=_mps_env(workspace, swift),
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
            identity = _record_posix_identity(identity_dir, lease_id, process, pgid)
            timed_out = False
            cancelled = False
            deadline = time.monotonic() + wall
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    break
                peak_rss = max(peak_rss, _rss_bytes(process.pid))
                try:
                    process.wait(timeout=min(_CANCEL_POLL_SECONDS, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        if cancelled:
            return _finish_cancelled(process, pgid, identity)
        _reap_process_group(process, pgid)
        if timed_out:
            return SandboxResult(
                disposition=SandboxDisposition.UNKNOWN,
                stdout=b"",
                result_digest=None,
                reason_code="worker.process.timeout",
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
                stdout=b"",
                result_digest=None,
                reason_code="worker.brick.failed",
                diagnostics=_log_tail(log_path),
            )
        report = _training_report(
            output,
            plan=plan,
            probe=probe,
            environment=environment,
            wall_seconds=time.monotonic() - started,
            peak_rss_bytes=peak_rss,
            log_path=log_path,
        )
        payload = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        collect_output_artifacts(
            output,
            artifacts,
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
            max_upload_bytes=MAX_MPS_CHECKPOINT_UPLOAD_BYTES,
        )
        return SandboxResult(
            disposition=SandboxDisposition.SUCCEEDED,
            stdout=payload,
            result_digest=content_digest(report),
            reason_code="worker.brick.ok",
        )
    finally:
        if process is not None:
            _reap_process_group(process, pgid)


def _parse_environment(payload: bytes) -> MpsEnvironmentReceipt:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerSandboxError(
            "MPS environment receipt is invalid",
            code="mps-env-invalid",
        ) from exc
    if type(document) is not dict or document.get("kind") != "MacMpsEnvironment":
        raise WorkerSandboxError("MPS environment receipt is invalid", code="mps-env-invalid")
    backend_id = document.get("backendId")
    backend_version = document.get("backendVersion")
    python = document.get("python")
    torch = document.get("torch")
    accelerator = document.get("accelerator")
    stub = document.get("stub", False)
    if (
        backend_id != "ms-swift"
        or backend_version != "4.5.2"
        or type(python) is not str
        or type(torch) is not str
        or accelerator != MPS_ACCELERATOR
        or type(stub) is not bool
    ):
        raise WorkerSandboxError("MPS environment receipt is invalid", code="mps-env-invalid")
    return MpsEnvironmentReceipt(
        kind="MacMpsEnvironment",
        backend_id=backend_id,
        backend_version=backend_version,
        python=python,
        torch=torch,
        accelerator=accelerator,
        stub=stub,
    )


def _resolve_dir(value: Path | None, env_name: str, role: str) -> Path:
    if value is not None:
        return value
    raw = os.environ.get(env_name)
    if type(raw) is not str or raw == "":
        raise WorkerSandboxError(f"MPS {role} directory is missing", code="mps-workspace-missing")
    return Path(raw)


def _resolve_swift(interpreter: Path | None) -> Path:
    if interpreter is not None:
        return interpreter
    raw = os.environ.get(MPS_PYTHON_ENV)
    if type(raw) is str and raw != "":
        python = Path(raw)
        sibling = python.parent / "swift"
        if sibling.is_file():
            return sibling
        return python
    found = shutil.which("swift")
    if found is None:
        raise WorkerSandboxError("MPS swift interpreter is missing", code="mps-runtime-missing")
    return Path(found)


def _require_workspace(model_dir: Path, data_dir: Path, output_dir: Path) -> Path:
    workspace = output_dir.resolve().parent
    if model_dir.resolve() != (workspace / MPS_MODEL_DIR).resolve():
        raise WorkerSandboxError(
            "MPS model directory is not workspace/model",
            code="mps-workspace-missing",
        )
    if data_dir.resolve() != (workspace / "data").resolve():
        raise WorkerSandboxError(
            "MPS data directory is not workspace/data",
            code="mps-workspace-missing",
        )
    if output_dir.resolve() != (workspace / MPS_OUTPUT_DIR).resolve():
        raise WorkerSandboxError(
            "MPS output directory is not workspace/output",
            code="mps-workspace-missing",
        )
    if workspace.is_symlink() or model_dir.is_symlink() or data_dir.is_symlink():
        raise WorkerSandboxError(
            "MPS workspace must not be a symlink",
            code="snapshot-symlink-forbidden",
        )
    return workspace


def _probe_device(swift: Path, environment: MpsEnvironmentReceipt) -> dict[str, str]:
    if environment.stub or (swift.parent / ".mps-stub").exists():
        return {
            "device": "mps",
            "torch": environment.torch,
            "swift": environment.backend_version,
            "python": environment.python,
            "stub": "true",
        }
    python = swift.parent / "python"
    if not python.is_file():
        python = Path(os.environ.get(MPS_PYTHON_ENV, "python3"))
    script = (
        "import json,sys,torch,swift;"
        "ok=torch.backends.mps.is_available() and torch.backends.mps.is_built();"
        "device='mps' if ok else 'cpu';"
        "print(json.dumps({'device':device,'torch':torch.__version__,"
        "'swift':getattr(swift,'__version__','4.5.2'),"
        "'python':sys.version.split()[0],'stub':'false'}))"
    )
    try:
        completed = subprocess.run(  # noqa: S603
            [str(python), "-c", script],
            check=False,
            capture_output=True,
            timeout=30,
            env=_mps_env(swift.parent, swift),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerSandboxError("MPS device probe failed", code="mps-unavailable") from exc
    if completed.returncode != 0:
        raise WorkerSandboxError("MPS device probe failed", code="mps-unavailable")
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerSandboxError("MPS device probe failed", code="mps-unavailable") from exc
    if type(payload) is not dict or type(payload.get("device")) is not str:
        raise WorkerSandboxError("MPS device probe failed", code="mps-unavailable")
    return {
        "device": payload["device"],
        "torch": str(payload.get("torch", "")),
        "swift": str(payload.get("swift", "")),
        "python": str(payload.get("python", "")),
        "stub": "false",
    }


def _sitecustomize_digest(swift: Path) -> str | None:
    path = swift.parent.parent.parent / "pythonpath" / "sitecustomize.py"
    if not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _mps_env(workspace: Path, swift: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _PASSTHROUGH:
        value = os.environ.get(key)
        if type(value) is str and value != "":
            env[key] = value
    env["PATH"] = str(swift.parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["HOME"] = str(workspace)
    env["TMPDIR"] = MPS_TMPDIR
    env["TMP"] = MPS_TMPDIR
    env["TEMP"] = MPS_TMPDIR
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_DATASETS_OFFLINE"] = "1"
    env["MODELSCOPE_OFFLINE"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    shim = swift.parent.parent.parent / "pythonpath"
    if shim.is_dir():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(shim) if existing == "" else str(shim) + os.pathsep + existing
    stub_sleep = os.environ.get("RESEARCHOS_MPS_STUB_SLEEP")
    if type(stub_sleep) is str and stub_sleep != "":
        env["RESEARCHOS_MPS_STUB_SLEEP"] = stub_sleep
    return env


def _record_posix_identity(
    identity_dir: Path | None,
    lease_id: str | None,
    process: subprocess.Popen[bytes],
    pgid: int | None,
) -> ExecutionIdentity | None:
    if identity_dir is None or lease_id is None or process.pid is None:
        return None
    identity = ExecutionIdentity(
        lease_id=lease_id,
        kind=KIND_POSIX,
        pid=process.pid,
        pgid=pgid,
        start_token=posix_start_token(process.pid),
        container_id=None,
        docker_executable=None,
    )
    save_execution_identity(identity_dir, identity)
    return identity


def _finish_cancelled(
    process: subprocess.Popen[bytes],
    pgid: int | None,
    identity: ExecutionIdentity | None,
) -> SandboxResult:
    if identity is not None:
        outcome = observe_and_stop(identity)
        if outcome == UNOBSERVED:
            return SandboxResult(
                disposition=SandboxDisposition.UNKNOWN,
                stdout=b"",
                result_digest=None,
                reason_code=UNOBSERVED,
            )
        if outcome == OBSERVED_STOP:
            return SandboxResult(
                disposition=SandboxDisposition.FAILED,
                stdout=b"",
                result_digest=None,
                reason_code="cancel-observed",
            )
    _reap_process_group(process, pgid)
    if process.poll() is not None:
        return SandboxResult(
            disposition=SandboxDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="cancel-observed",
        )
    return SandboxResult(
        disposition=SandboxDisposition.UNKNOWN,
        stdout=b"",
        result_digest=None,
        reason_code=UNOBSERVED,
    )


def _training_report(
    output: Path,
    *,
    plan: MacMpsTrainingPlan,
    probe: Mapping[str, str],
    environment: MpsEnvironmentReceipt,
    wall_seconds: float,
    peak_rss_bytes: int,
    log_path: Path,
) -> dict[str, object]:
    checkpoints = _checkpoint_dirs(output)
    if not checkpoints:
        raise WorkerSandboxError(
            "MPS training produced no checkpoint",
            code="mps-checkpoint-missing",
        )
    latest = checkpoints[-1]
    state = _trainer_state(latest)
    global_step = state.get("global_step")
    if type(global_step) is not int or global_step < 1:
        raise WorkerSandboxError(
            "MPS trainer global_step is missing",
            code="mps-checkpoint-missing",
        )
    losses = _losses(state, log_path)
    if not losses or any(not math.isfinite(item) for item in losses):
        raise WorkerSandboxError("MPS training loss is not finite", code="mps-loss-invalid")
    adapters = [_file_digest(latest, name) for name in _ADAPTER_NAMES if (latest / name).is_file()]
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
            "MPS adapter bytes did not change",
            code="mps-parameters-unchanged",
        )
    fallback_ops = _fallback_ops(log_path)
    return {
        "kind": "MacMpsTrainingReport",
        "status": "ok",
        "executed": True,
        "device": probe["device"],
        "cpuFallback": probe["device"] != "mps",
        "mpsFallbackOps": fallback_ops,
        "backendId": plan.backend_id,
        "backendVersion": plan.backend_version,
        "torchVersion": probe["torch"],
        "pythonVersion": probe["python"],
        "isolation": MPS_ISOLATION,
        "ociIsolationClaimed": False,
        "networkEnforcement": "offline-env-flags",
        "globalStep": global_step,
        "losses": losses,
        "lossFinite": True,
        "parametersUpdated": True if len(checkpoints) == 1 else updated,
        "checkpoint": {
            "path": latest.relative_to(output).as_posix()
            if latest.is_relative_to(output)
            else latest.name,
            "optimizer": _has_any(latest, _OPTIMIZER_NAMES),
            "scheduler": _has_any(latest, _SCHEDULER_NAMES),
            "rng": _has_any(latest, _RNG_NAMES),
            "adapter": bool(adapters),
            "globalStep": global_step,
        },
        "wallSeconds": wall_seconds,
        "peakRssBytes": peak_rss_bytes,
        "stub": environment.stub or probe.get("stub") == "true",
    }


def _checkpoint_dirs(output: Path) -> list[Path]:
    found = [path for path in sorted(output.glob("checkpoint-*")) if path.is_dir()]
    nested = [path for path in sorted(output.glob("*/checkpoint-*")) if path.is_dir()]
    return found or nested


def _trainer_state(checkpoint: Path) -> dict[str, object]:
    path = checkpoint / "trainer_state.json"
    if not path.is_file():
        raise WorkerSandboxError("MPS trainer_state.json is missing", code="mps-checkpoint-missing")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerSandboxError(
            "MPS trainer_state.json is invalid",
            code="mps-checkpoint-missing",
        ) from exc
    if type(document) is not dict:
        raise WorkerSandboxError("MPS trainer_state.json is invalid", code="mps-checkpoint-missing")
    return document


def _losses(state: Mapping[str, object], log_path: Path) -> list[float]:
    history = state.get("log_history")
    values: list[float] = []
    if type(history) is list:
        for item in history:
            if type(item) is dict and isinstance(item.get("loss"), int | float):
                values.append(float(item["loss"]))
    if values:
        return values
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.search(r"'loss':\s*([0-9.eE+-]+)", line)
            if match is None:
                match = re.search(r'"loss":\s*([0-9.eE+-]+)', line)
            if match is not None:
                values.append(float(match.group(1)))
    return values


def _has_any(checkpoint: Path, names: tuple[str, ...]) -> bool:
    return any((checkpoint / name).is_file() for name in names)


def _file_digest(checkpoint: Path, name: str) -> str:
    payload = (checkpoint / name).read_bytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fallback_ops(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    found: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if _FALLBACK_RE.search(line) is None:
            continue
        found.append(line.strip()[:200])
        if len(found) >= 8:
            break
    return found


def _log_tail(log_path: Path) -> str | None:
    if not log_path.is_file():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if text == "":
        return None
    return text[-2048:]


def _rss_bytes(pid: int | None) -> int:
    if pid is None:
        return 0
    executable = shutil.which("ps")
    if executable is None:
        return 0
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, "-o", "rss=", "-p", str(pid)],
            check=False,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if completed.returncode != 0:
        return 0
    try:
        kb = int(completed.stdout.decode("utf-8").strip() or "0")
    except ValueError:
        return 0
    return kb * 1024
