"""Live reviewed Attempt stop and conservative restart reconciliation."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from test_native_reviewed_runtime import _world

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.execution.native_reviewed_recovery import reconcile_reviewed_native
from llm_research_os.execution.native_reviewed_runtime import (
    NativeLaunchError,
    _lifecycle,
    execute_reviewed_native,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.storage import EventStore
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.supervise import (
    OBSERVATION_EXITED,
    load_execution_identity,
    observe_process_group,
    posix_start_token,
)


def _execute(world, plane, spec, registry, state):  # type: ignore[no-untyped-def]
    return execute_reviewed_native(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=state,
        grant_token=world.token,
    )


def test_cancel_and_reconcile_after_controller_restart(tmp_path: Path) -> None:
    if posix_start_token(os.getpid()) is None:
        pytest.skip("host hides process start identity; CI runners exercise the live stop")
    task = (
        b"from pathlib import Path\nimport time\ndef main():\n"
        b" Path('started').write_text('yes')\n time.sleep(30)\n return {'done': True}\n"
    )
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    state = tmp_path / "launch"
    outcome: list[Exception] = []

    def run() -> None:
        try:
            thread_plane = WorkerPlane(
                store=EventStore(world.database),
                artifacts=LocalArtifactStore(world.artifacts),
                hmac_key=world.hmac_key,
                project_id=world.request.project_id,
                source=plane.source,
                clock=plane.clock,
            )
            _execute(world, thread_plane, spec, registry, state)
        except Exception as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not (world.workspace / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (world.workspace / "started").exists(), outcome
        _lifecycle(
            RunControl(
                plane.store, project_id=world.request.project_id, run_id=world.request.run_id
            ),
            world.request,
            "run.cancel.requested",
            {"reasonCode": "user-requested"},
        )
        restarted = WorkerPlane(
            store=EventStore(world.database),
            artifacts=LocalArtifactStore(world.artifacts),
            hmac_key=world.hmac_key,
            project_id=world.request.project_id,
            source=plane.source,
            clock=plane.clock,
        )
        result = reconcile_reviewed_native(
            request=world.request, plane=restarted, state_dir=state, grant_token=world.token
        )
        assert result.disposition == "cancelled"
        identity = load_execution_identity(state / "identities", result.lease_id or "")
        assert identity is not None
        assert observe_process_group(identity.pgid, identity.pid) == OBSERVATION_EXITED
        assert restarted.rebuild().lease(result.lease_id or "").reason_code == "cancel-observed"
        again = reconcile_reviewed_native(
            request=world.request, plane=restarted, state_dir=state, grant_token=world.token
        )
        assert again.disposition == "cancelled"
    finally:
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], NativeLaunchError)


def test_missing_identity_after_consumption_stays_unknown(tmp_path: Path) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    state = tmp_path / "launch"
    from llm_research_os.execution import native_reviewed_runtime as runtime

    runtime._write_intent(state, world.request)
    _lifecycle(
        RunControl(plane.store, project_id=world.request.project_id, run_id=world.request.run_id),
        world.request,
        "run.queued",
        {
            "workflowId": world.request.workflow_id,
            "specDigest": world.request.spec_digest,
            "registryDigest": world.request.registry_digest,
            "planDigest": world.request.plan_digest,
            "decisionDigest": world.request.decision_digest,
            "authorizationEventId": world.request.authorization_event_id,
            "authorizationSequence": world.request.authorization_sequence,
            "maxAttempts": 1,
        },
    )
    run = RunControl(plane.store, project_id=world.request.project_id, run_id=world.request.run_id)
    _lifecycle(run, world.request, "run.started", {})
    _lifecycle(
        run,
        world.request,
        "attempt.queued",
        {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
        attempt=True,
    )
    assert plane.poll(worker_id=world.request.worker_id, grant_token=world.token) is not None
    observed = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert observed.disposition == "unknown"
    assert plane.store.get_event("evt.work.failed.lease.grant.native") is None
    with pytest.raises(NativeLaunchError, match=r"Run already exists|not ready"):
        _execute(world, plane, spec, registry, state)
    assert json.loads(next(state.glob("*.intent")).read_text())["runId"] == world.request.run_id


def test_reused_process_identity_never_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import llm_research_os.execution.native_reviewed_recovery as recovery
    from llm_research_os.workers.supervise import ExecutionIdentity

    world, plane, _spec, _registry = _world(tmp_path)
    state = tmp_path / "launch"
    from llm_research_os.execution.native_reviewed_runtime import _write_intent

    _write_intent(state, world.request)
    run = RunControl(plane.store, project_id=world.request.project_id, run_id=world.request.run_id)
    _lifecycle(
        run,
        world.request,
        "run.queued",
        {
            "workflowId": world.request.workflow_id,
            "specDigest": world.request.spec_digest,
            "registryDigest": world.request.registry_digest,
            "planDigest": world.request.plan_digest,
            "decisionDigest": world.request.decision_digest,
            "authorizationEventId": world.request.authorization_event_id,
            "authorizationSequence": world.request.authorization_sequence,
            "maxAttempts": 1,
        },
    )
    _lifecycle(run, world.request, "run.started", {})
    _lifecycle(
        run,
        world.request,
        "attempt.queued",
        {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
        attempt=True,
    )
    assert plane.poll(worker_id=world.request.worker_id, grant_token=world.token) is not None
    _lifecycle(run, world.request, "attempt.started", {}, attempt=True)
    identity = ExecutionIdentity(
        lease_id="lease.grant.native",
        kind="posix-pg",
        pid=54321,
        pgid=54321,
        start_token="original",
        container_id=None,
        docker_executable=None,
    )
    monkeypatch.setattr(recovery, "load_execution_identity", lambda *_: identity)
    monkeypatch.setattr(recovery, "posix_start_token", lambda *_: "original")
    monkeypatch.setattr(recovery, "observe_process_group", lambda *_: "running")
    monkeypatch.setattr(recovery, "observe_process", lambda *_: "running")
    monkeypatch.setattr(
        recovery, "observe_and_stop", lambda *_: pytest.fail("must not signal reused PID")
    )
    assert (
        reconcile_reviewed_native(
            request=world.request, plane=plane, state_dir=state, grant_token=world.token
        ).disposition
        == "running"
    )
    _lifecycle(run, world.request, "run.cancel.requested", {"reasonCode": "user-requested"})
    monkeypatch.setattr(recovery, "posix_start_token", lambda *_: "reused")
    result = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert result.disposition == "unknown"
    assert plane.store.get_event("evt.work.failed.lease.grant.native") is None


def test_restart_requires_untampered_durable_intent(tmp_path: Path) -> None:
    from llm_research_os.execution.native_reviewed_runtime import _write_intent

    world, plane, _spec, _registry = _world(tmp_path)
    state = tmp_path / "launch"
    with pytest.raises(NativeLaunchError, match="durable launch intent"):
        reconcile_reviewed_native(
            request=world.request, plane=plane, state_dir=state, grant_token=world.token
        )
    _write_intent(state, world.request)
    intent = next(state.glob("*.intent"))
    intent.unlink()
    intent.symlink_to(tmp_path / "outside")
    with pytest.raises(NativeLaunchError, match="symlink"):
        reconcile_reviewed_native(
            request=world.request, plane=plane, state_dir=state, grant_token=world.token
        )


def test_reconcile_cli_reports_uncertain_intent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from llm_research_os.cli.native_commands import run_native
    from llm_research_os.cli.parser import build_parser
    from llm_research_os.execution.native_reviewed_runtime import _write_intent

    world, _plane, _spec, _registry = _world(tmp_path)
    state = tmp_path / "launch"
    _write_intent(state, world.request)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(world.request.model_dump(mode="json", by_alias=True, exclude_none=True))
    )
    key_path = tmp_path / "key"
    key_path.write_bytes(world.hmac_key)
    token_path = tmp_path / "token"
    token_path.write_text(world.token)
    args = build_parser().parse_args(
        [
            "native",
            "reconcile-reviewed",
            str(request_path),
            str(world.database),
            str(world.artifacts),
            str(world.workspace),
            "--grant-token-file",
            str(token_path),
            "--hmac-key-file",
            str(key_path),
            "--state-dir",
            str(state),
            "--format",
            "json",
        ]
    )
    assert run_native(args) == 1
    assert json.loads(capsys.readouterr().out)["disposition"] == "unknown"


def test_completed_attempt_rebuilds_without_rerunning_and_rejects_tampered_intent(
    tmp_path: Path,
) -> None:
    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    state = tmp_path / "launch"
    result = _execute(world, plane, spec, registry, state)
    observation = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert observation.disposition == "completed"
    assert observation.lease_id == result.lease_id
    intent = next(state.glob("*.intent"))
    document = json.loads(intent.read_text())
    document["requestDigest"] = "jcs-sha256:" + "0" * 64
    intent.write_text(json.dumps(document))
    with pytest.raises(NativeLaunchError, match="does not bind"):
        reconcile_reviewed_native(
            request=world.request, plane=plane, state_dir=state, grant_token=world.token
        )


def test_checkpoint_input_without_restore_evidence_refuses_before_claim(tmp_path: Path) -> None:
    from llm_research_os.canonical import content_digest
    from llm_research_os.execution.native_reviewed import execution_object

    world, plane, spec, registry = _world(tmp_path)
    world.prepare()
    request = world.request.model_copy(
        update={"inputs": (world.request.inputs[0].model_copy(update={"purpose": "checkpoint"}),)}
    )
    request = request.model_copy(
        update={"config_digest": content_digest(execution_object(request))}
    )
    with pytest.raises(NativeLaunchError, match="checkpoint restore requires"):
        execute_reviewed_native(
            request=request,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "launch",
            grant_token=world.token,
        )
    assert plane.rebuild().grant("grant.native").consumed_lease_id is None


def test_post_claim_revocation_and_expiry_settle_only_after_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    import llm_research_os.execution.native_reviewed_recovery as recovery
    from llm_research_os.execution.native_reviewed_runtime import _write_intent
    from llm_research_os.storage.errors import DuplicateEventError
    from llm_research_os.workers.supervise import ExecutionIdentity

    world, plane, _spec, _registry = _world(tmp_path)
    state = tmp_path / "launch"
    _write_intent(state, world.request)
    run = RunControl(plane.store, project_id=world.request.project_id, run_id=world.request.run_id)
    _lifecycle(
        run,
        world.request,
        "run.queued",
        {
            "workflowId": world.request.workflow_id,
            "specDigest": world.request.spec_digest,
            "registryDigest": world.request.registry_digest,
            "planDigest": world.request.plan_digest,
            "decisionDigest": world.request.decision_digest,
            "authorizationEventId": world.request.authorization_event_id,
            "authorizationSequence": world.request.authorization_sequence,
            "maxAttempts": 1,
        },
    )
    _lifecycle(run, world.request, "run.started", {})
    _lifecycle(
        run,
        world.request,
        "attempt.queued",
        {"ordinal": 1, "retryOf": None, "retryDecisionId": None},
        attempt=True,
    )
    assert plane.poll(worker_id=world.request.worker_id, grant_token=world.token) is not None
    _lifecycle(run, world.request, "attempt.started", {}, attempt=True)
    plane.revoke_grant(
        grant_id="grant.native",
        actor_id=world.request.actor_id,
        event_id="evt.grant.revoked.native",
    )
    plane.clock = lambda: datetime(2028, 1, 1, tzinfo=UTC)
    first = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert first.disposition == "unknown"
    assert plane.store.get_event("evt.native.run.1.attempt.1.run.cancel.requested") is not None
    assert plane.store.get_event("evt.work.failed.lease.grant.native") is None
    identity = ExecutionIdentity(
        lease_id="lease.grant.native",
        kind="posix-pg",
        pid=54321,
        pgid=54321,
        start_token="old",
        container_id=None,
        docker_executable=None,
    )
    monkeypatch.setattr(recovery, "load_execution_identity", lambda *_: identity)
    monkeypatch.setattr(recovery, "posix_start_token", lambda *_: None)
    monkeypatch.setattr(recovery, "observe_process_group", lambda *_: "exited")
    original_append = plane._control.append
    raced = False

    def append_after_competing_reconciler(draft):  # type: ignore[no-untyped-def]
        nonlocal raced
        if draft["type"] == "work.failed" and not raced:
            raced = True
            original_append(draft)
            raise DuplicateEventError("another reconciler recorded the observed stop")
        return original_append(draft)

    monkeypatch.setattr(plane._control, "append", append_after_competing_reconciler)
    observed = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert observed.disposition == "cancelled"
    assert raced
    assert plane.rebuild().lease(observed.lease_id or "").reason_code == "cancel-observed"
    assert run.rebuild().snapshot.status.value == "cancelled"
    assert (
        reconcile_reviewed_native(
            request=world.request, plane=plane, state_dir=state, grant_token=world.token
        ).disposition
        == "cancelled"
    )
