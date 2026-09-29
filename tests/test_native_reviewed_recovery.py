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
    _lifecycle(run, world.request, "run.cancel.requested", {"reasonCode": "user-requested"})
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
    monkeypatch.setattr(recovery, "posix_start_token", lambda *_: "reused")
    monkeypatch.setattr(recovery, "observe_process_group", lambda *_: "running")
    monkeypatch.setattr(recovery, "observe_process", lambda *_: "running")
    monkeypatch.setattr(
        recovery, "observe_and_stop", lambda *_: pytest.fail("must not signal reused PID")
    )
    result = reconcile_reviewed_native(
        request=world.request, plane=plane, state_dir=state, grant_token=world.token
    )
    assert result.disposition == "unknown"
    assert plane.store.get_event("evt.work.failed.lease.grant.native") is None


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
