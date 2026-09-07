from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_worker_protocol import HMAC_KEY, PROJECT, SOURCE, FrozenClock

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli import main
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m2 import mps_prove as mps_prove_mod
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.training.checkpoint import (
    MAX_MPS_CHECKPOINT_FILES,
    MAX_MPS_SNAPSHOT_FILE_BYTES,
    MAX_PUT_BYTES,
    collect_output_artifacts,
    list_tree_files,
    tree_digest,
)
from llm_research_os.training.errors import TrainingBackendError
from llm_research_os.training.mps_bind import bind_ms_swift_mps_command, plan_document_digest
from llm_research_os.training.requests import load_mac_mps_training_plan
from llm_research_os.workers import mps as mps_mod
from llm_research_os.workers.binding import brick_execution_digest
from llm_research_os.workers.errors import WorkerCallError, WorkerSandboxError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_MPS_ENV,
    WORKER_RUNTIME_GPU_OCI,
    WORKER_RUNTIME_MACOS_MPS,
    WORKER_RUNTIME_OCI_CONTAINER,
)
from llm_research_os.workers.mps import (
    DEFAULT_MPS_WALL_SECONDS,
    MPS_ACCELERATOR,
    MpsEnvironmentReceipt,
    execute_mps_training,
    live_environment_document,
    mps_integration_required,
    parse_mps_launch_policy,
)
from llm_research_os.workers.oci import parse_oci_launch_policy
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.sandbox import SandboxDisposition

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-mps-checkpoint"
PLAN_PATH = CORPUS / "plan.json"
AUTH = CORPUS / "authorization-event.json"
NOW = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)


def _artifacts(tmp_path: Path) -> LocalArtifactStore:
    root = tmp_path / "artifacts"
    root.mkdir()
    return LocalArtifactStore(root)


def _workspace(tmp_path: Path, *, stub_marker: bool = True) -> Path:
    work = tmp_path / "work"
    shutil.copytree(CORPUS / "model", work / "model")
    shutil.copytree(CORPUS / "data", work / "data")
    (work / "output").mkdir(parents=True)
    stub = work / "bin" / "swift"
    stub.parent.mkdir(parents=True)
    shutil.copyfile(CORPUS / "stub-swift.py", stub)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    if stub_marker:
        (stub.parent / ".mps-stub").write_text("1\n", encoding="utf-8")
    return work


def _tree_digest(path: Path) -> str:
    digest = tree_digest(
        list_tree_files(
            path,
            max_files=MAX_MPS_CHECKPOINT_FILES,
            max_file_bytes=MAX_MPS_SNAPSHOT_FILE_BYTES,
        )
    )
    assert digest is not None
    return digest


def _mps_config(command_digest: str) -> dict[str, object]:
    return {
        "network": "denied",
        "accDevice": MPS_ACCELERATOR,
        "isolation": "process-group",
        "commandDigest": command_digest,
        "wallTimeSeconds": DEFAULT_MPS_WALL_SECONDS,
        "resume": "none",
    }


def _inputs(plan_digest: str, plan_artifact: str, dataset: str, model: str) -> dict[str, object]:
    return {
        "planDigest": plan_digest,
        "planArtifactDigest": plan_artifact,
        "datasetDigest": dataset,
        "modelDigest": model,
    }


def _spec(
    image_digest: str,
    command_digest: str,
    plan_digest: str,
    plan_artifact: str,
    dataset: str,
    model: str,
) -> ResearchSpec:
    payload = snapshot_json_document(load_document(CORPUS / "spec.yaml", reject_symlinks=True))
    assert type(payload) is dict
    workflows = payload["workflows"]
    assert type(workflows) is list
    graph = workflows[0]["graph"]
    node = graph["nodes"][0]
    node["config"]["imageDigest"] = image_digest
    node["config"]["config"]["commandDigest"] = command_digest
    node["config"]["inputs"] = _inputs(plan_digest, plan_artifact, dataset, model)
    return ResearchSpec.model_validate(payload)


def _record_mps_authorization(store: EventStore, spec: ResearchSpec) -> tuple[str, str]:
    registry = build_registry([CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id="workflow.mps")
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.mps",),
    )
    result = authorize_plan(report, policy)
    document = snapshot_json_document(load_document(AUTH, reject_symlinks=True))
    assert type(document) is dict
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


def test_cpu_oci_policy_rejects_mps_keys() -> None:
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest="sha256:" + ("0" * 64),
            config={"network": "denied", "accDevice": "mps"},
            inputs={"brickDigest": "sha256:" + ("0" * 64)},
        )
    assert captured.value.code == "oci-mount-forbidden"


def test_mps_policy_rejects_docker_and_privileged(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    with pytest.raises(WorkerSandboxError) as captured:
        parse_mps_launch_policy(
            image_digest=env.digest,
            config={**_mps_config(command_digest), "privileged": True},
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
        )
    assert captured.value.code == "mps-isolation-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_mps_launch_policy(
            image_digest=env.digest,
            config={**_mps_config(command_digest), "gpus": "all"},
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
        )
    assert captured.value.code == "mps-isolation-forbidden"


def _valid_policy_args(tmp_path: Path) -> tuple[str, dict[str, object], dict[str, object]]:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    return (
        env.digest,
        _mps_config(command_digest),
        _inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    (
        (
            lambda image, config, inputs: ("sha256:deadbeef", config, inputs),
            "mps-env-invalid",
        ),
        (
            lambda image, config, inputs: (image, {**config, "network": "bridge"}, inputs),
            "mps-isolation-forbidden",
        ),
        (
            lambda image, config, inputs: (image, {**config, "accDevice": "cuda"}, inputs),
            "accelerator-missing",
        ),
        (
            lambda image, config, inputs: (image, {**config, "isolation": "oci"}, inputs),
            "mps-isolation-forbidden",
        ),
        (
            lambda image, config, inputs: (image, {**config, "extra": True}, inputs),
            "mps-isolation-forbidden",
        ),
        (
            lambda image, config, inputs: (
                image,
                {**config, "commandDigest": "not-a-digest"},
                inputs,
            ),
            "execution-binding-mismatch",
        ),
        (
            lambda image, config, inputs: (image, {**config, "wallTimeSeconds": 0}, inputs),
            "mps-resource-limit",
        ),
        (
            lambda image, config, inputs: (image, {**config, "resume": "maybe"}, inputs),
            "resume-overlay-conflict",
        ),
        (
            lambda image, config, inputs: (image, {**config, "checkpoint": "output/x"}, inputs),
            "resume-overlay-conflict",
        ),
        (
            lambda image, config, inputs: (
                image,
                {**config, "resume": "full-checkpoint", "checkpoint": "/tmp/x"},
                inputs,
            ),
            "mps-isolation-forbidden",
        ),
        (
            lambda image, config, inputs: (image, config, {**inputs, "secret": "1"}),
            "mps-isolation-forbidden",
        ),
        (
            lambda image, config, inputs: (image, config, {**inputs, "planDigest": "not-a-digest"}),
            "execution-binding-mismatch",
        ),
        (
            lambda image, config, inputs: (
                image,
                config,
                {**inputs, "datasetDigest": "not-a-digest"},
            ),
            "execution-binding-mismatch",
        ),
        (
            lambda image, config, inputs: (
                image,
                config,
                {**inputs, "modelDigest": "not-a-digest"},
            ),
            "execution-binding-mismatch",
        ),
        (
            lambda image, config, inputs: (
                image,
                config,
                {**inputs, "planArtifactDigest": "sha256:00"},
            ),
            "execution-binding-mismatch",
        ),
    ),
)
def test_mps_policy_rejects_invalid_objects(
    tmp_path: Path,
    mutate: object,
    code: str,
) -> None:
    image, config, inputs = _valid_policy_args(tmp_path)
    bad_image, bad_config, bad_inputs = mutate(image, config, inputs)  # type: ignore[operator]
    with pytest.raises(WorkerSandboxError) as captured:
        parse_mps_launch_policy(image_digest=bad_image, config=bad_config, inputs=bad_inputs)
    assert captured.value.code == code


def test_mps_plan_prints_argv_without_claiming_execution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["training", "plan", str(PLAN_PATH), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "TrainingBackendPlanReceipt"
    assert payload["executed"] is False
    assert payload["argv"][0:2] == ["swift", "sft"]
    assert "--device_map" not in payload["argv"]
    assert "--model_type" in payload["argv"]
    assert "qwen2" in payload["argv"]
    assert "--template" in payload["argv"]
    assert "qwen2_5" in payload["argv"]
    assert "--add_version" in payload["argv"]
    assert payload["argv"][payload["argv"].index("--add_version") + 1] == "false"
    assert "--optim" in payload["argv"]
    assert "adamw_torch" in payload["argv"]
    assert "--max_length" in payload["argv"]
    assert "256" in payload["argv"]
    assert "--acc_device" not in payload["argv"]


def test_mps_extra_field_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    path = ROOT / "examples" / "training-backend" / "invalid" / "mac-mps-extra-field.json"
    assert main(["training", "plan", str(path), "--format", "json"]) == 2
    err = capsys.readouterr().err.lower()
    assert "extra" in err or "valid" in err


def test_full_checkpoint_overlay_is_not_adapter_only(capsys: pytest.CaptureFixture[str]) -> None:
    plan = load_mac_mps_training_plan(PLAN_PATH)
    full, full_digest = bind_ms_swift_mps_command(
        plan,
        resume_mode="full-checkpoint",
        checkpoint_path="output/checkpoint-10",
    )
    adapter, adapter_digest = bind_ms_swift_mps_command(
        plan,
        resume_mode="adapter-only",
        checkpoint_path="output/checkpoint-10",
    )
    assert full_digest != adapter_digest
    assert "--resume_from_checkpoint" in full
    assert "--adapters" not in full
    assert "--adapters" in adapter
    assert "--resume_from_checkpoint" not in adapter
    assert (
        main(
            [
                "training",
                "overlay",
                str(PLAN_PATH),
                "--resume",
                "full-checkpoint",
                "--checkpoint",
                "output/checkpoint-10",
                "--format",
                "json",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert "optimizer" in receipt["loads"]
    assert "scheduler" in receipt["loads"]
    assert "rng" in receipt["loads"]
    assert "global_step" in receipt["loads"]
    assert receipt["executed"] is False


def test_execute_mps_stub_updates_parameters_and_records_finite_loss(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_argv, command_digest = bind_ms_swift_mps_command(plan)
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    result = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(command_digest),
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
        timeout_seconds=30,
    )
    assert result.disposition is SandboxDisposition.SUCCEEDED
    report = json.loads(result.stdout.decode("utf-8"))
    assert report["executed"] is True
    assert report["device"] == "mps"
    assert report["cpuFallback"] is False
    assert report["ociIsolationClaimed"] is False
    assert report["isolation"] == "process-group"
    assert report["lossFinite"] is True
    assert report["globalStep"] == 20
    assert report["checkpoint"]["optimizer"] is True
    assert report["checkpoint"]["scheduler"] is True
    assert report["checkpoint"]["rng"] is True
    assert report["parametersUpdated"] is True
    assert command_argv[0] == "swift"


def test_mps_full_resume_is_step_continuous_adapter_only_is_not(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    first_digest = bind_ms_swift_mps_command(plan)[1]
    first = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(first_digest),
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
        timeout_seconds=30,
    )
    assert first.disposition is SandboxDisposition.SUCCEEDED
    optimizer_ten = (work / "output" / "checkpoint-10" / "optimizer.pt").read_bytes()
    shutil.rmtree(work / "output" / "checkpoint-20")
    full_argv, full_digest = bind_ms_swift_mps_command(
        plan,
        resume_mode="full-checkpoint",
        checkpoint_path="output/checkpoint-10",
    )
    config = _mps_config(full_digest)
    config["resume"] = "full-checkpoint"
    config["checkpoint"] = "output/checkpoint-10"
    resumed = execute_mps_training(
        artifacts,
        env.digest,
        config=config,
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
        timeout_seconds=30,
    )
    assert resumed.disposition is SandboxDisposition.SUCCEEDED
    report = json.loads(resumed.stdout.decode("utf-8"))
    assert report["globalStep"] == 20
    assert "--resume_from_checkpoint" in full_argv
    assert (work / "output" / "checkpoint-20" / "optimizer.pt").read_bytes() != optimizer_ten

    adapter_dir = tmp_path / "adapter-work"
    shutil.copytree(work, adapter_dir)
    adapter_output = adapter_dir / "output"
    shutil.rmtree(adapter_output / "checkpoint-20", ignore_errors=True)
    adapter_argv, adapter_digest = bind_ms_swift_mps_command(
        plan,
        resume_mode="adapter-only",
        checkpoint_path="output/checkpoint-10",
    )
    adapter_config = _mps_config(adapter_digest)
    adapter_config["resume"] = "adapter-only"
    adapter_config["checkpoint"] = "output/checkpoint-10"
    adapter = execute_mps_training(
        artifacts,
        env.digest,
        config=adapter_config,
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(adapter_dir / "data"),
            _tree_digest(adapter_dir / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=adapter_dir / "data",
        model_dir=adapter_dir / "model",
        output_dir=adapter_output,
        interpreter=adapter_dir / "bin" / "swift",
        timeout_seconds=30,
    )
    assert adapter.disposition is SandboxDisposition.SUCCEEDED
    assert "--adapters" in adapter_argv
    optimizer = (adapter_output / "checkpoint-20" / "optimizer.pt").read_bytes()
    assert b"optimizer-adapter-only" in optimizer


def test_mps_collect_accepts_real_checkpoint_size(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    payload = output / "adapter_model.safetensors"
    payload.write_bytes(b"x" * (MAX_PUT_BYTES + 64))
    (output / "optimizer.pt").write_bytes(b"opt")
    (output / "scheduler.pt").write_bytes(b"sched")
    (output / "rng_state.pth").write_bytes(b"rng")
    (output / "trainer_state.json").write_text('{"global_step": 20}\n', encoding="utf-8")
    artifacts = _artifacts(tmp_path)
    with pytest.raises(TrainingBackendError) as captured:
        collect_output_artifacts(output, artifacts)
    assert captured.value.code == "gpu-resource-limit"
    receipt = collect_output_artifacts(
        output,
        artifacts,
        max_files=64,
        max_file_bytes=268_435_456,
        max_upload_bytes=268_435_456,
    )
    assert receipt.status == "complete"
    assert any(item.size > MAX_PUT_BYTES for item in receipt.files)
    assert (
        main(
            [
                "training",
                "collect",
                str(output),
                "--artifacts",
                str(tmp_path / "cli-artifacts"),
                "--profile",
                "mps",
                "--format",
                "json",
            ]
        )
        == 0
    )


def test_mps_cancel_is_observed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    monkeypatch.setenv("RESEARCHOS_MPS_STUB_SLEEP", "30")
    calls = {"n": 0}

    def cancel_after_start() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    identity_dir = tmp_path / "identities"
    identity_dir.mkdir()
    result = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(command_digest),
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
        identity_dir=identity_dir,
        lease_id="lease.mps.cancel",
        should_cancel=cancel_after_start,
        timeout_seconds=10,
    )
    assert result.reason_code == "cancel-observed"
    assert result.disposition is SandboxDisposition.FAILED


def test_cpu_probe_is_fail_closed_not_disguised_as_mps(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env_path = tmp_path / "env.json"
    env_path.write_text(
        json.dumps(
            {
                "kind": "MacMpsEnvironment",
                "backendId": "ms-swift",
                "backendVersion": "4.5.2",
                "python": "3.12",
                "torch": "2.14.0",
                "accelerator": "mps",
                "stub": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    env = artifacts.put(env_path)
    work = _workspace(tmp_path, stub_marker=False)
    python = work / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo \'{"device":"cpu","torch":"2.14.0","swift":"4.5.2",'
        '"python":"3.12","stub":"false"}\'\n',
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
            timeout_seconds=10,
        )
    assert captured.value.code == "mps-unavailable"


def test_oci_container_worker_cannot_lease_mps_work(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    spec = _spec(
        env.digest,
        command_digest,
        plan_document_digest(plan),
        stored.digest,
        _tree_digest(work / "data"),
        _tree_digest(work / "model"),
    )
    registry = build_registry([CORPUS / "block.json"])
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        event_id, sequence = _record_mps_authorization(store, spec)
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
            event_id="evt.worker.registered.oci.for-mps",
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
            accelerators=(MPS_ACCELERATOR,),
        )
        config = _mps_config(command_digest)
        inputs = _inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        )
        config_digest = brick_execution_digest(
            image_digest=env.digest,
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
        )
        plane.record_grant(
            grant_id="grant.mps.oci-worker",
            worker_id="worker.oci.1",
            task_id="task.mps",
            run_id="run.worker.mps",
            attempt_id="attempt.worker.mps.1",
            nonce="nonce.mps.oci-worker",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.mps.oci-worker",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=env.digest,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-08T00:00:00Z",
            workflow_id="workflow.mps",
        )
        plane.enqueue(
            task_id="task.mps",
            run_id="run.worker.mps",
            attempt_id="attempt.worker.mps.1",
            image_digest=env.digest,
            event_id="evt.work.queued.task.mps",
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
            required_accelerators=(MPS_ACCELERATOR,),
            time="2026-09-08T00:00:00Z",
        )
        token = plane.issue_token("grant.mps.oci-worker")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.oci.1", grant_token=token)
        assert captured.value.code == "runtime-mismatch"


def test_gpu_worker_cannot_lease_mps_work(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    spec = _spec(
        env.digest,
        command_digest,
        plan_document_digest(plan),
        stored.digest,
        _tree_digest(work / "data"),
        _tree_digest(work / "model"),
    )
    registry = build_registry([CORPUS / "block.json"])
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        event_id, sequence = _record_mps_authorization(store, spec)
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
            event_id="evt.worker.registered.gpu.for-mps",
            runtime=WORKER_RUNTIME_GPU_OCI,
            accelerators=("cuda", MPS_ACCELERATOR),
        )
        config = _mps_config(command_digest)
        inputs = _inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        )
        config_digest = brick_execution_digest(
            image_digest=env.digest,
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
        )
        plane.record_grant(
            grant_id="grant.mps.gpu-worker",
            worker_id="worker.gpu.1",
            task_id="task.mps",
            run_id="run.worker.mps",
            attempt_id="attempt.worker.mps.1",
            nonce="nonce.mps.gpu-worker",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.mps.gpu-worker",
            authorization_event_id=event_id,
            authorization_sequence=sequence,
            image_digest=env.digest,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-08T00:00:00Z",
            workflow_id="workflow.mps",
        )
        plane.enqueue(
            task_id="task.mps",
            run_id="run.worker.mps",
            attempt_id="attempt.worker.mps.1",
            image_digest=env.digest,
            event_id="evt.work.queued.task.mps",
            config=config,
            inputs=inputs,
            image_media_type=IMAGE_MEDIA_MPS_ENV,
            runtime=WORKER_RUNTIME_MACOS_MPS,
            required_accelerators=(MPS_ACCELERATOR,),
            time="2026-09-08T00:00:00Z",
        )
        token = plane.issue_token("grant.mps.gpu-worker")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.gpu.1", grant_token=token)
        assert captured.value.code == "runtime-mismatch"


def test_m2_mps_prove_records_work_completed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "mps.db"
    artifacts = tmp_path / "artifacts"
    assert (
        main(
            [
                "m2",
                "mps",
                str(CORPUS),
                str(database),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "M2CheckpointReceipt"
    assert "work.completed" in payload["eventTypes"]
    assert payload["runId"] == "run.worker.mps"


def test_m2_mps_live_followups_on_stub(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    monkeypatch.setattr("llm_research_os.m2.mps_prove._live_swift", lambda _interpreter: True)
    monkeypatch.setenv("RESEARCHOS_MPS_STUB_SLEEP", "2")
    database = tmp_path / "mps-live.db"
    artifacts = tmp_path / "artifacts"
    assert (
        main(
            [
                "m2",
                "mps",
                str(corpus),
                str(database),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert "run.cancelled" in payload["eventTypes"]
    evidence = json.loads((corpus / "live-evidence.json").read_text(encoding="utf-8"))
    assert evidence["cancel"]["observed"] is True
    assert evidence["cancel"]["reasonCode"] == "cancel-observed"
    assert "evt.run.cancel.requested.mps" in evidence["cancel"]["eventIds"]
    assert evidence["resume"]["fromStep"] == 10
    assert evidence["resume"]["toStep"] == 20
    assert evidence["resume"]["adapterOnly"] is False
    assert evidence["resume"]["argvFlags"] == [
        "--resume_from_checkpoint",
        "output/checkpoint-10",
    ]
    observed = evidence["resume"]["observed"]
    assert observed["globalStep"]["continuous"] is True
    assert observed["optimizer"]["digestChanged"] is True
    assert observed["scheduler"]["digestChanged"] is True
    assert observed["rng"]["status"] in {
        "bytes-changed",
        "file-present-digest-unchanged",
    }
    assert type(observed["rng"]["digestBefore"]) is str
    assert type(observed["rng"]["digestAfter"]) is str
    assert evidence["cpuFallbackBasis"]["probeDevice"] == "mps"
    assert evidence["memory"]["mpsAllocatedStatus"] == "unmeasured"
    assert evidence["checkpoint10BeforeResume"]["path"] == "output/checkpoint-10"
    assert evidence["collect"]["status"] == "complete"
    assert evidence["cudaOci"] == "pending-live"
    assert evidence["twoHost"] == "pending-live"


def test_mps_execute_refuses_missing_accelerator_and_missing_dataset(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    inputs = _inputs(
        plan_document_digest(plan),
        stored.digest,
        _tree_digest(work / "data"),
        _tree_digest(work / "model"),
    )
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=inputs,
            advertised_accelerators=("cuda",),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "accelerator-missing"
    (work / "data" / "sft.jsonl").unlink()
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=inputs,
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "snapshot-path-invalid"


def test_mps_execute_failed_swift_is_brick_failed(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    swift = work / "bin" / "swift"
    swift.write_text("#!/bin/sh\necho fail >&2\nexit 1\n", encoding="utf-8")
    swift.chmod(swift.stat().st_mode | stat.S_IXUSR)
    result = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(command_digest),
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=swift,
        timeout_seconds=10,
    )
    assert result.disposition is SandboxDisposition.FAILED
    assert result.reason_code == "worker.brick.failed"


def test_mps_execute_timeout_stays_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    monkeypatch.setenv("RESEARCHOS_MPS_STUB_SLEEP", "30")
    result = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(command_digest),
        inputs=_inputs(
            plan_document_digest(plan),
            stored.digest,
            _tree_digest(work / "data"),
            _tree_digest(work / "model"),
        ),
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
        timeout_seconds=1,
    )
    assert result.disposition is SandboxDisposition.UNKNOWN
    assert result.reason_code == "worker.process.timeout"


def test_live_environment_document_fail_closed_on_cpu(tmp_path: Path) -> None:
    work = _workspace(tmp_path, stub_marker=False)
    python = work / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo \'{"device":"cpu","torch":"2.14.0","swift":"4.5.2",'
        '"python":"3.12","stub":"false"}\'\n',
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(WorkerSandboxError) as captured:
        live_environment_document(work / "bin" / "swift")
    assert captured.value.code == "mps-unavailable"


def test_mps_integration_required_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCHOS_MPS_REQUIRED", raising=False)
    assert mps_integration_required() is False
    monkeypatch.setenv("RESEARCHOS_MPS_REQUIRED", "1")
    assert mps_integration_required() is True


def test_invalid_environment_receipt_fails(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env_path = tmp_path / "bad-env.json"
    env_path.write_text('{"kind":"Nope"}\n', encoding="utf-8")
    env = artifacts.put(env_path)
    work = _workspace(tmp_path)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "mps-env-invalid"


def test_mps_dataset_digest_mismatch(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    inputs = _inputs(
        plan_document_digest(plan),
        stored.digest,
        "jcs-sha256:" + ("a" * 64),
        _tree_digest(work / "model"),
    )
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=inputs,
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "execution-binding-mismatch"


def test_mps_command_digest_mismatch(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    config = _mps_config("jcs-sha256:" + ("a" * 64))
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=config,
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "execution-binding-mismatch"


def test_mps_model_digest_mismatch(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                "jcs-sha256:" + ("b" * 64),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "execution-binding-mismatch"


def test_mps_plan_artifact_must_be_mac_plan(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    gpu_plan = ROOT / "examples" / "training-backend" / "valid" / "ms-swift-sft.json"
    stored = artifacts.put(gpu_plan)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "execution-binding-mismatch"


def test_mps_environment_must_be_json(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put_bytes(b"not-json")
    work = _workspace(tmp_path)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "mps-env-invalid"


def test_live_environment_document_accepts_mps_probe(tmp_path: Path) -> None:
    work = _workspace(tmp_path, stub_marker=False)
    python = work / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo \'{"device":"mps","torch":"2.14.0","swift":"4.5.2",'
        '"python":"3.12","stub":"false"}\'\n',
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    shim = tmp_path / "pythonpath" / "sitecustomize.py"
    shim.parent.mkdir()
    shim.write_text("x\n", encoding="utf-8")
    document = live_environment_document(work / "bin" / "swift")
    assert document["accelerator"] == "mps"
    assert document["stub"] is False
    assert document["torch"] == "2.14.0"
    assert document["probeDevice"] == "mps"
    assert document["deviceMapArgv"] == "absent"
    assert document["sitecustomizeDigest"].startswith("sha256:")


def test_live_environment_document_requires_sitecustomize(tmp_path: Path) -> None:
    work = _workspace(tmp_path, stub_marker=False)
    python = work / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo \'{"device":"mps","torch":"2.14.0","swift":"4.5.2",'
        '"python":"3.12","stub":"false"}\'\n',
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(WorkerSandboxError) as captured:
        live_environment_document(work / "bin" / "swift")
    assert captured.value.code == "mps-runtime-missing"


def test_mps_missing_host_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    monkeypatch.delenv("RESEARCHOS_MPS_DATA_DIR", raising=False)
    monkeypatch.delenv("RESEARCHOS_MPS_MODEL_DIR", raising=False)
    monkeypatch.delenv("RESEARCHOS_MPS_OUTPUT_DIR", raising=False)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(work / "model"),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "mps-workspace-missing"


def test_mps_workspace_layout_is_required(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "model"
    shutil.copytree(work / "model", elsewhere)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=_inputs(
                plan_document_digest(plan),
                stored.digest,
                _tree_digest(work / "data"),
                _tree_digest(elsewhere),
            ),
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=elsewhere,
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
        )
    assert captured.value.code == "mps-workspace-missing"


def test_mps_execute_invalid_wall_and_popen_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    plan = load_mac_mps_training_plan(PLAN_PATH)
    command_digest = bind_ms_swift_mps_command(plan)[1]
    stored = artifacts.put(PLAN_PATH)
    env = artifacts.put(CORPUS / "environment.json")
    work = _workspace(tmp_path)
    inputs = _inputs(
        plan_document_digest(plan),
        stored.digest,
        _tree_digest(work / "data"),
        _tree_digest(work / "model"),
    )
    with pytest.raises(WorkerSandboxError) as captured:
        execute_mps_training(
            artifacts,
            env.digest,
            config=_mps_config(command_digest),
            inputs=inputs,
            advertised_accelerators=(MPS_ACCELERATOR,),
            data_dir=work / "data",
            model_dir=work / "model",
            output_dir=work / "output",
            interpreter=work / "bin" / "swift",
            timeout_seconds=0,
        )
    assert captured.value.code == "mps-resource-limit"

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr(mps_mod.subprocess, "Popen", _boom)
    lost = execute_mps_training(
        artifacts,
        env.digest,
        config=_mps_config(command_digest),
        inputs=inputs,
        advertised_accelerators=(MPS_ACCELERATOR,),
        data_dir=work / "data",
        model_dir=work / "model",
        output_dir=work / "output",
        interpreter=work / "bin" / "swift",
    )
    assert lost.reason_code == "worker.process.lost"
    assert lost.disposition is SandboxDisposition.UNKNOWN


def test_mps_helper_negative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert mps_mod._rss_bytes(None) == 0
    monkeypatch.setattr(mps_mod.shutil, "which", lambda _name: None)
    assert mps_mod._rss_bytes(1) == 0
    ps = tmp_path / "ps"
    ps.write_text("#!/bin/sh\necho nope\n", encoding="utf-8")
    ps.chmod(ps.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(mps_mod.shutil, "which", lambda name: str(ps) if name == "ps" else None)
    assert mps_mod._rss_bytes(1) == 0
    ps.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    assert mps_mod._rss_bytes(1) == 0

    def _timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ps", timeout=1)

    monkeypatch.setattr(mps_mod.subprocess, "run", _timeout)
    assert mps_mod._rss_bytes(1) == 0

    missing = tmp_path / "missing.log"
    assert mps_mod._log_tail(missing) is None
    missing.write_text("", encoding="utf-8")
    assert mps_mod._log_tail(missing) is None
    assert mps_mod._fallback_ops(tmp_path / "no-log") == []
    log = tmp_path / "train.log"
    log.write_text(
        "\n".join(
            f"op{index} is not currently implemented for the MPS device" for index in range(10)
        )
        + "\n",
        encoding="utf-8",
    )
    assert len(mps_mod._fallback_ops(log)) == 8
    assert mps_mod._losses({}, log) == []
    log.write_text("{'loss': 1.25}\n\"loss\": 0.5\nskip\n", encoding="utf-8")
    assert mps_mod._losses({"log_history": []}, log) == [1.25, 0.5]

    checkpoint = tmp_path / "checkpoint-1"
    checkpoint.mkdir()
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._trainer_state(checkpoint)
    assert captured.value.code == "mps-checkpoint-missing"
    (checkpoint / "trainer_state.json").write_text("{", encoding="utf-8")
    with pytest.raises(WorkerSandboxError):
        mps_mod._trainer_state(checkpoint)
    (checkpoint / "trainer_state.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(WorkerSandboxError):
        mps_mod._trainer_state(checkpoint)

    plan = load_mac_mps_training_plan(PLAN_PATH)
    probe = {"device": "mps", "torch": "2.14.0", "python": "3.12.13", "stub": "true"}
    receipt = MpsEnvironmentReceipt(
        kind="MacMpsEnvironment",
        backend_id="ms-swift",
        backend_version="4.5.2",
        python="3.12.13",
        torch="2.14.0",
        accelerator="mps",
        stub=True,
    )
    empty = tmp_path / "empty-out"
    empty.mkdir()
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._training_report(
            empty,
            plan=plan,
            probe=probe,
            environment=receipt,
            wall_seconds=1.0,
            peak_rss_bytes=1,
            log_path=log,
        )
    assert captured.value.code == "mps-checkpoint-missing"

    first = empty / "checkpoint-10"
    last = empty / "checkpoint-20"
    for path, _step in ((first, 10), (last, 20)):
        path.mkdir()
        (path / "adapter_model.safetensors").write_bytes(b"same-adapter")
        (path / "optimizer.pt").write_bytes(b"opt")
        (path / "scheduler.pt").write_bytes(b"sch")
        (path / "rng_state.pth").write_bytes(b"rng")
        (path / "trainer_state.json").write_text(
            json.dumps({"global_step": 0, "log_history": [{"loss": 1.0}]}),
            encoding="utf-8",
        )
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._training_report(
            empty,
            plan=plan,
            probe=probe,
            environment=receipt,
            wall_seconds=1.0,
            peak_rss_bytes=1,
            log_path=log,
        )
    assert captured.value.code == "mps-checkpoint-missing"
    (first / "trainer_state.json").write_text(
        json.dumps({"global_step": 10, "log_history": []}),
        encoding="utf-8",
    )
    (last / "trainer_state.json").write_text(
        json.dumps({"global_step": 20, "log_history": []}),
        encoding="utf-8",
    )
    log.write_text("no losses here\n", encoding="utf-8")
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._training_report(
            empty,
            plan=plan,
            probe=probe,
            environment=receipt,
            wall_seconds=1.0,
            peak_rss_bytes=1,
            log_path=log,
        )
    assert captured.value.code == "mps-loss-invalid"
    (first / "trainer_state.json").write_text(
        json.dumps({"global_step": 10, "log_history": [{"loss": 1.0}]}),
        encoding="utf-8",
    )
    (last / "trainer_state.json").write_text(
        json.dumps({"global_step": 20, "log_history": [{"loss": 0.5}]}),
        encoding="utf-8",
    )
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._training_report(
            empty,
            plan=plan,
            probe=probe,
            environment=receipt,
            wall_seconds=1.0,
            peak_rss_bytes=1,
            log_path=log,
        )
    assert captured.value.code == "mps-parameters-unchanged"

    monkeypatch.setenv("RESEARCHOS_MPS_DATA_DIR", str(tmp_path / "from-env"))
    assert mps_mod._resolve_dir(None, "RESEARCHOS_MPS_DATA_DIR", "data") == tmp_path / "from-env"
    monkeypatch.delenv("RESEARCHOS_MPS_PYTHON", raising=False)
    monkeypatch.setattr(mps_mod.shutil, "which", lambda _name: None)
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._resolve_swift(None)
    assert captured.value.code == "mps-runtime-missing"
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("RESEARCHOS_MPS_PYTHON", str(python))
    assert mps_mod._resolve_swift(None) == python
    sibling = python.parent / "swift"
    sibling.write_text("x\n", encoding="utf-8")
    assert mps_mod._resolve_swift(None) == sibling

    work = tmp_path / "layout"
    (work / "model").mkdir(parents=True)
    (work / "data").mkdir()
    (work / "output").mkdir()
    with pytest.raises(WorkerSandboxError):
        mps_mod._require_workspace(work / "model", tmp_path / "other-data", work / "output")
    with pytest.raises(WorkerSandboxError):
        mps_mod._require_workspace(work / "model", work / "data", tmp_path / "other-output")
    linked = tmp_path / "linked-model"
    linked.symlink_to(work / "model")
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._require_workspace(linked, work / "data", work / "output")
    assert captured.value.code == "snapshot-symlink-forbidden"

    process = subprocess.Popen(["/usr/bin/true"])
    process.wait()
    cancelled = mps_mod._finish_cancelled(process, None, None)
    assert cancelled.reason_code == "cancel-observed"
    sleeper = subprocess.Popen(["/bin/sleep", "30"])
    try:
        unobserved = mps_mod._finish_cancelled(sleeper, None, None)
        assert unobserved.reason_code == mps_mod.UNOBSERVED
    finally:
        sleeper.kill()
        sleeper.wait()


def test_mps_probe_device_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = MpsEnvironmentReceipt(
        kind="MacMpsEnvironment",
        backend_id="ms-swift",
        backend_version="4.5.2",
        python="3.12.13",
        torch="2.14.0",
        accelerator="mps",
        stub=False,
    )
    swift = tmp_path / "bin" / "swift"
    swift.parent.mkdir(parents=True)
    swift.write_text("x\n", encoding="utf-8")
    python = swift.parent / "python"
    python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(WorkerSandboxError) as captured:
        mps_mod._probe_device(swift, receipt)
    assert captured.value.code == "mps-unavailable"
    python.write_text("#!/bin/sh\necho not-json\n", encoding="utf-8")
    with pytest.raises(WorkerSandboxError):
        mps_mod._probe_device(swift, receipt)
    python.write_text("#!/bin/sh\necho '[]'\n", encoding="utf-8")
    with pytest.raises(WorkerSandboxError):
        mps_mod._probe_device(swift, receipt)
    python.unlink()
    monkeypatch.setenv("RESEARCHOS_MPS_PYTHON", str(tmp_path / "missing-python"))
    with pytest.raises(WorkerSandboxError):
        mps_mod._probe_device(swift, receipt)


def test_mps_prove_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCHOS_MPS_PYTHON", raising=False)
    stub = tmp_path / "bin" / "swift"
    stub.parent.mkdir(parents=True)
    stub.write_text("x\n", encoding="utf-8")
    assert mps_prove_mod._live_swift(stub) is False
    monkeypatch.setenv("RESEARCHOS_MPS_PYTHON", str(tmp_path / "python"))
    (stub.parent / ".mps-stub").write_text("1\n", encoding="utf-8")
    assert mps_prove_mod._live_swift(stub) is False
    (stub.parent / ".mps-stub").unlink()
    assert mps_prove_mod._live_swift(stub) is True

    workspace = tmp_path / "ws"
    mps_prove_mod._archive_prior_output(workspace)
    assert (workspace / "output").is_dir()
    mps_prove_mod._archive_prior_output(workspace)
    (workspace / "output" / "keep.txt").write_text("1\n", encoding="utf-8")
    mps_prove_mod._archive_prior_output(workspace)
    assert (workspace / "output.direct-gate" / "keep.txt").is_file()
    (workspace / "output" / "again.txt").write_text("2\n", encoding="utf-8")
    mps_prove_mod._archive_prior_output(workspace)
    assert (workspace / "output.direct-gate" / "again.txt").is_file()

    dest = tmp_path / "copied"
    dest.mkdir()
    mps_prove_mod._copy_tree(workspace / "output", dest)

    python = tmp_path / "interp" / "python"
    python.parent.mkdir()
    python.write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("RESEARCHOS_MPS_PYTHON", str(python))
    assert mps_prove_mod._prepare_interpreter(CORPUS, tmp_path) == python
    sibling = python.parent / "swift"
    sibling.write_text("x\n", encoding="utf-8")
    assert mps_prove_mod._prepare_interpreter(CORPUS, tmp_path) == sibling

    missing = mps_prove_mod._checkpoint_facts(tmp_path / "no-ckpt")
    assert missing["present"] is False
    assert missing["path"] == "no-ckpt"
    ckpt = tmp_path / "checkpoint-10"
    ckpt.mkdir()
    (ckpt / "trainer_state.json").write_text("{", encoding="utf-8")
    facts = mps_prove_mod._checkpoint_facts(ckpt)
    assert facts["globalStep"] is None
    (ckpt / "trainer_state.json").write_text('{"global_step": 10}\n', encoding="utf-8")
    (ckpt / "optimizer.bin").write_bytes(b"opt")
    facts = mps_prove_mod._checkpoint_facts(ckpt)
    assert facts["globalStep"] == 10
    assert facts["optimizer"] is True
    assert type(facts["optimizerDigest"]) is str

    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_resume_config({}, command_digest="x")
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_resume_config({"workflows": [{}]}, command_digest="x")
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_resume_config(
            {"workflows": [{"graph": {"nodes": []}}]}, command_digest="x"
        )
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_resume_config(
            {"workflows": [{"graph": {"nodes": [{}]}}]}, command_digest="x"
        )
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_resume_config(
            {"workflows": [{"graph": {"nodes": [{"config": {}}]}}]},
            command_digest="x",
        )
    mps_prove_mod._patch_resume_config(
        {"workflows": [{"graph": {"nodes": [{"config": {"config": {}}}]}}]},
        command_digest="digest",
    )
    patch_kwargs = {
        "image_digest": "a",
        "command_digest": "b",
        "plan_digest": "c",
        "plan_artifact_digest": "d",
        "dataset_digest": "e",
        "model_digest": "f",
    }
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_spec({}, **patch_kwargs)
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_spec({"workflows": [{}]}, **patch_kwargs)
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_spec({"workflows": [{"graph": {"nodes": []}}]}, **patch_kwargs)
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_spec({"workflows": [{"graph": {"nodes": [{}]}}]}, **patch_kwargs)
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._patch_spec(
            {"workflows": [{"graph": {"nodes": [{"config": {"config": {}}}]}}]},
            **patch_kwargs,
        )

    artifacts = _artifacts(tmp_path)
    listed = artifacts.put_bytes(b"[]")
    with pytest.raises(M2CheckpointError):
        mps_prove_mod._read_json_artifact(artifacts, listed.digest)

    mps_prove_mod._wait_for_identity(None, 0.0)
    ident = tmp_path / "identities"
    ident.mkdir()
    (ident / "lease.json").write_text("{}\n", encoding="utf-8")
    mps_prove_mod._wait_for_identity(ident, 1.0)

    def _sysctl_fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="sysctl", timeout=2)

    monkeypatch.setattr(mps_prove_mod.subprocess, "run", _sysctl_fail)
    host = mps_prove_mod._host_inventory()
    assert host["system"] == os.uname().sysname
    assert host["memBytes"] is None
