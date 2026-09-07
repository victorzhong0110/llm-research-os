from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.cli import main
from llm_research_os.cli.m2_commands import run_m2
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m2.errors import M2CheckpointError
from llm_research_os.m2.oci_prove import prove_oci_loop
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.workers.binding import (
    brick_execution_digest,
    require_authorized_execution_binding,
)
from llm_research_os.workers.errors import WorkerCallError, WorkerSandboxError
from llm_research_os.workers.models import (
    IMAGE_MEDIA_OCI_IMAGE,
    IMAGE_MEDIA_PYTHON_BRICK,
    WORKER_RUNTIME_OCI_CONTAINER,
    WORKER_RUNTIME_PYTHON_SANDBOX,
    WorkQueuedPayload,
)
from llm_research_os.workers.oci import (
    MAX_OCI_SECRETS,
    OciBackend,
    _docker_run_argv,
    _image_identities,
    _resolve_secret_env,
    discover_oci_backend,
    execute_oci_python_brick,
    parse_oci_launch_policy,
    require_pinned_docker_image,
)
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.sandbox import execute_python_brick
from llm_research_os.workers.tokens import HMAC_KEY_BYTES

ROOT = Path(__file__).parents[1]
CPU_CORPUS = ROOT / "examples" / "m2-checkpoint"
OCI_CORPUS = ROOT / "examples" / "m2-oci-checkpoint"
HMAC_KEY = b"a" * HMAC_KEY_BYTES
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
PROJECT = "example-minimal"
SOURCE = "https://researchos.dev/projects/example-minimal"
OCI_IMAGE = "sha256:" + ("0" * 64)
AUTH_EVENT_ID = "evt.authorization.example-minimal.oci.1"


class FrozenClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


def _oci_plan() -> tuple[ResearchSpec, BlockRegistry]:
    return load_spec(OCI_CORPUS / "spec.yaml"), build_registry([OCI_CORPUS / "block.json"])


def _record_oci_authorization(store: EventStore) -> tuple[str, str]:
    spec, registry = _oci_plan()
    report = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.oci",),
    )
    result = authorize_plan(report, policy)
    document = snapshot_json_document(
        load_document(OCI_CORPUS / "authorization-event.json", reject_symlinks=True)
    )
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


def _oci_plane(tmp_path: Path) -> tuple[EventStore, LocalArtifactStore, WorkerPlane, str]:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    store = EventStore(database)
    store.__enter__()
    _record_oci_authorization(store)
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(OCI_CORPUS / "brick.py")
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
        event_id="evt.worker.registered.oci.1",
        time="2026-09-07T12:00:00Z",
        runtime=WORKER_RUNTIME_OCI_CONTAINER,
    )
    return store, artifacts, plane, brick.digest


def _oci_config_digest(brick_digest: str, image_digest: str = OCI_IMAGE) -> str:
    return brick_execution_digest(
        image_digest=image_digest,
        config={"network": "denied"},
        inputs={"brickDigest": brick_digest},
        image_media_type=IMAGE_MEDIA_OCI_IMAGE,
        runtime=WORKER_RUNTIME_OCI_CONTAINER,
    )


def test_parse_oci_launch_policy_pins_digest_and_denies_host_escape() -> None:
    policy = parse_oci_launch_policy(
        image_digest=OCI_IMAGE,
        config={"network": "denied"},
        inputs={"brickDigest": "sha256:" + ("a" * 64)},
    )
    assert policy.network == "denied"
    assert policy.brick_digest.endswith("a" * 64)
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest="python:3.12",
            config={"network": "denied"},
            inputs={"brickDigest": "sha256:" + ("a" * 64)},
        )
    assert captured.value.code == "oci-image-tag-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={"network": "bridge"},
            inputs={"brickDigest": "sha256:" + ("a" * 64)},
        )
    assert captured.value.code == "oci-network-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={"network": "denied", "mounts": ["/etc"]},
            inputs={"brickDigest": "sha256:" + ("a" * 64)},
        )
    assert captured.value.code == "oci-mount-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={"network": "denied", "memoryBytes": 10**12},
            inputs={"brickDigest": "sha256:" + ("a" * 64)},
        )
    assert captured.value.code == "oci-resource-limit"


def test_oci_secrets_are_typed_slots_and_values_stay_off_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(OCI_CORPUS / "brick.py")
    secret = "super-secret-oci-token"
    monkeypatch.setenv("RESEARCHOS_OCI_TOKEN", secret)
    with pytest.raises(WorkerSandboxError) as captured:
        execute_oci_python_brick(
            artifacts,
            OCI_IMAGE,
            config={
                "network": "denied",
                "secrets": [
                    {
                        "env": "TOKEN",
                        "secretRef": {
                            "apiVersion": "researchos.dev/v0alpha1",
                            "kind": "SecretRef",
                            "backend": "env",
                            "name": "RESEARCHOS_OCI_TOKEN",
                        },
                    }
                ],
            },
            inputs={"brickDigest": brick.digest},
        )
    assert captured.value.code in {"oci-runtime-missing", "oci-image-missing"}
    assert secret not in str(captured.value)
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={
                "network": "denied",
                "secrets": [{"env": "not-valid", "secretRef": {}}],
            },
            inputs={"brickDigest": brick.digest},
        )
    assert captured.value.code == "oci-secret-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={"network": "denied", "secrets": {"env": "TOKEN"}},
            inputs={"brickDigest": brick.digest},
        )
    assert captured.value.code == "oci-secret-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={
                "network": "denied",
                "secrets": [
                    {
                        "env": f"TOKEN{index}",
                        "secretRef": {
                            "apiVersion": "researchos.dev/v0alpha1",
                            "kind": "SecretRef",
                            "backend": "env",
                            "name": "RESEARCHOS_OCI_TOKEN",
                        },
                    }
                    for index in range(MAX_OCI_SECRETS + 1)
                ],
            },
            inputs={"brickDigest": brick.digest},
        )
    assert captured.value.code == "oci-secret-forbidden"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={"network": "denied"},
            inputs={"brickDigest": "not-a-digest"},
        )
    assert captured.value.code == "execution-binding-mismatch"
    with pytest.raises(WorkerSandboxError) as captured:
        parse_oci_launch_policy(
            image_digest=OCI_IMAGE,
            config={
                "network": "denied",
                "secrets": [
                    {
                        "env": "TOKEN",
                        "secretRef": {
                            "apiVersion": "researchos.dev/v0alpha1",
                            "kind": "SecretRef",
                            "backend": "env",
                            "name": "RESEARCHOS_OCI_TOKEN",
                        },
                    },
                    {
                        "env": "TOKEN",
                        "secretRef": {
                            "apiVersion": "researchos.dev/v0alpha1",
                            "kind": "SecretRef",
                            "backend": "env",
                            "name": "RESEARCHOS_OCI_TOKEN",
                        },
                    },
                ],
            },
            inputs={"brickDigest": brick.digest},
        )
    assert captured.value.code == "oci-secret-forbidden"


def test_oci_secret_resolution_fails_closed_without_value() -> None:
    policy = parse_oci_launch_policy(
        image_digest=OCI_IMAGE,
        config={
            "network": "denied",
            "secrets": [
                {
                    "env": "TOKEN",
                    "secretRef": {
                        "apiVersion": "researchos.dev/v0alpha1",
                        "kind": "SecretRef",
                        "backend": "env",
                        "name": "RESEARCHOS_OCI_MISSING",
                    },
                }
            ],
        },
        inputs={"brickDigest": "sha256:" + ("a" * 64)},
    )
    with pytest.raises(WorkerSandboxError) as captured:
        _resolve_secret_env(policy.secrets, environ={})
    assert captured.value.code == "oci-secret-forbidden"
    assert "super-secret" not in str(captured.value)
    resolved = _resolve_secret_env(
        policy.secrets,
        environ={"RESEARCHOS_OCI_MISSING": "super-secret-oci-token"},
    )
    assert resolved == {"TOKEN": "super-secret-oci-token"}


def test_host_python_helper_stays_a_trusted_non_oci_path(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    digest = artifacts.put(CPU_CORPUS / "brick.py").digest
    result = execute_python_brick(artifacts, digest)
    assert result.reason_code == "worker.brick.ok"
    assert result.result_digest is not None


def test_execute_local_authorization_cannot_grant_oci_plan(tmp_path: Path) -> None:
    store, _artifacts, _plane, brick = _oci_plane(tmp_path)
    try:
        spec, registry = _oci_plan()
        cpu_spec = load_spec(CPU_CORPUS / "spec.yaml")
        cpu_registry = build_registry([CPU_CORPUS / "block.json"])
        cpu_report = TrustedKernel(cpu_registry).dry_run(cpu_spec, workflow_id="workflow.cpu")
        assert cpu_report.digests.plan is not None
        policy = PlanAuthorizationPolicy(
            spec_digest=cpu_report.digests.spec,
            registry_digest=cpu_report.digests.registry,
            plan_digest=cpu_report.digests.plan,
            granted_capabilities=("execute.local",),
        )
        result = authorize_plan(cpu_report, policy)
        document = snapshot_json_document(
            load_document(CPU_CORPUS / "authorization-event.json", reject_symlinks=True)
        )
        assert type(document) is dict
        document["binding"] = {
            "specDigest": result.spec_digest,
            "registryDigest": result.registry_digest,
            "planDigest": result.plan_digest,
            "decisionDigest": result.decision_digest,
        }
        recorded = record_plan_authorization_event(
            store,
            cpu_report,
            policy,
            validate_plan_authorization_event_request_document(document),
        )
        with pytest.raises(WorkerCallError) as captured:
            require_authorized_execution_binding(
                store,
                spec,
                registry,
                project_id=PROJECT,
                experiment_revision=1,
                planned_task_id="task.oci",
                event_id=recorded.stored.event.id,
                sequence=recorded.stored.event.sequence,
                image_digest=OCI_IMAGE,
                config_digest=_oci_config_digest(brick),
            )
        assert captured.value.code == "authorization-capability-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_grants_record_cli_records_oci_grant_and_rejects_execute_local(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert (
        main(
            [
                "authorizations",
                "record",
                str(OCI_CORPUS / "spec.yaml"),
                str(OCI_CORPUS / "authorization-request.json"),
                str(OCI_CORPUS / "authorization-event.json"),
                str(database),
                "--registry",
                str(OCI_CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workers",
                "register",
                str(OCI_CORPUS / "worker.json"),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )
    registered = json.loads(capsys.readouterr().out)
    assert registered["type"] == "worker.registered"
    assert "rg1." not in json.dumps(registered)
    assert (
        main(
            [
                "grants",
                "record",
                str(OCI_CORPUS / "spec.yaml"),
                str(OCI_CORPUS / "grant.json"),
                str(database),
                "--registry",
                str(OCI_CORPUS / "block.json"),
                "--workflow",
                "workflow.oci",
                "--format",
                "json",
            ]
        )
        == 0
    )
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["type"] == "authorization.grant.recorded"
    assert "rg1." not in json.dumps(recorded)

    cpu_db = tmp_path / "cpu.db"
    with EventStore(cpu_db):
        pass
    assert (
        main(
            [
                "authorizations",
                "record",
                str(CPU_CORPUS / "spec.yaml"),
                str(CPU_CORPUS / "authorization-request.json"),
                str(CPU_CORPUS / "authorization-event.json"),
                str(cpu_db),
                "--registry",
                str(CPU_CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    mixed = json.loads((OCI_CORPUS / "grant.json").read_text(encoding="utf-8"))
    mixed["authorizationEventId"] = "evt.authorization.example-minimal.1"
    mixed["grantId"] = "grant.oci.from-local"
    mixed["nonce"] = "nonce.oci.from-local"
    mixed["event"] = {
        "id": "evt.grant.recorded.oci.from-local",
        "time": "2026-09-07T12:00:00Z",
    }
    mixed_path = tmp_path / "grant-local-on-oci.json"
    mixed_path.write_text(json.dumps(mixed), encoding="utf-8")
    assert (
        main(
            [
                "grants",
                "record",
                str(OCI_CORPUS / "spec.yaml"),
                str(mixed_path),
                str(cpu_db),
                "--registry",
                str(OCI_CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "authorization-capability-mismatch" in err
    assert "rg1." not in err


def test_python_sandbox_worker_cannot_lease_oci_work(tmp_path: Path) -> None:
    store, _artifacts, plane, brick = _oci_plane(tmp_path)
    try:
        plane.register(
            worker_id="worker.loopback.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.python.1",
            time="2026-09-07T12:00:01Z",
            runtime=WORKER_RUNTIME_PYTHON_SANDBOX,
        )
        spec, registry = _oci_plan()
        stored = plane.store.get_event(AUTH_EVENT_ID)
        assert stored is not None
        plane.record_grant(
            grant_id="grant.oci.python-worker",
            worker_id="worker.loopback.1",
            task_id="task.oci",
            run_id="run.worker.oci",
            attempt_id="attempt.worker.oci.1",
            nonce="nonce.oci.python-worker",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.oci.python-worker",
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            image_digest=OCI_IMAGE,
            config_digest=_oci_config_digest(brick),
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.oci",
        )
        plane.enqueue(
            task_id="task.oci",
            run_id="run.worker.oci",
            attempt_id="attempt.worker.oci.1",
            image_digest=OCI_IMAGE,
            event_id="evt.work.queued.task.oci",
            config={"network": "denied"},
            inputs={"brickDigest": brick},
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.oci.python-worker")
        with pytest.raises(WorkerCallError) as captured:
            plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert captured.value.code == "runtime-mismatch"
    finally:
        store.__exit__(None, None, None)


def test_oci_image_get_is_the_cas_brick_not_the_oci_digest(tmp_path: Path) -> None:
    store, artifacts, plane, brick = _oci_plane(tmp_path)
    try:
        spec, registry = _oci_plan()
        stored = plane.store.get_event(AUTH_EVENT_ID)
        assert stored is not None
        plane.record_grant(
            grant_id="grant.oci.1",
            worker_id="worker.oci.1",
            task_id="task.oci",
            run_id="run.worker.oci",
            attempt_id="attempt.worker.oci.1",
            nonce="nonce.oci.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.oci.1",
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            image_digest=OCI_IMAGE,
            config_digest=_oci_config_digest(brick),
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.oci",
        )
        plane.enqueue(
            task_id="task.oci",
            run_id="run.worker.oci",
            attempt_id="attempt.worker.oci.1",
            image_digest=OCI_IMAGE,
            event_id="evt.work.queued.task.oci",
            config={"network": "denied"},
            inputs={"brickDigest": brick},
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token("grant.oci.1")
        with pytest.raises(WorkerCallError) as captured:
            plane.authorize_image_fetch(
                worker_id="worker.oci.1",
                grant_token=token,
                image_digest=OCI_IMAGE,
            )
        assert captured.value.code == "execution-binding-mismatch"
        plane.authorize_image_fetch(
            worker_id="worker.oci.1",
            grant_token=token,
            image_digest=brick,
        )
        artifacts.verify(brick)
    finally:
        store.__exit__(None, None, None)


def test_work_queued_rejects_mixed_runtime_and_media() -> None:
    with pytest.raises(ValidationError, match="runtime does not match imageMediaType"):
        WorkQueuedPayload.model_validate(
            {
                "taskId": "task.oci",
                "imageDigest": OCI_IMAGE,
                "imageMediaType": IMAGE_MEDIA_PYTHON_BRICK,
                "runtime": WORKER_RUNTIME_OCI_CONTAINER,
                "config": {},
                "inputs": {},
                "configDigest": "jcs-sha256:" + ("0" * 64),
            }
        )


def test_oci_prove_fails_closed_without_a_runnable_image(tmp_path: Path) -> None:
    with pytest.raises((M2CheckpointError, WorkerSandboxError)) as captured:
        prove_oci_loop(OCI_CORPUS, tmp_path / "research.db", tmp_path / "artifacts")
    assert captured.value.code in {"oci-runtime-missing", "oci-image-missing"}


def test_oci_prove_rejects_a_swapped_grant_before_the_engine(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(OCI_CORPUS, corpus)
    grant_path = corpus / "grant.json"
    grant = json.loads(grant_path.read_text(encoding="utf-8"))
    grant["imageDigest"] = "sha256:" + ("1" * 64)
    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(M2CheckpointError) as captured:
        prove_oci_loop(corpus, tmp_path / "research.db", tmp_path / "artifacts")
    assert captured.value.code == "execution-binding-mismatch"


def test_oci_prove_rejects_a_python_sandbox_worker_before_the_engine(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(OCI_CORPUS, corpus)
    worker_path = corpus / "worker.json"
    worker = json.loads(worker_path.read_text(encoding="utf-8"))
    worker["runtime"] = WORKER_RUNTIME_PYTHON_SANDBOX
    worker_path.write_text(json.dumps(worker), encoding="utf-8")
    with pytest.raises(M2CheckpointError) as captured:
        prove_oci_loop(corpus, tmp_path / "research.db", tmp_path / "artifacts")
    assert captured.value.code == "runtime-mismatch"


def test_oci_prove_rejects_a_project_mismatch_before_the_engine(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(OCI_CORPUS, corpus)
    grant_path = corpus / "grant.json"
    grant = json.loads(grant_path.read_text(encoding="utf-8"))
    grant["projectId"] = "other-project"
    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(M2CheckpointError) as captured:
        prove_oci_loop(corpus, tmp_path / "research.db", tmp_path / "artifacts")
    assert captured.value.code == "project-mismatch"


def test_m2_oci_cli_fails_closed_without_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_m2(
        argparse.Namespace(
            m2_command="oci",
            corpus=OCI_CORPUS,
            database=tmp_path / "research.db",
            artifacts=tmp_path / "artifacts",
            format="text",
        )
    )
    assert code in {1, 2}
    output = capsys.readouterr().err
    assert "oci-runtime-missing" in output or "oci-image-missing" in output


def test_docker_run_argv_is_digest_pinned_and_closed(tmp_path: Path) -> None:
    brick = "sha256:" + ("a" * 64)
    policy = parse_oci_launch_policy(
        image_digest=OCI_IMAGE,
        config={"network": "denied"},
        inputs={"brickDigest": brick},
    )
    argv = _docker_run_argv(
        "docker",
        image_digest=OCI_IMAGE,
        workspace=tmp_path,
        policy=policy,
        secret_env={"TOKEN": "super-secret-oci-token"},
    )
    joined = " ".join(argv)
    assert argv[:5] == ["docker", "run", "--rm", "-i", "--pull=never"]
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "--privileged" not in argv
    assert "--gpus" not in argv
    assert "dst=/in,readonly" in joined
    assert "/tmp:rw,noexec,nosuid" in joined
    assert "/out:rw,noexec,nosuid" in joined
    assert argv[-5:] == [OCI_IMAGE, "python", "-B", "-I", "/in/task.py"]
    assert "TOKEN=super-secret-oci-token" in argv


def test_image_identities_read_id_and_repo_digests() -> None:
    other = "sha256:" + ("1" * 64)
    identities = _image_identities(
        {
            "Id": OCI_IMAGE,
            "RepoDigests": [f"example/cpu@{other}", "not-a-digest"],
        }
    )
    assert OCI_IMAGE in identities
    assert other in identities


def test_require_pinned_docker_image_matches_local_id(tmp_path: Path) -> None:
    backend = OciBackend(kind="docker", executable=str(_stub_docker(tmp_path, image_id=OCI_IMAGE)))
    require_pinned_docker_image(backend, OCI_IMAGE)
    with pytest.raises(WorkerSandboxError) as captured:
        require_pinned_docker_image(backend, "sha256:" + ("1" * 64))
    assert captured.value.code == "oci-image-mismatch"
    missing = OciBackend(
        kind="docker",
        executable=str(_stub_docker(tmp_path, image_id=OCI_IMAGE, inspect_code=1)),
    )
    with pytest.raises(WorkerSandboxError) as captured:
        require_pinned_docker_image(missing, OCI_IMAGE)
    assert captured.value.code == "oci-image-missing"
    invalid = OciBackend(
        kind="docker",
        executable=str(_stub_docker(tmp_path, image_id=OCI_IMAGE, inspect_body="not-json")),
    )
    with pytest.raises(WorkerSandboxError) as captured:
        require_pinned_docker_image(invalid, OCI_IMAGE)
    assert captured.value.code == "oci-image-missing"


def test_stub_docker_run_is_failed_not_a_mocked_success(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(OCI_CORPUS / "brick.py")
    backend = OciBackend(
        kind="docker",
        executable=str(_stub_docker(tmp_path, image_id=OCI_IMAGE, run_code=2)),
    )
    result = execute_oci_python_brick(
        artifacts,
        OCI_IMAGE,
        config={"network": "denied"},
        inputs={"brickDigest": brick.digest},
        backend=backend,
    )
    assert result.disposition.value != "succeeded"
    assert result.reason_code != "worker.brick.ok"


def test_oci_brick_request_rejects_oversized_json(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(OCI_CORPUS / "brick.py")
    backend = OciBackend(kind="docker", executable=str(_stub_docker(tmp_path, image_id=OCI_IMAGE)))
    with pytest.raises(WorkerSandboxError) as captured:
        execute_oci_python_brick(
            artifacts,
            OCI_IMAGE,
            config={"network": "denied", "pad": "x" * 20_000},
            inputs={"brickDigest": brick.digest},
            backend=backend,
        )
    assert captured.value.code == "brick-request-too-large"


def _stub_docker(
    tmp_path: Path,
    *,
    image_id: str,
    run_code: int = 2,
    inspect_code: int = 0,
    inspect_body: str | None = None,
) -> Path:
    stub = tmp_path / f"docker-stub-{inspect_code}-{run_code}.py"
    printed = "json.dumps({'Id': IMAGE, 'RepoDigests': ['example/cpu@' + IMAGE]})"
    if inspect_body is not None:
        printed = repr(inspect_body)
    stub.write_text(
        "import json\n"
        "import sys\n"
        f"IMAGE = {image_id!r}\n"
        f"RUN_CODE = {run_code}\n"
        f"INSPECT_CODE = {inspect_code}\n"
        "if len(sys.argv) >= 3 and sys.argv[1] == 'image' and sys.argv[2] == 'inspect':\n"
        f"    print({printed})\n"
        "    raise SystemExit(INSPECT_CODE)\n"
        "raise SystemExit(RUN_CODE)\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / f"docker-{stub.stem}"
    wrapper.write_text(
        f'#!/bin/sh\nexec {sys.executable} {stub} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


@pytest.mark.skipif(discover_oci_backend() is None, reason="OCI runtime not installed")
def test_live_oci_python_brick_loop(tmp_path: Path) -> None:
    backend = discover_oci_backend()
    assert backend is not None
    image = _build_local_python_image(backend, tmp_path)
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = artifacts.put(OCI_CORPUS / "brick.py")
    result = execute_oci_python_brick(
        artifacts,
        image,
        config={"network": "denied"},
        inputs={"brickDigest": brick.digest},
        backend=backend,
    )
    assert result.reason_code == "worker.brick.ok"
    assert result.result_digest is not None
    assert b"oci-loop" in result.stdout


def _build_local_python_image(backend: OciBackend, tmp_path: Path) -> str:
    context = tmp_path / "image"
    context.mkdir()
    (context / "Dockerfile").write_text(
        (OCI_CORPUS / "Dockerfile").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    built = subprocess.run(
        [backend.executable, "build", "-q", str(context)],
        check=False,
        capture_output=True,
        timeout=180,
    )
    if built.returncode != 0:
        pytest.skip("OCI image build is unavailable")
    tag = built.stdout.decode("utf-8").strip()
    inspected = subprocess.run(
        [backend.executable, "image", "inspect", "--format", "{{json .}}", tag],
        check=False,
        capture_output=True,
        timeout=10,
    )
    if inspected.returncode != 0:
        pytest.skip("OCI image inspect is unavailable")
    document = json.loads(inspected.stdout.decode("utf-8"))
    image_id = document["Id"]
    assert type(image_id) is str
    return image_id
