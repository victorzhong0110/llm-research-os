"""Real browser-broker dispatch, conservative retries, and confined restore."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_native_reviewed_runtime import TASK, _world
from test_web_commands import _command
from web_helpers import ORIGIN, Client

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationCommand
from llm_research_os.application.native import NativeLaunchProfile, confined
from llm_research_os.application.receipts import ReceiptLog
from llm_research_os.application.service import ApplicationService
from llm_research_os.application.workspace import init_workspace
from llm_research_os.recovery.backup import create_backup
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore


def setup_native(tmp_path: Path, *, task_source: bytes = TASK):  # type: ignore[no-untyped-def]
    world, plane, spec, _registry = _world(tmp_path / "fixture", task_source=task_source)
    world.prepare()
    plane.store.close()
    root = tmp_path / "controller"
    database = root / "control" / "events.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(world.database) as source, sqlite3.connect(database) as target:
        source.backup(target)
    workspace = init_workspace(
        root,
        project_id=world.request.project_id,
        control_db=database,
        cas_root=world.artifacts,
        worker_root=world.workspace,
    )
    (root / "native-profiles").mkdir()
    (root / "request.json").write_text(
        world.request.model_dump_json(by_alias=True, exclude_none=True)
    )
    (root / "spec.json").write_text(spec.model_dump_json(by_alias=True, exclude_none=True))
    shutil.copyfile(tmp_path / "fixture" / "native-block.json", root / "block.json")
    (root / "token").write_text(world.token)
    (root / "key").write_bytes(world.hmac_key)
    profile = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "NativeLaunchProfile",
        "request": "request.json",
        "spec": "spec.json",
        "registry": ["block.json"],
        "preparedRoot": str(world.workspace),
        "stateRoot": str(world.workspace / "launch"),
        "grantTokenFile": "token",
        "hmacKeyFile": "key",
    }
    (root / "native-profiles" / "cpu.json").write_text(json.dumps(profile))
    return workspace, world, profile


def native_command(
    kind: str, identity: str = "browser.start", head: int = 4, digest: str | None = None
) -> ApplicationCommand:
    return ApplicationCommand.model_validate(
        _command(
            command_id=identity,
            operation={"kind": kind, "profileId": "cpu", "materialDigest": digest},
            expected_head=None if kind == "native.observe" else head,
            expected_revision=None if kind == "native.observe" else 1,
        )
    )


def test_real_cpu_browser_start_retry_and_observe(tmp_path: Path) -> None:
    workspace, world, _ = setup_native(tmp_path)
    service = ApplicationService(workspace)
    with EventStore(workspace.control_db) as store:
        head = store.last_sequence()
    from llm_research_os.application.native import freeze_native

    digest = freeze_native(workspace, "cpu").digest
    inspect = ApplicationCommand.model_validate(
        _command(
            command_id="browser.inspect", operation={"kind": "native.inspect", "profileId": "cpu"}
        )
    )
    preview = service.execute(inspect)
    assert preview["result"]["materialDigest"] == digest
    assert preview["result"]["launchAllowed"] is False
    command = native_command("native.start", head=head, digest=digest)
    api = LocalApi(
        workspace,
        sessions=SessionStore(bootstrap_token="native-test"),
        allowed_hosts=frozenset({"127.0.0.1:8787"}),
        allowed_origin=ORIGIN,
    )
    client = Client(api)
    client.bootstrap("native-test")
    status, _, result = client.request(
        "POST",
        "/api/v0alpha1/commands",
        body=command.model_dump_json(by_alias=True).encode(),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 200, result
    assert result["result"]["observation"] == "completed"
    assert "hmac" not in json.dumps(result).lower()
    assert world.token not in json.dumps(result)
    replay = service.execute(command)
    assert replay["disposition"] == "replayed"
    observed = service.execute(native_command("native.observe", "browser.observe"))
    assert observed["result"]["observation"] == "completed"
    with EventStore(workspace.control_db) as store:
        new_head = store.last_sequence()
    duplicate = service.execute(native_command("native.start", "other-window", new_head, digest))
    assert duplicate["result"]["observation"] == "unknown"
    with EventStore(workspace.control_db) as store:
        assert store.last_sequence() == new_head


def test_stale_and_restore_prerequisites_do_not_launch(tmp_path: Path) -> None:
    workspace, world, _ = setup_native(tmp_path)
    service = ApplicationService(workspace)
    from llm_research_os.application.native import freeze_native

    digest = freeze_native(workspace, "cpu").digest
    with pytest.raises(ApplicationError, match="expectedHead"):
        service.execute(native_command("native.start", head=0, digest=digest))
    with pytest.raises(ApplicationError, match="matching start or restore"):
        service.execute(native_command("native.restore", digest=digest))
    assert not (world.workspace / "launch").exists()


def test_reserved_dispatch_after_crash_never_relaunches(tmp_path: Path) -> None:
    workspace, world, _ = setup_native(tmp_path)
    from llm_research_os.application.native import freeze_native

    context = freeze_native(workspace, "cpu")
    ReceiptLog(workspace.receipt_db).reserve_effect(
        f"native:{world.request.project_id}:{world.request.run_id}", context.digest
    )
    result = ApplicationService(workspace).execute(
        native_command("native.start", digest=context.digest)
    )
    assert result["result"]["reasonCode"] == "dispatch-already-reserved"
    assert not (world.workspace / "launch").exists()


def test_backup_browser_restore_and_duplicate(tmp_path: Path) -> None:
    workspace, _, _ = setup_native(tmp_path)
    image = workspace.root / "backups" / "image1"
    create_backup(workspace, image, now=datetime.now(UTC))
    service = ApplicationService(workspace)
    verify = ApplicationCommand.model_validate(
        _command(
            command_id="backup.verify", operation={"kind": "backup.verify", "imageId": "image1"}
        )
    )
    assert service.execute(verify)["result"]["verified"] is True
    restore = ApplicationCommand.model_validate(
        _command(
            command_id="backup.restore",
            expected_head=4,
            operation={"kind": "backup.restore", "imageId": "image1", "destinationId": "copy1"},
        )
    )
    receipt = service.execute(restore)
    assert receipt["result"]["appendedEvents"] == 0
    assert receipt["result"]["relaunchPolicy"] == "not-relaunched"
    assert (workspace.root / "restored" / "copy1" / "workspace.json").is_file()
    assert service.execute(restore)["disposition"] == "replayed"


def test_profile_and_output_paths_reject_escape(tmp_path: Path) -> None:
    workspace, _, profile = setup_native(tmp_path)
    profile["restoreClaim"] = "claim.json"
    with pytest.raises(ValueError, match="restore requires"):
        NativeLaunchProfile.model_validate(profile)
    for path in (Path("../outside"), tmp_path / "outside"):
        with pytest.raises(ApplicationError, match="inside its root"):
            confined(workspace.root, path, exists=False)
    (workspace.root / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ApplicationError, match="inside its root"):
        confined(workspace.root, Path("link/future"), exists=False)


def test_material_change_is_refused_and_intents_cannot_be_rebound(tmp_path: Path) -> None:
    workspace, _, _ = setup_native(tmp_path)
    from llm_research_os.application.native import freeze_native

    digest = freeze_native(workspace, "cpu").digest
    path = workspace.root / "native-profiles/cpu.json"
    document = json.loads(path.read_text())
    document["stateRoot"] += "-changed"
    path.write_text(json.dumps(document))
    with pytest.raises(ApplicationError, match="inspect the current"):
        ApplicationService(workspace).execute(native_command("native.start", digest=digest))
    log = ReceiptLog(workspace.receipt_db)
    assert log.reserve_effect("intent", "a")
    assert not log.reserve_effect("intent", "a")
    with pytest.raises(ApplicationError, match="other material"):
        log.reserve_effect("intent", "b")


def test_real_checkpoint_restore_uses_new_authority(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_native_reviewed_preparation import EXPIRES, _authorization_event

    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.blocks.registry import build_registry
    from llm_research_os.canonical import content_digest
    from llm_research_os.execution import TrustedKernel, authorize_plan
    from llm_research_os.execution.authorization import PlanAuthorizationPolicy
    from llm_research_os.execution.native_reviewed import execution_object
    from llm_research_os.spec.models import ResearchSpec
    from llm_research_os.workers.plane import WorkerPlane

    task = b"""from pathlib import Path
import json
def main():
    prior = Path('material/inputs/prior')
    state = json.loads(prior.read_text())['output']['state'] if prior.exists() else {
        'model': 1, 'optimizer': 2, 'scheduler': 3, 'rng': 4}
    return {'restoreMode':'full-state', 'state':state, 'restored':prior.exists()}
"""
    workspace, world, profile = setup_native(tmp_path, task_source=task)
    service = ApplicationService(workspace)
    from llm_research_os.application.native import freeze_native

    source = world.request
    digest = freeze_native(workspace, "cpu").digest
    source_receipt = service.execute(native_command("native.start", digest=digest))
    source_artifact = source_receipt["result"]["artifactDigest"]
    artifacts = LocalArtifactStore(workspace.cas_root)
    record = artifacts.verify(source_artifact)
    target = source.model_copy(
        update={
            "run_id": "run.restore",
            "attempt_id": "attempt.restore",
            "authorization_event_id": "evt.auth.restore",
            "inputs": (
                source.inputs[0].model_copy(
                    update={
                        "name": "prior",
                        "purpose": "checkpoint",
                        "digest": source_artifact,
                        "size_bytes": record.size_bytes,
                    }
                ),
            ),
        }
    )
    target = target.model_copy(update={"config_digest": content_digest(execution_object(target))})
    spec_doc = json.loads((workspace.root / "spec.json").read_text())
    spec_doc["workflows"][0]["graph"]["nodes"][0]["config"]["config"] = execution_object(target)
    spec = ResearchSpec.model_validate(spec_doc)
    registry = build_registry([workspace.root / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id=target.workflow_id)
    assert report.digests.plan is not None
    decision = authorize_plan(
        report,
        PlanAuthorizationPolicy(
            spec_digest=report.digests.spec,
            registry_digest=report.digests.registry,
            plan_digest=report.digests.plan,
            granted_capabilities=("execute.native",),
        ),
    )
    with EventStore(workspace.control_db) as store:
        target = target.model_copy(
            update={
                "spec_digest": report.digests.spec,
                "registry_digest": report.digests.registry,
                "plan_digest": report.digests.plan,
                "decision_digest": decision.decision_digest,
                "authorization_sequence": str(store.last_sequence() + 1),
            }
        )
        auth = _authorization_event(
            target.spec_digest, target.registry_digest, target.plan_digest, "execute.native"
        )
        auth["id"] = target.authorization_event_id
        store.append(auth)
        plane = WorkerPlane(
            store=store,
            artifacts=artifacts,
            hmac_key=world.hmac_key,
            project_id=target.project_id,
            source=f"https://researchos.dev/projects/{target.project_id}",
        )
        plane.enqueue(
            task_id=target.task_id,
            run_id=target.run_id,
            attempt_id=target.attempt_id,
            image_digest=target.code.bundle_digest,
            config=execution_object(target),
            inputs={},
            event_id="evt.work.restore",
            image_media_type=target.code.media_type,
            runtime="native-reviewed-process",
        )
        plane.record_grant(
            grant_id="grant.restore",
            worker_id=target.worker_id,
            task_id=target.task_id,
            run_id=target.run_id,
            attempt_id=target.attempt_id,
            nonce="nonce.restore",
            expires_at=EXPIRES,
            actor_id=target.actor_id,
            event_id="evt.grant.restore",
            authorization_event_id=target.authorization_event_id,
            authorization_sequence=target.authorization_sequence,
            image_digest=target.code.bundle_digest,
            config_digest=target.config_digest,
            spec=spec,
            registry=registry,
        )
        token = plane.issue_token("grant.restore")
    target_root = workspace.worker_root / "target"
    target_world = replace(
        world, database=workspace.control_db, request=target, workspace=target_root, token=token
    )
    target_world.prepare()
    (workspace.root / "target-request.json").write_text(
        target.model_dump_json(by_alias=True, exclude_none=True)
    )
    (workspace.root / "target-spec.json").write_text(
        spec.model_dump_json(by_alias=True, exclude_none=True)
    )
    (workspace.root / "target-token").write_text(token)
    (workspace.root / "restore-claim.json").write_text(
        json.dumps(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "NativeRestoreClaim",
                "mode": "full-state",
                "sourceRunId": source.run_id,
                "sourceAttemptId": source.attempt_id,
                "targetRunId": target.run_id,
                "targetAttemptId": target.attempt_id,
                "checkpointInput": "prior",
                "artifactDigest": source_artifact,
            }
        )
    )
    profile.update(
        request="target-request.json",
        spec="target-spec.json",
        preparedRoot=str(target_root),
        stateRoot=str(workspace.worker_root / "restore-launch"),
        grantTokenFile="target-token",
        restoreClaim="restore-claim.json",
        sourceRequest="request.json",
    )
    (workspace.root / "native-profiles/restore.json").write_text(json.dumps(profile))
    context = freeze_native(workspace, "restore")
    with EventStore(workspace.control_db) as store:
        head = store.last_sequence()
    command = ApplicationCommand.model_validate(
        _command(
            command_id="browser.restore",
            expected_head=head,
            expected_revision=1,
            operation={
                "kind": "native.restore",
                "profileId": "restore",
                "materialDigest": context.digest,
            },
        )
    )
    result = service.execute(command)
    assert result["result"]["observation"] == "completed"
    with artifacts.open(result["result"]["artifactDigest"]) as stream:
        output = json.load(stream)["output"]
    assert output["restored"] is True
    assert output["state"] == {"model": 1, "optimizer": 2, "scheduler": 3, "rng": 4}
