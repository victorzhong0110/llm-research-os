"""Real CPU execution, Worker consumption, and duplicate/tamper refusal."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_native_reviewed_preparation import (
    EXPIRES,
    NOW,
    PROJECT,
    SOURCE,
    _authorization_event,
    _build,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.cli.native_commands import run_native
from llm_research_os.cli.parser import build_parser
from llm_research_os.execution import TrustedKernel, authorize_plan
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.execution.native_reviewed import execution_object
from llm_research_os.execution.native_reviewed_runtime import (
    NativeLaunchError,
    execute_reviewed_native,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.spec.io import load_spec
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.workers.models import (
    IMAGE_MEDIA_NATIVE_REVIEWED,
    WORKER_RUNTIME_NATIVE_REVIEWED,
)
from llm_research_os.workers.plane import WorkerPlane

ROOT = Path(__file__).parents[1]
TASK = b"""from pathlib import Path
import hashlib
def main():
    data = Path('material/inputs/corpus').read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'rows': 1}
"""


def _world(tmp_path: Path, *, task_source: bytes = TASK):  # type: ignore[no-untyped-def]
    base = _build(tmp_path, brick=task_source)
    block = json.loads((ROOT / "examples/m2-checkpoint/block.json").read_text())
    block["metadata"]["id"] = "researchos.native-reviewed"
    block["runtime"]["entrypoint"] = "researchos.native-reviewed"
    block["capabilities"] = ["execute.native"]
    block["configSchema"]["properties"]["config"]["additionalProperties"] = True
    block["configSchema"]["properties"]["imageMediaType"]["const"] = IMAGE_MEDIA_NATIVE_REVIEWED
    block["configSchema"]["properties"]["runtime"]["const"] = WORKER_RUNTIME_NATIVE_REVIEWED
    block_path = tmp_path / "native-block.json"
    block_path.write_text(json.dumps(block))
    registry = build_registry([block_path])
    spec_document = load_spec(ROOT / "examples/m2-checkpoint/spec.yaml").model_dump(
        mode="json",
        by_alias=True,
    )
    spec_document["metadata"]["id"] = PROJECT
    spec_document["workflows"][0]["id"] = "workflow.reviewed"
    task = spec_document["workflows"][0]["graph"]["nodes"][0]
    task["id"] = "task.brick"
    task["blockType"] = "researchos.native-reviewed"
    task["config"] = {
        "config": execution_object(base.request),
        "imageDigest": base.request.code.bundle_digest,
        "imageMediaType": IMAGE_MEDIA_NATIVE_REVIEWED,
        "inputs": {},
        "runtime": WORKER_RUNTIME_NATIVE_REVIEWED,
    }
    spec = ResearchSpec.model_validate(spec_document)
    report = TrustedKernel(registry).dry_run(spec, workflow_id="workflow.reviewed")
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.native",),
    )
    decision = authorize_plan(report, policy)
    request = base.request.model_copy(
        update={
            "spec_digest": report.digests.spec,
            "registry_digest": report.digests.registry,
            "plan_digest": report.digests.plan,
            "decision_digest": decision.decision_digest,
        }
    )
    database = tmp_path / "actual.sqlite"
    store = EventStore(database)
    store.append(
        _authorization_event(
            request.spec_digest,
            request.registry_digest,
            request.plan_digest,
            "execute.native",
        )
    )
    plane = WorkerPlane(
        store=store,
        artifacts=LocalArtifactStore(base.artifacts),
        hmac_key=base.hmac_key,
        project_id=PROJECT,
        source=SOURCE,
        clock=lambda: NOW,
    )
    plane.register(
        worker_id=request.worker_id,
        actor_id=request.actor_id,
        event_id="evt.worker.native",
        runtime=WORKER_RUNTIME_NATIVE_REVIEWED,
    )
    plane.enqueue(
        task_id=request.task_id,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
        image_digest=request.code.bundle_digest,
        config=execution_object(request),
        inputs={},
        event_id="evt.work.native",
        image_media_type=IMAGE_MEDIA_NATIVE_REVIEWED,
        runtime=WORKER_RUNTIME_NATIVE_REVIEWED,
    )
    plane.record_grant(
        grant_id="grant.native",
        worker_id=request.worker_id,
        task_id=request.task_id,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
        nonce="nonce.native",
        expires_at=EXPIRES,
        actor_id=request.actor_id,
        event_id="evt.grant.native",
        authorization_event_id="evt.auth.1",
        authorization_sequence="1",
        image_digest=request.code.bundle_digest,
        config_digest=request.config_digest,
        spec=spec,
        registry=registry,
    )
    token = plane.issue_token("grant.native")
    return replace(base, database=database, request=request, token=token), plane, spec, registry


def test_real_cpu_task_and_duplicate_refusal(tmp_path: Path) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    kwargs = dict(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "launch",
        grant_token=world.token,
    )
    result = execute_reviewed_native(**kwargs)
    assert result.output == {
        "rows": 1,
        "sha256": "815853a11c4f2e2e5355f547308cd7c6054f85ba6a324b2c37beb8edbec1fb93",
    }
    plane.artifacts.verify(result.artifact_digest)
    assert plane.rebuild().grant("grant.native").consumed_lease_id == result.lease_id
    assert plane.store.get_event(f"evt.work.completed.{result.lease_id}") is not None
    with pytest.raises(NativeLaunchError):
        execute_reviewed_native(**kwargs)


def test_tampered_prepared_code_does_not_consume_grant(tmp_path: Path) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    (world.workspace / "material/code/brick/task.py").write_text("raise Exception()")
    with pytest.raises(NativeLaunchError, match="not ready"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_revocation_and_expiry_refuse_before_claim(tmp_path: Path) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    plane.revoke_grant(
        grant_id="grant.native", actor_id="researcher.local", event_id="evt.revoked.native"
    )
    kwargs = dict(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "launch",
        grant_token=world.token,
    )
    with pytest.raises(Exception, match="revoked"):
        execute_reviewed_native(**kwargs)
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_expired_grant_refuses_before_claim(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    plane.clock = lambda: datetime(2028, 1, 1, tzinfo=UTC)
    with pytest.raises(NativeLaunchError, match="not ready"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_substitution_at_child_barrier_never_imports_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    task = b"from pathlib import Path\ndef main():\n Path('ran').write_text('yes')\n return 1\n"
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    original = runtime._sync_identity

    def substitute(identity_dir: Path, lease_id: str) -> None:
        original(identity_dir, lease_id)
        (world.workspace / "material/code/brick/task.py").write_text("raise ValueError()")

    monkeypatch.setattr(runtime, "_sync_identity", substitute)
    with pytest.raises(NativeLaunchError, match="status 70"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert not (world.workspace / "ran").exists()
    snapshot = RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    assert snapshot is not None and snapshot.status.value == "failed"


def test_descendant_cannot_outlive_recorded_success(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-ran"
    task = (
        "import os, time\nfrom pathlib import Path\n"
        "def main():\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        os.close(0); os.close(1); os.close(2)\n"
        "        time.sleep(0.8)\n"
        f"        Path({str(marker)!r}).write_text('ran')\n"
        "        os._exit(0)\n"
        "    return {'child': pid}\n"
    ).encode()
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    with pytest.raises(NativeLaunchError, match="process group"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    import time

    time.sleep(1)
    assert not marker.exists()
    snapshot = RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    assert snapshot is not None and snapshot.status.value == "unknown"


def test_timeout_kills_descendant_after_leader_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    from types import SimpleNamespace

    import llm_research_os.execution.native_reviewed_runtime as runtime

    marker = tmp_path / "survived-timeout"
    task = (
        "import os, time\nfrom pathlib import Path\n"
        "def main():\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        time.sleep(0.8)\n"
        f"        Path({str(marker)!r}).write_text('ran')\n"
        "        os._exit(0)\n"
        "    return {'child': pid}\n"
    ).encode()
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    original = runtime._collect

    def short_collect(process: object, request: object) -> object:
        limits = world.request.limits.model_copy(update={"wall_time_seconds": 0.2})
        return original(process, SimpleNamespace(limits=limits))  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "_collect", short_collect)
    with pytest.raises(NativeLaunchError, match="wall-clock limit"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    time.sleep(1)
    assert not marker.exists()


def test_child_waits_for_durable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    task = b"from pathlib import Path\ndef main():\n Path('ran').write_text('yes')\n return 1\n"
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()

    def fail_identity(*_args: object) -> None:
        raise OSError("identity persistence failed")

    monkeypatch.setattr(runtime, "save_execution_identity", fail_identity)
    kwargs = dict(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "launch",
        grant_token=world.token,
    )
    with pytest.raises(OSError, match="identity persistence failed"):
        execute_reviewed_native(**kwargs)
    assert not (world.workspace / "ran").exists()
    assert plane.rebuild().grant("grant.native").consumed_lease_id is not None
    snapshot = (
        runtime.RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    )
    assert snapshot is not None and snapshot.status.value == "unknown"
    with pytest.raises(NativeLaunchError, match="not ready"):
        execute_reviewed_native(**kwargs)


def test_task_failure_records_terminal_facts(tmp_path: Path) -> None:
    task = b"def main():\n raise ValueError('intentional')\n"
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    with pytest.raises(NativeLaunchError, match="status 1"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    snapshot = RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    assert snapshot is not None and snapshot.status.value == "failed"
    assert plane.store.get_event("evt.work.failed.lease.grant.native") is not None


def test_cli_executes_prepared_reviewed_task(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world, _plane, spec, _registry = _world(tmp_path)
    world.prepare()
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(world.request.model_dump(mode="json", by_alias=True, exclude_none=True))
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec.model_dump(mode="json", by_alias=True)))
    token_path = tmp_path / "token"
    token_path.write_text(world.token)
    key_path = tmp_path / "key"
    key_path.write_bytes(world.hmac_key)
    args = build_parser().parse_args(
        [
            "native",
            "execute-reviewed",
            str(request_path),
            str(world.database),
            str(world.artifacts),
            str(world.workspace),
            "--grant-token-file",
            str(token_path),
            "--hmac-key-file",
            str(key_path),
            "--spec",
            str(spec_path),
            "--registry",
            str(tmp_path / "native-block.json"),
            "--state-dir",
            str(tmp_path / "launch"),
            "--format",
            "json",
        ]
    )
    assert run_native(args) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["output"]["rows"] == 1
    assert response["artifactDigest"].startswith("sha256:")


def test_existing_launch_intent_refuses_unclaimed_attempt(tmp_path: Path) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    state = tmp_path / "launch"
    runtime._write_intent(state, world.request)
    with pytest.raises(NativeLaunchError, match="intent already exists"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=state,
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_receipt_changed_after_preflight_refuses_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    original = runtime.check_before_user_code

    def change_receipt(**kwargs: object):  # type: ignore[no-untyped-def]
        diagnosis = original(**kwargs)  # type: ignore[arg-type]
        receipt = world.workspace / "receipt.json"
        document = json.loads(receipt.read_text())
        document["files"][0]["digest"] = "sha256:" + "0" * 64
        receipt.write_text(json.dumps(document))
        return diagnosis

    monkeypatch.setattr(runtime, "check_before_user_code", change_receipt)
    with pytest.raises(NativeLaunchError, match="receipt changed"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_bounded_stdout_marks_unknown_without_redispatch(tmp_path: Path) -> None:
    task = b"def main():\n print('x' * 5000)\n return 1\n"
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    kwargs = dict(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "launch",
        grant_token=world.token,
    )
    with pytest.raises(NativeLaunchError, match="bound exceeded"):
        execute_reviewed_native(**kwargs)
    snapshot = RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    assert snapshot is not None and snapshot.status.value == "unknown"
    with pytest.raises(NativeLaunchError, match="not ready"):
        execute_reviewed_native(**kwargs)


def test_intent_state_symlink_refused(tmp_path: Path) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    target = tmp_path / "real-state"
    target.mkdir()
    alias = tmp_path / "launch"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(NativeLaunchError, match="symlink"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=alias,
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_started_fact_fault_after_consumption_becomes_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    original = runtime._lifecycle
    failures = 0

    def fail_once(*args: object, **kwargs: object) -> None:
        nonlocal failures
        if len(args) >= 3 and args[2] == "attempt.started" and failures == 0:
            failures += 1
            raise OSError("start fact unavailable")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "_lifecycle", fail_once)
    with pytest.raises(OSError, match="start fact unavailable"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    snapshot = RunControl(plane.store, project_id=PROJECT, run_id="run.1").rebuild().snapshot
    assert snapshot is not None and snapshot.status.value == "unknown"
    assert plane.rebuild().grant("grant.native").consumed_lease_id is not None


def test_code_substitution_between_preflight_and_manifest_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_research_os.execution.native_reviewed_runtime as runtime

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    original = runtime.check_before_user_code

    def substitute(**kwargs: object):  # type: ignore[no-untyped-def]
        diagnosis = original(**kwargs)  # type: ignore[arg-type]
        (world.workspace / "material/code/brick/task.py").write_text("raise ValueError()")
        return diagnosis

    monkeypatch.setattr(runtime, "check_before_user_code", substitute)
    with pytest.raises(NativeLaunchError, match="prepared file changed"):
        execute_reviewed_native(
            request=world.request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None
