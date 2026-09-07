"""Parse a pinned training-backend plan. This command does not launch GPU work."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.training.checkpoint import (
    collect_output_artifacts,
    inspect_snapshot,
    load_collect_manifest,
    load_gpu_data_checkpoint_binding,
    require_binding_matches_plan,
)
from llm_research_os.training.errors import TrainingBackendError, TrainingBackendRequestError
from llm_research_os.training.gpu_bind import (
    bind_ms_swift_gpu_command,
    plan_document_digest,
    resume_loads,
)
from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import load_training_backend_plan
from llm_research_os.workers.errors import WorkerSandboxError
from llm_research_os.workers.gpu import (
    DEFAULT_GPU_CPU_MILLIS,
    DEFAULT_GPU_DISK_BYTES,
    DEFAULT_GPU_MEMORY_BYTES,
    DEFAULT_GPU_PIDS,
    DEFAULT_GPU_WALL_SECONDS,
    GPU_ACCELERATOR,
    GPU_DATA_MOUNT,
    GPU_DEVICE,
    GPU_MODEL_MOUNT,
    GPU_NETWORK_DENIED,
    GPU_OUTPUT_MOUNT,
    parse_gpu_launch_policy,
    prepare_gpu_launch,
)

_INPUT_ERRORS = (
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
    WorkerSandboxError,
)


def run_training(args: argparse.Namespace) -> int:
    if args.training_command == "plan":
        return _plan(args.request, args.format)
    if args.training_command == "bind":
        return _bind(args)
    if args.training_command == "overlay":
        return _overlay(args)
    if args.training_command == "snapshot":
        return _snapshot(args)
    if args.training_command == "collect":
        return _collect(args)
    raise AssertionError(f"unhandled training command: {args.training_command}")


def _plan(request_path: Path, output_format: str) -> int:
    try:
        receipt = plan_ms_swift(load_training_backend_plan(request_path))
    except TrainingBackendRequestError as exc:
        print_error(exc, output_format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    payload = {
        "apiVersion": "researchos.dev/v0alpha1",
        **receipt.as_json(),
    }
    if output_format == "json":
        print(dumps_json(payload))
        return 0
    print("training plan: recorded")
    print(f"backend: {safe_text(receipt.backend_id)} {safe_text(receipt.backend_version)}")
    print(f"executed: {receipt.executed}")
    print(f"gpu: {safe_text(receipt.gpu)}")
    print(f"backendInstalled: {receipt.backend_installed}")
    print(f"costKnown: {receipt.cost_known}")
    print(f"argv: {safe_text(' '.join(receipt.argv))}")
    return 0


def _bind(args: argparse.Namespace) -> int:
    try:
        plan = load_training_backend_plan(args.request)
        command_argv, command = bind_ms_swift_gpu_command(plan)
        raw = args.request.read_bytes()
        artifact = "sha256:" + hashlib.sha256(raw).hexdigest()
        policy = parse_gpu_launch_policy(
            image_digest=args.image,
            config={
                "network": GPU_NETWORK_DENIED,
                "device": GPU_DEVICE,
                "memoryBytes": DEFAULT_GPU_MEMORY_BYTES,
                "pidsLimit": DEFAULT_GPU_PIDS,
                "cpuMillis": DEFAULT_GPU_CPU_MILLIS,
                "wallTimeSeconds": DEFAULT_GPU_WALL_SECONDS,
                "diskBytes": DEFAULT_GPU_DISK_BYTES,
                "dataMount": GPU_DATA_MOUNT,
                "modelMount": GPU_MODEL_MOUNT,
                "outputMount": GPU_OUTPUT_MOUNT,
                "commandDigest": command,
            },
            inputs={
                "planDigest": plan_document_digest(plan),
                "planArtifactDigest": artifact,
            },
        )
        prepared = prepare_gpu_launch(
            image_digest=args.image,
            policy=policy,
            command_argv=command_argv,
            data_dir=args.data_dir,
            model_dir=args.model_dir,
            output_dir=args.output_dir,
            advertised_accelerators=(GPU_ACCELERATOR,),
        )
    except TrainingBackendRequestError as exc:
        print_error(exc, args.format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    payload = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "GpuLaunchPreparation",
        "dockerArgv": list(prepared.docker_argv),
        "commandArgv": list(prepared.command_argv),
        "executed": prepared.executed,
        "gpu": prepared.gpu,
        "commandDigest": command,
        "planDigest": plan_document_digest(plan),
        "planArtifactDigest": artifact,
    }
    if args.format == "json":
        print(dumps_json(payload))
        return 0
    print("training bind: recorded")
    print(f"executed: {prepared.executed}")
    print(f"gpu: {safe_text(prepared.gpu)}")
    print(f"command: {safe_text(' '.join(prepared.command_argv))}")
    return 0


def _overlay(args: argparse.Namespace) -> int:
    try:
        plan = load_training_backend_plan(args.request)
        command_argv, command = bind_ms_swift_gpu_command(
            plan,
            resume_mode=args.resume,
            checkpoint_path=args.checkpoint,
        )
    except TrainingBackendRequestError as exc:
        print_error(exc, args.format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    payload = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "GpuResumeOverlayReceipt",
        "commandArgv": list(command_argv),
        "commandDigest": command,
        "resume": args.resume,
        "loads": list(resume_loads(args.resume)),
        "executed": False,
        "gpu": "not-run",
    }
    if args.format == "json":
        print(dumps_json(payload))
        return 0
    print("training overlay: recorded")
    print(f"resume: {safe_text(args.resume)}")
    print("gpu: not-run")
    print(f"command: {safe_text(' '.join(command_argv))}")
    return 0


def _snapshot(args: argparse.Namespace) -> int:
    try:
        binding = load_gpu_data_checkpoint_binding(args.binding)
        if args.plan is not None:
            require_binding_matches_plan(binding, load_training_backend_plan(args.plan))
        receipt = inspect_snapshot(
            binding,
            model_dir=args.model_dir,
            data_dir=args.data_dir,
        )
    except TrainingBackendRequestError as exc:
        print_error(exc, args.format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    payload = {"apiVersion": "researchos.dev/v0alpha1", **receipt.as_json()}
    if args.format == "json":
        print(dumps_json(payload))
        return 0
    print("training snapshot: recorded")
    print(f"fetched: {receipt.fetched}")
    print(f"gpu: {safe_text(receipt.gpu)}")
    print(f"model: {safe_text(receipt.model.status)}")
    print(f"dataset: {safe_text(receipt.dataset.status)}")
    return 0


def _collect(args: argparse.Namespace) -> int:
    try:
        artifacts_root = args.artifacts
        artifacts_root.mkdir(parents=True, exist_ok=True)
        artifacts = LocalArtifactStore(artifacts_root)
        prior = load_collect_manifest(args.resume_from) if args.resume_from is not None else None
        receipt = collect_output_artifacts(args.output, artifacts, prior=prior)
    except TrainingBackendRequestError as exc:
        print_error(exc, args.format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    payload = {"apiVersion": "researchos.dev/v0alpha1", **receipt.as_json()}
    if args.format == "json":
        print(dumps_json(payload))
        return 0
    print("training collect: recorded")
    print(f"status: {safe_text(receipt.status)}")
    print(f"executed: {receipt.executed}")
    print(f"gpu: {safe_text(receipt.gpu)}")
    return 0
