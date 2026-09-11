from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_worker_protocol import HMAC_KEY, NOW, PROJECT, SOURCE, FrozenClock

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli import main
from llm_research_os.cli.training_commands import run_training
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.training.errors import TrainingBackendError
from llm_research_os.training.gpu_bind import bind_ms_swift_gpu_command, plan_document_digest
from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import load_training_backend_plan
from llm_research_os.workers.binding import brick_execution_digest
from llm_research_os.workers.errors import WorkerCallError, WorkerSandboxError
from llm_research_os.workers.gpu import (
    DEFAULT_GPU_WALL_SECONDS,
    GPU_ACCELERATOR,
    GPU_CACHE_ENV,
    GPU_CONTAINER_USER,
    GPU_DEVICE,
    GPU_OUTPUT_MOUNT,
    execute_gpu_training,
    gpu_docker_argv,
    parse_gpu_launch_policy,
    prepare_gpu_launch,
)
from llm_research_os.workers.models import (
    IMAGE_MEDIA_OCI_IMAGE,
    WORKER_RUNTIME_GPU_OCI,
    WORKER_RUNTIME_OCI_CONTAINER,
)
from llm_research_os.workers.oci import parse_oci_launch_policy
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.sandbox import SandboxDisposition

ROOT = Path(__file__).parents[1]
GPU_CORPUS = ROOT / "examples" / "m2-gpu-checkpoint"
PLAN_PATH = ROOT / "examples" / "training-backend" / "valid" / "ms-swift-sft.json"
OCI_AUTH = ROOT / "examples" / "m2-oci-checkpoint" / "authorization-event.json"
GPU_IMAGE = "sha256:" + ("0" * 64)
AUTH_EVENT_ID = "evt.authorization.example-minimal.gpu.1"
_JCS_A = "jcs-sha256:" + ("a" * 64)
_JCS_B = "jcs-sha256:" + ("b" * 64)


def _gpu_config(command_digest: str) -> dict[str, object]:
    return {
        "network": "denied",
        "device": GPU_DEVICE,
        "commandDigest": command_digest,
        "dataMount": "/work/data",
        "modelMount": "/work/model",
        "outputMount": GPU_OUTPUT_MOUNT,
        "wallTimeSeconds": DEFAULT_GPU_WALL_SECONDS,
    }


def _plan_bundle(artifacts: LocalArtifactStore) -> tuple[object, str, str, str]:
    plan = load_training_backend_plan(PLAN_PATH)
    command_argv, command_digest = bind_ms_swift_gpu_command(plan)
    stored = artifacts.put(PLAN_PATH)
    return plan, command_argv, command_digest, stored.digest


def _gpu_spec(
    image_digest: str, command_digest: str, plan_digest: str, plan_artifact: str
) -> ResearchSpec:
    payload = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ResearchProject",
        "metadata": {
            "id": PROJECT,
            "revision": 1,
            "title": "GPU ms-swift launch profile",
        },
        "questions": [{"id": "rq.gpu", "question": "Can the pinned GPU profile bind?"}],
        "hypotheses": [],
        "evidence": [],
        "datasets": [],
        "models": [],
        "workflows": [
            {
                "id": "workflow.gpu",
                "graph": {
                    "nodes": [
                        {
                            "kind": "task",
                            "id": "task.gpu",
                            "blockType": "researchos.gpu-ms-swift",
                            "blockVersion": "0.1.0",
                            "config": {
                                "imageDigest": image_digest,
                                "imageMediaType": IMAGE_MEDIA_OCI_IMAGE,
                                "runtime": WORKER_RUNTIME_GPU_OCI,
                                "config": _gpu_config(command_digest),
                                "inputs": {
                                    "planDigest": plan_digest,
                                    "planArtifactDigest": plan_artifact,
                                },
                            },
                        }
                    ],
                    "edges": [],
                },
            }
        ],
        "evaluations": [],
        "resources": [],
        "policies": {
            "paidActionsRequireApproval": True,
            "destructiveActionsRequireApproval": True,
            "preserveAiDissent": True,
            "unknownEvidenceMayTrain": False,
        },
    }
    return ResearchSpec.model_validate(payload)


def _record_gpu_authorization(store: EventStore, spec: ResearchSpec) -> tuple[str, str]:
    registry = build_registry([GPU_CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id="workflow.gpu")
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.gpu",),
    )
    result = authorize_plan(report, policy)
    document = snapshot_json_document(load_document(OCI_AUTH, reject_symlinks=True))
    assert type(document) is dict
    document["workflowId"] = "workflow.gpu"
    document["event"] = {"id": AUTH_EVENT_ID, "time": "2026-09-02T05:00:00Z"}
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    recorded = record_plan_authorization_event(
        store,
        report,
        policy,
        validate_plan_authorization_event_request_document(document),
    )
    return recorded.stored.event.id, recorded.stored.event.sequence


def test_cpu_oci_policy_rejects_gpu_device() -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=GPU_IMAGE,
            config={"network": "denied", "device": GPU_DEVICE},
            inputs={"brickDigest": GPU_IMAGE},
        )
    assert captured.value.code == "oci-mount-forbidden"


def test_gpu_policy_pins_device_mounts_and_command(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, command_argv, command_digest, artifact = _plan_bundle(artifacts)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
    )
    assert policy.device == GPU_DEVICE
    assert policy.output_mount == GPU_OUTPUT_MOUNT
    assert policy.wall_time_seconds == DEFAULT_GPU_WALL_SECONDS
    prepared = prepare_gpu_launch(
        image_digest=GPU_IMAGE,
        policy=policy,
        command_argv=command_argv,
        data_dir=tmp_path / "data",
        model_dir=tmp_path / "model",
        output_dir=tmp_path / "output",
        advertised_accelerators=(GPU_ACCELERATOR,),
    )
    joined = " ".join(prepared.docker_argv)
    assert prepared.executed is False
    assert prepared.gpu == "not-run"
    assert prepared.command_argv == plan_ms_swift(plan).argv
    assert "--privileged" not in prepared.docker_argv
    assert "--gpus" in prepared.docker_argv
    assert prepared.docker_argv[prepared.docker_argv.index("--gpus") + 1] == "device=0"
    assert f"dst={GPU_OUTPUT_MOUNT}" in joined
    assert f"dst={GPU_OUTPUT_MOUNT},readonly" not in joined
    assert "/out:rw" not in joined
    assert "--network" in prepared.docker_argv
    assert prepared.docker_argv[prepared.docker_argv.index("--network") + 1] == "none"
    assert "--read-only" in prepared.docker_argv
    assert prepared.docker_argv[prepared.docker_argv.index("--user") + 1] == GPU_CONTAINER_USER
    for value in GPU_CACHE_ENV:
        assert prepared.docker_argv[prepared.docker_argv.index(value) - 1] == "--env"
    assert "HOME=/nonexistent" not in prepared.docker_argv
    assert "PYTHONPATH=/work/output/.researchos" in prepared.docker_argv
    assert "RESEARCHOS_GPU_RESTORE_OBSERVE=1" in prepared.docker_argv


@pytest.mark.parametrize(
    ("config", "code"),
    (
        (
            {"network": "bridge", "device": GPU_DEVICE, "commandDigest": "x"},
            "gpu-network-forbidden",
        ),
        (
            {"network": "denied", "device": "nvidia.com/gpu=1", "commandDigest": "x"},
            "gpu-device-forbidden",
        ),
        (
            {"network": "denied", "device": GPU_DEVICE, "privileged": True, "commandDigest": "x"},
            "gpu-mount-forbidden",
        ),
        (
            {"network": "denied", "device": GPU_DEVICE, "mounts": ["/var/run/docker.sock"]},
            "gpu-mount-forbidden",
        ),
        (
            {
                "network": "denied",
                "device": GPU_DEVICE,
                "outputMount": "/tmp",
                "commandDigest": _JCS_A,
            },
            "gpu-mount-forbidden",
        ),
    ),
)
def test_gpu_policy_forbids_escape(config: dict[str, object], code: str) -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_gpu_launch_policy(
            image_digest=GPU_IMAGE,
            config=config,
            inputs={
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
        )
    assert captured.value.code == code


def test_gpu_prepare_requires_cuda_advertisement(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, command_argv, command_digest, artifact = _plan_bundle(artifacts)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
    )
    with pytest.raises(WorkerSandboxError) as captured:
        prepare_gpu_launch(
            image_digest=GPU_IMAGE,
            policy=policy,
            command_argv=command_argv,
            data_dir=tmp_path / "data",
            model_dir=tmp_path / "model",
            output_dir=tmp_path / "output",
            advertised_accelerators=(),
        )
    assert captured.value.code == "accelerator-missing"


def test_execute_gpu_training_validates_and_does_not_run(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    result = execute_gpu_training(
        artifacts,
        GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
        advertised_accelerators=(GPU_ACCELERATOR,),
        data_dir=tmp_path / "data",
        model_dir=tmp_path / "model",
        output_dir=tmp_path / "output",
    )
    assert result.disposition is SandboxDisposition.FAILED
    assert result.reason_code == "gpu-not-run"
    assert result.result_digest is None


def test_training_bind_cli_prints_docker_argv_without_executing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    assert (
        main(
            [
                "training",
                "bind",
                str(PLAN_PATH),
                "--image",
                GPU_IMAGE,
                "--data-dir",
                str(data),
                "--model-dir",
                str(model),
                "--output-dir",
                str(output),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "GpuLaunchPreparation"
    assert payload["executed"] is False
    assert payload["gpu"] == "not-run"
    assert payload["commandArgv"][0:2] == ["swift", "sft"]
    assert "--privileged" not in payload["dockerArgv"]
    assert "device=0" in payload["dockerArgv"]


def test_execute_gpu_grant_and_poll_requires_cuda_worker(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    spec = _gpu_spec(GPU_IMAGE, command_digest, plan_document_digest(plan), artifact)
    registry = build_registry([GPU_CORPUS / "block.json"])
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        event_id, sequence = _record_gpu_authorization(store, spec)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.gpu.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.gpu.1",
            runtime=WORKER_RUNTIME_GPU_OCI,
            accelerators=(GPU_ACCELERATOR,),
        )
        config = _gpu_config(command_digest)
        inputs = {
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        }
        config_digest = brick_execution_digest(
            image_digest=GPU_IMAGE,
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
        )
        plane.record_grant(
            grant_id="grant.gpu.1",
            worker_id="worker.gpu.1",
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            nonce="nonce.gpu.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.gpu.1",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=GPU_IMAGE,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.gpu",
        )
        plane.enqueue(
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            image_digest=GPU_IMAGE,
            event_id="evt.work.queued.task.gpu",
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
            required_accelerators=(GPU_ACCELERATOR,),
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.gpu.1")
        claimed = plane.poll(worker_id="worker.gpu.1", grant_token=token)
        assert claimed is not None
        assert claimed.runtime == WORKER_RUNTIME_GPU_OCI


def test_oci_container_worker_cannot_lease_gpu_work(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    spec = _gpu_spec(GPU_IMAGE, command_digest, plan_document_digest(plan), artifact)
    registry = build_registry([GPU_CORPUS / "block.json"])
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        event_id, sequence = _record_gpu_authorization(store, spec)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.oci.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.oci.for-gpu",
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
            accelerators=(GPU_ACCELERATOR,),
        )
        config = _gpu_config(command_digest)
        inputs = {
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        }
        config_digest = brick_execution_digest(
            image_digest=GPU_IMAGE,
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
        )
        plane.record_grant(
            grant_id="grant.gpu.oci-worker",
            worker_id="worker.oci.1",
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            nonce="nonce.gpu.oci-worker",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.gpu.oci-worker",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=GPU_IMAGE,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.gpu",
        )
        plane.enqueue(
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            image_digest=GPU_IMAGE,
            event_id="evt.work.queued.task.gpu",
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
            required_accelerators=(GPU_ACCELERATOR,),
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.gpu.oci-worker")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.oci.1", grant_token=token)
        assert captured.value.code == "runtime-mismatch"


def test_gpu_work_is_refused_without_cuda_advertisement(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    spec = _gpu_spec(GPU_IMAGE, command_digest, plan_document_digest(plan), artifact)
    registry = build_registry([GPU_CORPUS / "block.json"])
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        event_id, sequence = _record_gpu_authorization(store, spec)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.gpu.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.gpu.1",
            runtime=WORKER_RUNTIME_GPU_OCI,
        )
        config = _gpu_config(command_digest)
        inputs = {
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        }
        config_digest = brick_execution_digest(
            image_digest=GPU_IMAGE,
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
        )
        plane.record_grant(
            grant_id="grant.gpu.1",
            worker_id="worker.gpu.1",
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            nonce="nonce.gpu.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.gpu.1",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=GPU_IMAGE,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.gpu",
        )
        plane.enqueue(
            task_id="task.gpu",
            run_id="run.worker.gpu",
            attempt_id="attempt.worker.gpu.1",
            image_digest=GPU_IMAGE,
            event_id="evt.work.queued.task.gpu",
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_GPU_OCI,
            required_accelerators=(GPU_ACCELERATOR,),
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.gpu.1")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.gpu.1", grant_token=token)
        assert captured.value.code == "accelerator-missing"


def test_importing_worker_client_does_not_load_training_adapter() -> None:
    before = {name for name in sys.modules if name.startswith("llm_research_os.training")}
    import llm_research_os.workers.client as client

    after = {name for name in sys.modules if name.startswith("llm_research_os.training")}
    assert after == before
    assert client.WorkerClient is not None


@pytest.mark.parametrize(
    ("image", "config", "inputs", "code"),
    (
        (
            "nginx:latest",
            {"network": "denied", "device": GPU_DEVICE, "commandDigest": _JCS_A},
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "oci-image-tag-forbidden",
        ),
        (
            "sha256:" + ("0" * 63),
            {"network": "denied", "device": GPU_DEVICE, "commandDigest": _JCS_A},
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "oci-image-tag-forbidden",
        ),
        (
            GPU_IMAGE,
            {
                "network": "denied",
                "device": GPU_DEVICE,
                "commandDigest": _JCS_A,
                "ipc": "host",
            },
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "gpu-mount-forbidden",
        ),
        (
            GPU_IMAGE,
            {"network": "denied", "device": GPU_DEVICE, "commandDigest": "not-a-digest"},
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "execution-binding-mismatch",
        ),
        (
            GPU_IMAGE,
            {"network": "denied", "device": GPU_DEVICE, "commandDigest": _JCS_A},
            {"planDigest": "not-a-digest", "planArtifactDigest": GPU_IMAGE},
            "execution-binding-mismatch",
        ),
        (
            GPU_IMAGE,
            {"network": "denied", "device": GPU_DEVICE, "commandDigest": _JCS_A},
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": "sha256:dead",
            },
            "execution-binding-mismatch",
        ),
        (
            GPU_IMAGE,
            {
                "network": "denied",
                "device": GPU_DEVICE,
                "commandDigest": _JCS_A,
                "dataMount": "/work/other",
            },
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "gpu-mount-forbidden",
        ),
        (
            GPU_IMAGE,
            {
                "network": "denied",
                "device": GPU_DEVICE,
                "commandDigest": _JCS_A,
                "memoryBytes": 0,
            },
            {
                "planDigest": _JCS_B,
                "planArtifactDigest": GPU_IMAGE,
            },
            "gpu-resource-limit",
        ),
    ),
)
def test_gpu_policy_rejects_invalid_identity_and_limits(
    image: str,
    config: dict[str, object],
    inputs: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_gpu_launch_policy(image_digest=image, config=config, inputs=inputs)
    assert captured.value.code == code


def test_gpu_prepare_rejects_command_that_is_not_the_bound_plan(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, command_argv, command_digest, artifact = _plan_bundle(artifacts)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
    )
    cases = (
        (*command_argv, "--extra"),
        ("python", "-c", "pass"),
        ("swift", "sft"),
        ("swift", "sft", "--output_dir", "/tmp/out"),
    )
    for argv in cases:
        with pytest.raises(WorkerSandboxError) as captured:
            prepare_gpu_launch(
                image_digest=GPU_IMAGE,
                policy=policy,
                command_argv=argv,
                data_dir=tmp_path / "data",
                model_dir=tmp_path / "model",
                output_dir=tmp_path / "output",
                advertised_accelerators=(GPU_ACCELERATOR,),
            )
        assert captured.value.code in {"execution-binding-mismatch", "gpu-mount-forbidden"}


def test_gpu_prepare_rejects_injected_privileged_and_all_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, command_argv, command_digest, artifact = _plan_bundle(artifacts)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
    )

    def privileged(*_args: object, **_kwargs: object) -> list[str]:
        return ["docker", "run", "--privileged", "--gpus", "device=0", GPU_IMAGE]

    monkeypatch.setattr("llm_research_os.workers.gpu.gpu_docker_argv", privileged)
    with pytest.raises(WorkerSandboxError) as captured:
        prepare_gpu_launch(
            image_digest=GPU_IMAGE,
            policy=policy,
            command_argv=command_argv,
            data_dir=tmp_path / "data",
            model_dir=tmp_path / "model",
            output_dir=tmp_path / "output",
            advertised_accelerators=(GPU_ACCELERATOR,),
        )
    assert captured.value.code == "gpu-mount-forbidden"

    def all_gpus(*_args: object, **_kwargs: object) -> list[str]:
        return ["docker", "run", "--gpus", "all", GPU_IMAGE]

    monkeypatch.setattr("llm_research_os.workers.gpu.gpu_docker_argv", all_gpus)
    with pytest.raises(WorkerSandboxError) as captured:
        prepare_gpu_launch(
            image_digest=GPU_IMAGE,
            policy=policy,
            command_argv=command_argv,
            data_dir=tmp_path / "data",
            model_dir=tmp_path / "model",
            output_dir=tmp_path / "output",
            advertised_accelerators=(GPU_ACCELERATOR,),
        )
    assert captured.value.code == "gpu-device-forbidden"


def test_gpu_docker_argv_records_cidfile(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, command_argv, command_digest, artifact = _plan_bundle(artifacts)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
    )
    cidfile = tmp_path / "cid"
    argv = gpu_docker_argv(
        "docker",
        image_digest=GPU_IMAGE,
        policy=policy,
        command_argv=command_argv,
        data_dir=tmp_path / "data",
        model_dir=tmp_path / "model",
        output_dir=tmp_path / "output",
        cidfile=cidfile,
    )
    assert argv[2:4] == ["--cidfile", str(cidfile)]
    assert argv[argv.index("--user") + 1] == GPU_CONTAINER_USER
    assert "--read-only" in argv
    for value in GPU_CACHE_ENV:
        assert argv[argv.index(value) - 1] == "--env"
    tmpfs = argv[argv.index("--tmpfs") + 1]
    assert tmpfs.startswith("/tmp:rw,exec,nosuid,size=")
    assert "noexec" not in tmpfs
    assert "type=bind" in " ".join(argv)
    assert argv.count("--tmpfs") == 1


def test_prepare_gpu_output_installs_restore_observe(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import _prepare_gpu_output_root

    output = tmp_path / "output"
    output.mkdir()
    _prepare_gpu_output_root(output)
    copied = output / ".researchos" / "gpu_restore_observe.py"
    site = output / ".researchos" / "sitecustomize.py"
    identity = json.loads((output / "researchos-code-identity.json").read_text(encoding="utf-8"))
    assert copied.is_file()
    assert "install()" in site.read_text(encoding="utf-8")
    assert identity["kind"] == "GpuCodeIdentity"
    assert identity["observeDigest"].startswith("sha256:")
    assert identity["gpuDigest"].startswith("sha256:")


def test_execute_gpu_training_without_host_dirs_is_not_run(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    result = execute_gpu_training(
        artifacts,
        GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
        advertised_accelerators=(GPU_ACCELERATOR,),
    )
    assert result.reason_code == "gpu-not-run"


def test_execute_gpu_training_rejects_plan_and_command_mismatch(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    other = artifacts.put_bytes(b'{"not":"the-plan"}')
    with pytest.raises(WorkerSandboxError) as captured:
        execute_gpu_training(
            artifacts,
            GPU_IMAGE,
            config=_gpu_config(command_digest),
            inputs={
                "planDigest": "jcs-sha256:" + ("c" * 64),
                "planArtifactDigest": other.digest,
            },
        )
    assert captured.value.code == "execution-binding-mismatch"
    with pytest.raises(WorkerSandboxError) as captured:
        execute_gpu_training(
            artifacts,
            GPU_IMAGE,
            config=_gpu_config(command_digest),
            inputs={
                "planDigest": _JCS_A,
                "planArtifactDigest": artifact,
            },
        )
    assert captured.value.code == "execution-binding-mismatch"
    with pytest.raises(WorkerSandboxError) as captured:
        execute_gpu_training(
            artifacts,
            GPU_IMAGE,
            config=_gpu_config("jcs-sha256:" + ("d" * 64)),
            inputs={
                "planDigest": plan_document_digest(plan),
                "planArtifactDigest": artifact,
            },
        )
    assert captured.value.code == "execution-binding-mismatch"


def test_training_bind_and_plan_text_receipts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    assert main(["training", "plan", str(PLAN_PATH)]) == 0
    plan_out = capsys.readouterr().out
    assert "training plan: recorded" in plan_out
    assert "gpu: not-run" in plan_out
    assert (
        main(
            [
                "training",
                "bind",
                str(PLAN_PATH),
                "--image",
                GPU_IMAGE,
                "--data-dir",
                str(data),
                "--model-dir",
                str(model),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    bind_out = capsys.readouterr().out
    assert "training bind: recorded" in bind_out
    assert "gpu: not-run" in bind_out


def test_training_bind_rejects_invalid_image(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    assert (
        main(
            [
                "training",
                "bind",
                str(PLAN_PATH),
                "--image",
                "nginx:latest",
                "--data-dir",
                str(data),
                "--model-dir",
                str(model),
                "--output-dir",
                str(output),
                "--format",
                "json",
            ]
        )
        == 2
    )
    assert "tag" in capsys.readouterr().err.lower()


def test_training_plan_and_bind_report_backend_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_plan: object) -> object:
        raise TrainingBackendError("adapter failed", code="training-backend")

    monkeypatch.setattr("llm_research_os.cli.training_commands.plan_ms_swift", boom)
    assert main(["training", "plan", str(PLAN_PATH), "--format", "json"]) == 1
    assert "adapter failed" in capsys.readouterr().err
    monkeypatch.setattr(
        "llm_research_os.cli.training_commands.bind_ms_swift_gpu_command",
        lambda _plan: (_ for _ in ()).throw(TrainingBackendError("bind failed")),
    )
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    assert (
        main(
            [
                "training",
                "bind",
                str(PLAN_PATH),
                "--image",
                GPU_IMAGE,
                "--data-dir",
                str(data),
                "--model-dir",
                str(model),
                "--output-dir",
                str(output),
                "--format",
                "json",
            ]
        )
        == 1
    )
    assert "bind failed" in capsys.readouterr().err


def test_unhandled_training_command_fails_closed() -> None:
    with pytest.raises(AssertionError, match="unhandled training command"):
        run_training(type("Args", (), {"training_command": "launch"})())


def test_wsl_cuda_profile_rejects_autodl_memory() -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_gpu_launch_policy(
            image_digest=GPU_IMAGE,
            config={
                "network": "denied",
                "device": GPU_DEVICE,
                "profile": "wsl2-cuda-laptop-8g",
                "memoryBytes": 17_179_869_184,
                "commandDigest": _JCS_A,
            },
            inputs={"planDigest": _JCS_A, "planArtifactDigest": GPU_IMAGE},
        )
    assert captured.value.code == "gpu-resource-limit"


def test_wsl_cuda_profile_uses_three_gib_default() -> None:
    from llm_research_os.workers.gpu import WSL_GPU_MEMORY_BYTES

    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config={
            "network": "denied",
            "device": GPU_DEVICE,
            "profile": "wsl2-cuda-laptop-8g",
            "commandDigest": _JCS_A,
        },
        inputs={"planDigest": _JCS_A, "planArtifactDigest": GPU_IMAGE},
    )
    assert policy.memory_bytes == WSL_GPU_MEMORY_BYTES
    assert policy.profile == "wsl2-cuda-laptop-8g"
    assert policy.tmpfs_bytes == 268_435_456


def test_run_gpu_training_forbidden_config_fails_the_sandbox(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import run_gpu_training

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    result = run_gpu_training(
        artifacts,
        GPU_IMAGE,
        config={**_gpu_config(command_digest), "volumes": ["/host"]},
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
        advertised_accelerators=(GPU_ACCELERATOR,),
    )
    assert result.disposition is SandboxDisposition.FAILED
    assert result.reason_code == "gpu-mount-forbidden"


def test_run_gpu_training_without_host_dirs_is_distinct_from_bind(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import run_gpu_training

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    result = run_gpu_training(
        artifacts,
        GPU_IMAGE,
        config=_gpu_config(command_digest),
        inputs={
            "planDigest": plan_document_digest(plan),
            "planArtifactDigest": artifact,
        },
        advertised_accelerators=(GPU_ACCELERATOR,),
    )
    assert result.reason_code == "gpu-host-dirs-missing"
    assert result.disposition is SandboxDisposition.FAILED


def test_run_gpu_training_without_docker_fails_closed(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import run_gpu_training

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan, _argv, command_digest, artifact = _plan_bundle(artifacts)
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    with pytest.raises(WorkerSandboxError) as captured:
        run_gpu_training(
            artifacts,
            GPU_IMAGE,
            config=_gpu_config(command_digest),
            inputs={
                "planDigest": plan_document_digest(plan),
                "planArtifactDigest": artifact,
            },
            advertised_accelerators=(GPU_ACCELERATOR,),
            data_dir=data,
            model_dir=model,
            output_dir=output,
        )
    assert captured.value.code in {"oci-runtime-missing", "oci-image-missing"}


def test_wsl_cuda_plan_bind_prints_device_zero_and_does_not_execute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    model = tmp_path / "model"
    output = tmp_path / "output"
    data.mkdir()
    model.mkdir()
    output.mkdir()
    plan = ROOT / "examples" / "training-backend" / "valid" / "wsl-cuda-sft.json"
    assert (
        main(
            [
                "training",
                "bind",
                str(plan),
                "--image",
                GPU_IMAGE,
                "--data-dir",
                str(data),
                "--model-dir",
                str(model),
                "--output-dir",
                str(output),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["gpu"] == "not-run"
    assert "device=0" in payload["dockerArgv"]
    assert "all" not in payload["dockerArgv"]
    assert "--memory" in payload["dockerArgv"]
    memory_at = payload["dockerArgv"].index("--memory")
    assert payload["dockerArgv"][memory_at + 1] == "3221225472"


WSL_PLAN_PATH = ROOT / "examples" / "training-backend" / "valid" / "wsl-cuda-sft.json"


def _write_cuda_checkpoint(root: Path, step: int, *, adapter: bytes) -> Path:
    directory = root / f"checkpoint-{step}"
    directory.mkdir(parents=True)
    (directory / "adapter_model.safetensors").write_bytes(adapter)
    (directory / "adapter_config.json").write_text('{"r":8}\n', encoding="utf-8")
    (directory / "optimizer.pt").write_bytes(b"opt-" + adapter[:8])
    (directory / "scheduler.pt").write_bytes(b"sch-" + adapter[:8])
    (directory / "rng_state.pth").write_bytes(b"rng-" + adapter[:8])
    state = {
        "global_step": step,
        "log_history": [{"loss": 1.0 / step} for _ in range(step)],
    }
    (directory / "trainer_state.json").write_text(json.dumps(state), encoding="utf-8")
    return directory


def test_single_checkpoint_does_not_claim_parameters_updated_or_restore(
    tmp_path: Path,
) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-only-once")
    report = _cuda_training_report(output, profile="wsl2-cuda-laptop-8g")
    assert report["parametersUpdated"] is None
    evidence = report["resumeEvidence"]
    assert evidence["kind"] == "checkpoint-state-files"
    assert evidence["optimizer"] == {"present": True, "name": "optimizer.pt"}
    assert evidence["scheduler"] == {"present": True, "name": "scheduler.pt"}
    assert evidence["rng"] == {"present": True, "name": "rng_state.pth"}
    assert evidence["trainerState"] == {"present": True, "name": "trainer_state.json"}
    restore = report["restore"]
    assert restore["executed"] is False
    assert restore["status"] == "unverified"
    assert restore["source"] is None
    assert restore["requestedLoads"] == []
    assert restore["observedLoads"] == {}
    assert restore["fromStep"] is None
    assert restore["toStep"] is None
    assert restore["loadBasis"] is None


def test_two_checkpoints_verify_adapter_change_without_claiming_restore(
    tmp_path: Path,
) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-v2-changed")
    report = _cuda_training_report(output, profile="wsl2-cuda-laptop-8g")
    assert report["parametersUpdated"] is True
    assert report["restore"]["executed"] is False
    assert report["restore"]["status"] == "unverified"


def test_full_checkpoint_restore_separates_requested_and_observed_loads(
    tmp_path: Path,
) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report, snapshot_gpu_checkpoints

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-v2-changed")
    (output / "logging.jsonl").write_text(
        json.dumps({"global_step/max_steps": "11/20", "loss": 0.1}) + "\n",
        encoding="utf-8",
    )
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    restore = report["restore"]
    assert restore["executed"] is True
    assert restore["status"] == "partial"
    assert restore["requestedLoads"] == [
        "weights",
        "optimizer",
        "scheduler",
        "rng",
        "global_step",
    ]
    assert restore["loadBasis"] == "argv --resume_from_checkpoint (requested)"
    assert restore["thisRunCheckpoints"] == ["checkpoint-20"]
    observed = restore["observedLoads"]
    assert observed["global_step"]["status"] == "verified"
    assert observed["global_step"]["detail"] == "11/20"
    assert observed["weights"]["status"] == "verified"
    assert observed["optimizer"]["status"] == "unverified"
    assert observed["scheduler"]["status"] == "unverified"
    assert observed["rng"]["status"] == "unverified"
    assert report["parametersUpdated"] is True


def test_argv_and_step_growth_do_not_verify_all_restore_loads(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report, snapshot_gpu_checkpoints

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-v2-changed")
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    observed = report["restore"]["observedLoads"]
    assert report["restore"]["status"] == "partial"
    assert observed["global_step"]["status"] == "unverified"
    assert observed["global_step"]["basis"] == "step-growth-only"
    assert observed["optimizer"]["status"] == "unverified"
    assert observed["weights"]["status"] == "verified"


def test_leftover_checkpoint_is_not_this_run_product(tmp_path: Path) -> None:
    from llm_research_os.workers.errors import WorkerSandboxError
    from llm_research_os.workers.gpu import _cuda_training_report, snapshot_gpu_checkpoints

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-v2-changed")
    baseline = snapshot_gpu_checkpoints(output)
    with pytest.raises(WorkerSandboxError) as captured:
        _cuda_training_report(
            output,
            profile="wsl2-cuda-laptop-8g",
            resume_mode="full-checkpoint",
            checkpoint_path="/work/output/checkpoint-10",
            baseline=baseline,
        )
    assert captured.value.code == "gpu-checkpoint-stale"


def test_leftover_checkpoint_is_excluded_when_this_run_writes_another(
    tmp_path: Path,
) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report, snapshot_gpu_checkpoints

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-leftover")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 30, adapter=b"adapter-this-run")
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    leftover = output / "checkpoint-20" / "adapter_model.safetensors"
    leftover_digest = "sha256:" + hashlib.sha256(leftover.read_bytes()).hexdigest()
    assert report["restore"]["thisRunCheckpoints"] == ["checkpoint-30"]
    assert report["checkpoint"]["path"] == "checkpoint-30"
    assert report["checkpoint"]["adapterDigest"] != leftover_digest


def test_framework_load_substring_does_not_verify_optimizer(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import _cuda_training_report, snapshot_gpu_checkpoints

    output = tmp_path / "output"
    _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 20, adapter=b"adapter-v2-changed")
    (output / "logging.jsonl").write_text(
        json.dumps({"global_step/max_steps": "11/20", "loss": 0.1})
        + "\nLoading optimizer states from checkpoint-10\n",
        encoding="utf-8",
    )
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    observed = report["restore"]["observedLoads"]
    assert observed["optimizer"]["status"] == "unverified"
    assert observed["optimizer"]["basis"] == "no-trainer-load-hook"
    assert observed["scheduler"]["status"] == "unverified"
    assert observed["rng"]["status"] == "unverified"


def test_prepare_observe_record_does_not_verify_optimizer(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import (
        OBSERVE_FILENAME,
        _cuda_training_report,
        snapshot_gpu_checkpoints,
    )

    output = tmp_path / "output"
    source = _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 12, adapter=b"adapter-v2-changed")
    (output / "logging.jsonl").write_text(
        json.dumps({"global_step/max_steps": "11/12", "loss": 0.1}) + "\n",
        encoding="utf-8",
    )
    (output / OBSERVE_FILENAME).write_text(
        json.dumps(
            {
                "kind": "GpuRestoreObserve",
                "phase": "prepare",
                "name": "optimizer",
                "sourcePath": str(source / "optimizer.pt"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    observed = report["restore"]["observedLoads"]
    assert observed["optimizer"]["status"] == "unverified"
    assert observed["global_step"]["status"] == "verified"


def test_trainer_load_hook_jsonl_verifies_optimizer_only(tmp_path: Path) -> None:
    from llm_research_os.workers.gpu import (
        OBSERVE_FILENAME,
        _cuda_training_report,
        snapshot_gpu_checkpoints,
    )

    output = tmp_path / "output"
    source = _write_cuda_checkpoint(output, 10, adapter=b"adapter-v1")
    baseline = snapshot_gpu_checkpoints(output)
    _write_cuda_checkpoint(output, 12, adapter=b"adapter-v2-changed")
    (output / "logging.jsonl").write_text(
        json.dumps({"global_step/max_steps": "11/12", "loss": 0.1}) + "\n",
        encoding="utf-8",
    )
    digest = "sha256:" + hashlib.sha256((source / "optimizer.pt").read_bytes()).hexdigest()
    after = {"stateDigest": "sha256:" + ("ab" * 32), "keyCount": 2}
    (output / OBSERVE_FILENAME).write_text(
        json.dumps(
            {
                "kind": "GpuRestoreObserve",
                "phase": "loaded",
                "name": "optimizer",
                "sourcePath": "/work/output/checkpoint-10/optimizer.pt",
                "sourceDigest": digest,
                "after": after,
                "trainerClass": "transformers.trainer.Trainer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = _cuda_training_report(
        output,
        profile="wsl2-cuda-laptop-8g",
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
        baseline=baseline,
    )
    observed = report["restore"]["observedLoads"]
    assert observed["optimizer"]["status"] == "verified"
    assert observed["optimizer"]["basis"] == "trainer-load-hook"
    assert observed["optimizer"]["sourceDigest"] == digest
    assert observed["optimizer"]["after"] == after
    assert observed["scheduler"]["status"] == "unverified"
    assert observed["rng"]["status"] == "unverified"
    identity = report["restore"]["observeIdentity"]
    assert type(identity["observeDigest"]) is str
    assert identity["observeDigest"].startswith("sha256:")


def test_wsl_resume_overlay_is_bound_into_authorized_command(tmp_path: Path) -> None:
    from llm_research_os.training.requests import load_wsl_cuda_training_plan
    from llm_research_os.training.wsl_bind import (
        bind_ms_swift_wsl_cuda_command,
    )
    from llm_research_os.training.wsl_bind import (
        plan_document_digest as wsl_plan_digest,
    )
    from llm_research_os.workers.gpu import _authorized_gpu_command

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan = load_wsl_cuda_training_plan(WSL_PLAN_PATH)
    stored = artifacts.put(WSL_PLAN_PATH)
    overlay_argv, overlay_digest = bind_ms_swift_wsl_cuda_command(
        plan,
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/checkpoint-10",
    )
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config={
            "network": "denied",
            "device": GPU_DEVICE,
            "profile": "wsl2-cuda-laptop-8g",
            "commandDigest": overlay_digest,
            "resume": "full-checkpoint",
            "checkpoint": "/work/output/checkpoint-10",
        },
        inputs={
            "planDigest": wsl_plan_digest(plan),
            "planArtifactDigest": stored.digest,
        },
    )
    command_argv, digest = _authorized_gpu_command(artifacts, policy)
    assert digest == overlay_digest
    assert command_argv == overlay_argv
    assert "--resume_from_checkpoint" in command_argv
    assert "/work/output/checkpoint-10" in command_argv


def test_wsl_resume_without_matching_command_digest_fails_closed(tmp_path: Path) -> None:
    from llm_research_os.training.requests import load_wsl_cuda_training_plan
    from llm_research_os.training.wsl_bind import (
        bind_ms_swift_wsl_cuda_command,
    )
    from llm_research_os.training.wsl_bind import (
        plan_document_digest as wsl_plan_digest,
    )
    from llm_research_os.workers.gpu import _authorized_gpu_command

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    plan = load_wsl_cuda_training_plan(WSL_PLAN_PATH)
    stored = artifacts.put(WSL_PLAN_PATH)
    _plain_argv, plain_digest = bind_ms_swift_wsl_cuda_command(plan)
    policy = parse_gpu_launch_policy(
        image_digest=GPU_IMAGE,
        config={
            "network": "denied",
            "device": GPU_DEVICE,
            "profile": "wsl2-cuda-laptop-8g",
            "commandDigest": plain_digest,
            "resume": "full-checkpoint",
            "checkpoint": "/work/output/checkpoint-10",
        },
        inputs={
            "planDigest": wsl_plan_digest(plan),
            "planArtifactDigest": stored.digest,
        },
    )
    with pytest.raises(WorkerSandboxError) as captured:
        _authorized_gpu_command(artifacts, policy)
    assert captured.value.code == "execution-binding-mismatch"


def test_resume_none_rejects_checkpoint_path() -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_gpu_launch_policy(
            image_digest=GPU_IMAGE,
            config={
                "network": "denied",
                "device": GPU_DEVICE,
                "profile": "wsl2-cuda-laptop-8g",
                "commandDigest": _JCS_A,
                "resume": "none",
                "checkpoint": "/work/output/checkpoint-10",
            },
            inputs={"planDigest": _JCS_A, "planArtifactDigest": GPU_IMAGE},
        )
    assert captured.value.code == "resume-overlay-conflict"
