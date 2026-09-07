from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_worker_protocol import (
    HMAC_KEY,
    NOW,
    PROJECT,
    SOURCE,
    FrozenClock,
    _cpu_spec_with_image,
    _grant_and_queue,
    _record_execute_local_authorization,
)
from test_worker_recovery import (
    ATTEMPT_ID,
    RUN_ID,
    _identities,
    _request_run_cancel,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import TrustedKernel, authorize_plan
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerCallError, WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import reconcile_worker_run
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.supervise import (
    ExecutionIdentity,
    PendingComplete,
    load_execution_identity,
    load_pending_complete,
    observe_and_stop,
    process_still_running,
    save_pending_complete,
)

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-checkpoint"
LEASE_ID = "lease.grant.cpu.1"
SLEEP_BRICK = """import sys, time
time.sleep(30)
sys.exit(2)
"""
_WORKER_MAIN = """\
from __future__ import annotations

import json
import sys
from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
client = WorkerClient(
    base_url=cfg["baseUrl"],
    worker_id=cfg["workerId"],
    session=cfg["session"],
    grant_token=cfg["grantToken"],
    identity_dir=Path(cfg["identityDir"]),
    timeout_seconds=int(cfg["timeoutSeconds"]),
)
try:
    client.run_once(LocalArtifactStore(Path(cfg["artifacts"])))
except WorkerError as exc:
    Path(cfg["errorPath"]).write_text(exc.code, encoding="utf-8")
    raise SystemExit(2)
"""


def _start_live_runtime(store: EventStore, spec: ResearchSpec) -> tuple[WorkerRuntime, object]:
    registry = build_registry([CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.local",),
    )
    authorization = authorize_plan(report, policy)
    stored = store.get_event("evt.authorization.example-minimal.1")
    assert stored is not None
    runtime = WorkerRuntime(
        store,
        project_id=PROJECT,
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        source=SOURCE,
        subject=RUN_ID,
        stream_id=RUN_ID,
        actor_id="researcher.alice",
        events=_identities(),
    )
    runtime.start(
        report=report,
        authorization=authorization,
        citation={"eventId": stored.event.id, "sequence": stored.event.sequence},
        revision=1,
    )
    return runtime, report


def _queue_live(
    tmp_path: Path, brick: Path | str
) -> tuple[Path, LocalArtifactStore, Path, str, ResearchSpec]:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    if type(brick) is str:
        path = tmp_path / "live-brick.py"
        path.write_text(brick, encoding="utf-8")
        image = artifacts.put(path)
    else:
        image = artifacts.put(brick)
    spec = _cpu_spec_with_image(image.digest)
    registry = build_registry([CORPUS / "block.json"])
    identity_dir = tmp_path / "identities"
    with EventStore(database) as store:
        _record_execute_local_authorization(store, spec, registry)
        _start_live_runtime(store, spec)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id="worker.loopback.1",
            actor_id="researcher.alice",
            event_id="evt.worker.registered.1",
        )
        token = _grant_and_queue(plane, image.digest, spec=spec, registry=registry)
    return database, artifacts, identity_dir, token, spec


def _server(
    database: Path,
    artifacts: LocalArtifactStore,
    *,
    port: int = 0,
) -> LoopbackWorkerServer:
    return LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
        clock=FrozenClock(NOW),
        port=port,
    )


def _client(
    server: LoopbackWorkerServer,
    token: str,
    identity_dir: Path,
    *,
    timeout_seconds: int = 30,
) -> WorkerClient:
    return WorkerClient(
        base_url=server.base_url,
        worker_id="worker.loopback.1",
        session=server.session_for("worker.loopback.1"),
        grant_token=token,
        identity_dir=identity_dir,
        timeout_seconds=timeout_seconds,
    )


def _wait_identity(identity_dir: Path, lease_id: str = LEASE_ID) -> ExecutionIdentity:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        loaded = load_execution_identity(identity_dir, lease_id)
        if loaded is not None and loaded.pid is not None:
            return loaded
        time.sleep(0.05)
    pytest.fail("execution identity was not recorded")


def _event_types(database: Path) -> set[str]:
    with EventStore(database, require_existing=True) as store:
        return {item.event.type for item in store.read_events(limit=80)}


def _runtime_for(store: EventStore) -> WorkerRuntime:
    return WorkerRuntime(
        store,
        project_id=PROJECT,
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        source=SOURCE,
        subject=RUN_ID,
        stream_id=RUN_ID,
        actor_id="researcher.alice",
        events=_identities(),
    )


def _spawn_worker_process(
    tmp_path: Path,
    server: LoopbackWorkerServer,
    token: str,
    identity_dir: Path,
    artifacts: LocalArtifactStore,
    *,
    timeout_seconds: int = 30,
) -> subprocess.Popen[bytes]:
    script = tmp_path / "live-worker.py"
    script.write_text(_WORKER_MAIN, encoding="utf-8")
    config = tmp_path / "live-worker.json"
    error_path = tmp_path / "live-worker-error.txt"
    config.write_text(
        json.dumps(
            {
                "baseUrl": server.base_url,
                "workerId": "worker.loopback.1",
                "session": server.session_for("worker.loopback.1"),
                "grantToken": token,
                "identityDir": str(identity_dir),
                "artifacts": str(artifacts.root),
                "timeoutSeconds": timeout_seconds,
                "errorPath": str(error_path),
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return subprocess.Popen(
        [sys.executable, str(script), str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_pending_complete_is_private_and_reloadable(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identities"
    digest = "jcs-sha256:" + ("a" * 64)
    other = "sha256:" + ("b" * 64)
    path = save_pending_complete(
        identity_dir,
        PendingComplete(lease_id=LEASE_ID, result_digest=digest, artifact_digest=other),
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = load_pending_complete(identity_dir, LEASE_ID)
    assert loaded is not None
    assert loaded.result_digest == digest
    assert loaded.artifact_digest == other
    path.write_text("{not-json", encoding="utf-8")
    assert load_pending_complete(identity_dir, LEASE_ID) is None


def test_running_cancel_observes_process_then_reconciles(tmp_path: Path) -> None:
    database, artifacts, identity_dir, token, spec = _queue_live(tmp_path, SLEEP_BRICK)
    server = _server(database, artifacts)
    captured: list[WorkerError] = []

    def _run() -> None:
        try:
            _client(server, token, identity_dir).run_once(artifacts)
        except WorkerError as exc:
            captured.append(exc)

    try:
        server.start()
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        assert process_still_running(identity.pid) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        thread.join(timeout=10)
        assert thread.is_alive() is False
        assert process_still_running(identity.pid) is False
    finally:
        server.stop()
    assert captured and captured[0].code == "cancel-observed"
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types
    with EventStore(database, require_existing=True) as store:
        snapshot = reconcile_worker_run(
            store,
            _runtime_for(store),
            WorkerPlane(
                store,
                artifacts=artifacts,
                hmac_key=HMAC_KEY,
                project_id=PROJECT,
                source=SOURCE,
                clock=FrozenClock(NOW),
            ).rebuild(),
            project_id=PROJECT,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            report=TrustedKernel(build_registry([CORPUS / "block.json"])).dry_run(
                spec, workflow_id=spec.workflows[0].id
            ),
            revision=1,
        )
        assert snapshot.status is RunStatus.CANCELLED
        assert snapshot.attempts[0].status is AttemptStatus.CANCELLED


def test_timeout_reaps_process_stays_unknown_and_does_not_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, artifacts, identity_dir, token, spec = _queue_live(tmp_path, SLEEP_BRICK)
    spawns = {"n": 0}
    from llm_research_os.workers import client as client_mod

    original = client_mod.execute_python_brick

    def _count(*args: object, **kwargs: object) -> object:
        spawns["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client_mod, "execute_python_brick", _count)
    server = _server(database, artifacts)
    try:
        server.start()
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir, timeout_seconds=1).run_once(artifacts)
        assert captured.value.code == "worker.process.timeout"
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        assert leftover is None
        first_spawns = spawns["n"]
        assert first_spawns == 1
        with pytest.raises(WorkerError) as resumed:
            _client(server, token, identity_dir, timeout_seconds=1).run_once(artifacts)
        assert resumed.value.code == "work-already-claimed"
        assert spawns["n"] == first_spawns
    finally:
        server.stop()
    types = _event_types(database)
    assert "work.failed" not in types
    assert "work.completed" not in types
    with EventStore(database, require_existing=True) as store:
        runtime, report = (
            _runtime_for(store),
            TrustedKernel(build_registry([CORPUS / "block.json"])).dry_run(
                spec, workflow_id=spec.workflows[0].id
            ),
        )
        runtime.unknown(reason_code="worker.process.timeout", revision=1)
        with pytest.raises(WorkerCallError) as reconcile_error:
            reconcile_worker_run(
                store,
                runtime,
                WorkerPlane(
                    store,
                    artifacts=artifacts,
                    hmac_key=HMAC_KEY,
                    project_id=PROJECT,
                    source=SOURCE,
                    clock=FrozenClock(NOW),
                ).rebuild(),
                project_id=PROJECT,
                run_id=RUN_ID,
                attempt_id=ATTEMPT_ID,
                report=report,
                revision=1,
            )
        assert reconcile_error.value.code == "attempt-unknown"
        snapshot = RunControl(store, project_id=PROJECT, run_id=RUN_ID).rebuild().snapshot
        assert snapshot is not None
        assert snapshot.status is RunStatus.UNKNOWN


def test_killed_worker_leaves_orphan_recovery_does_not_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("SIGKILL orphan recovery is a POSIX Worker outcome")
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, SLEEP_BRICK)
    from llm_research_os.workers import client as client_mod

    original = client_mod.execute_python_brick
    spawns = {"n": 0}

    def _count(*args: object, **kwargs: object) -> object:
        spawns["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client_mod, "execute_python_brick", _count)
    server = _server(database, artifacts)
    worker: subprocess.Popen[bytes] | None = None
    try:
        server.start()
        worker = _spawn_worker_process(tmp_path, server, token, identity_dir, artifacts)
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        assert worker.pid is not None
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        assert process_still_running(identity.pid) is True
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir).run_once(artifacts)
        assert captured.value.code == "work-already-claimed"
        assert spawns["n"] == 0
        assert process_still_running(identity.pid) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        with pytest.raises(WorkerError) as stopped:
            _client(server, token, identity_dir).run_once(artifacts)
        assert stopped.value.code == "cancel-observed"
        assert process_still_running(identity.pid) is False
        assert spawns["n"] == 0
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        if leftover is not None and leftover.pid is not None:
            observe_and_stop(leftover)
        server.stop()
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types


def test_control_plane_restart_keeps_executor_then_observes_cancel(
    tmp_path: Path,
) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, SLEEP_BRICK)
    server = _server(database, artifacts)
    captured: list[WorkerError] = []
    thread: threading.Thread | None = None
    restarted: LoopbackWorkerServer | None = None
    original_stopped = False
    try:
        server.start()
        port = server.port

        def _run() -> None:
            try:
                _client(server, token, identity_dir).run_once(artifacts)
            except WorkerError as exc:
                captured.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        server.stop()
        original_stopped = True
        restarted = _server(database, artifacts, port=port)
        restarted.start()
        assert process_still_running(identity.pid) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        assert thread is not None
        thread.join(timeout=10)
        assert thread.is_alive() is False
        assert process_still_running(identity.pid) is False
    finally:
        if thread is not None and thread.is_alive():
            leftover = load_execution_identity(identity_dir, LEASE_ID)
            if leftover is not None:
                observe_and_stop(leftover)
            thread.join(timeout=5)
        if restarted is not None:
            restarted.stop()
        elif not original_stopped:
            server.stop()
    assert captured
    assert captured[0].code == "cancel-observed"
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types


def test_disconnect_after_upload_retries_complete_without_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, CORPUS / "brick.py")
    from llm_research_os.workers import client as client_mod

    original_execute = client_mod.execute_python_brick
    original_complete = WorkerClient.complete
    spawns = {"n": 0}
    completes = {"n": 0}

    def _count_execute(*args: object, **kwargs: object) -> object:
        spawns["n"] += 1
        return original_execute(*args, **kwargs)

    def _flaky_complete(self: WorkerClient, **kwargs: object) -> object:
        completes["n"] += 1
        if completes["n"] == 1:
            raise WorkerError("disconnected before complete", code="http-disconnect")
        return original_complete(self, **kwargs)

    monkeypatch.setattr(client_mod, "execute_python_brick", _count_execute)
    monkeypatch.setattr(WorkerClient, "complete", _flaky_complete)
    server = _server(database, artifacts)
    try:
        server.start()
        client = _client(server, token, identity_dir, timeout_seconds=5)
        with pytest.raises(WorkerError) as captured:
            client.run_once(artifacts)
        assert captured.value.code == "http-disconnect"
        assert spawns["n"] == 1
        pending = load_pending_complete(identity_dir, LEASE_ID)
        assert pending is not None
        receipt = client.run_once(artifacts)
        assert receipt is not None
        assert receipt["type"] == "work.completed"
        assert spawns["n"] == 1
        assert completes["n"] == 2
        assert load_pending_complete(identity_dir, LEASE_ID) is None
    finally:
        server.stop()
    types = _event_types(database)
    assert "work.completed" in types
    assert "work.leased" in types


def test_recovery_client_while_executor_alive_does_not_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, SLEEP_BRICK)
    from llm_research_os.workers import client as client_mod

    original = client_mod.execute_python_brick
    spawns = {"n": 0}

    def _count(*args: object, **kwargs: object) -> object:
        spawns["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client_mod, "execute_python_brick", _count)
    server = _server(database, artifacts)
    captured: list[WorkerError] = []
    try:
        server.start()

        def _run() -> None:
            try:
                _client(server, token, identity_dir).run_once(artifacts)
            except WorkerError as exc:
                captured.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        assert spawns["n"] == 1
        with pytest.raises(WorkerError) as second:
            _client(server, token, identity_dir).run_once(artifacts)
        assert second.value.code == "work-already-claimed"
        assert spawns["n"] == 1
        assert process_still_running(identity.pid) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        thread.join(timeout=10)
        assert thread.is_alive() is False
        assert process_still_running(identity.pid) is False
    finally:
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        if leftover is not None:
            observe_and_stop(leftover)
        server.stop()
    assert captured and captured[0].code == "cancel-observed"


def test_duplicate_complete_after_live_execute_is_idempotent(tmp_path: Path) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, CORPUS / "brick.py")
    server = _server(database, artifacts)
    try:
        server.start()
        client = _client(server, token, identity_dir, timeout_seconds=5)
        first = client.run_once(artifacts)
        assert first is not None
        with EventStore(database, require_existing=True) as store:
            completed = next(
                item for item in store.read_events(limit=80) if item.event.type == "work.completed"
            )
            payload = completed.event.data.payload
        again = client.complete(
            lease_id=LEASE_ID,
            result_digest=str(payload["resultDigest"]),
            artifact_digest=str(payload["artifactDigest"]),
        )
        assert again["eventId"] == first["eventId"]
    finally:
        server.stop()


def test_expired_lease_refuses_result_while_process_still_runs(tmp_path: Path) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, SLEEP_BRICK)
    server = _server(database, artifacts)
    captured: list[WorkerError] = []
    try:
        server.start()

        def _run() -> None:
            try:
                _client(server, token, identity_dir).run_once(artifacts)
            except WorkerError as exc:
                captured.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        with EventStore(database, require_existing=True) as store:
            plane = WorkerPlane(
                store,
                artifacts=artifacts,
                hmac_key=HMAC_KEY,
                project_id=PROJECT,
                source=SOURCE,
                clock=FrozenClock(NOW),
            )
            plane.expire_lease(lease_id=LEASE_ID)
        assert process_still_running(identity.pid) is True
        types = _event_types(database)
        assert "work.lease.expired" in types
        assert "work.failed" not in types
        observe_and_stop(identity)
        assert process_still_running(identity.pid) is False
        thread.join(timeout=10)
        assert thread.is_alive() is False
    finally:
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        if leftover is not None:
            observe_and_stop(leftover)
        server.stop()
    assert "cancel-observed" not in {exc.code for exc in captured}


def test_revoked_grant_refuses_new_result_while_process_still_runs(tmp_path: Path) -> None:
    database, artifacts, identity_dir, token, _spec = _queue_live(tmp_path, SLEEP_BRICK)
    server = _server(database, artifacts)
    try:
        server.start()
        captured: list[WorkerError] = []

        def _run() -> None:
            try:
                _client(server, token, identity_dir).run_once(artifacts)
            except WorkerError as exc:
                captured.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        identity = _wait_identity(identity_dir)
        assert identity.pid is not None
        with EventStore(database, require_existing=True) as store:
            plane = WorkerPlane(
                store,
                artifacts=artifacts,
                hmac_key=HMAC_KEY,
                project_id=PROJECT,
                source=SOURCE,
                clock=FrozenClock(NOW),
            )
            plane.revoke_grant(
                grant_id="grant.cpu.1",
                actor_id="researcher.alice",
                event_id="evt.grant.revoked.1",
            )
        assert process_still_running(identity.pid) is True
        with pytest.raises(WorkerError) as resumed:
            _client(server, token, identity_dir).run_once(artifacts)
        assert resumed.value.code == "http-poll-failed"
        assert process_still_running(identity.pid) is True
        observe_and_stop(identity)
        assert process_still_running(identity.pid) is False
        thread.join(timeout=10)
        assert thread.is_alive() is False
        assert captured
    finally:
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        if leftover is not None:
            observe_and_stop(leftover)
        server.stop()
    types = _event_types(database)
    assert "authorization.grant.revoked" in types
    assert "work.completed" not in types
