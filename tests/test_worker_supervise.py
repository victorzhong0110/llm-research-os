from __future__ import annotations

import os
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
    _plane,
    _record_execute_local_authorization,
)
from test_worker_recovery import (
    ATTEMPT_ID,
    RUN_ID,
    _identities,
    _request_run_cancel,
    _start_runtime,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import TrustedKernel, authorize_plan
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.storage import EventStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.sandbox import (
    SandboxDisposition,
    _finish_cancelled,
    execute_python_brick,
)
from llm_research_os.workers.supervise import (
    CLOUD_INSTANCE_STOP,
    KIND_OCI,
    KIND_POSIX,
    OBSERVED_STOP,
    UNOBSERVED,
    ExecutionIdentity,
    drop_execution_identity,
    identity_path,
    inspect_container_running,
    load_execution_identity,
    observe_and_stop,
    posix_start_token,
    process_still_running,
    refuse_cloud_instance_stop,
    save_execution_identity,
)

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-checkpoint"
SLEEP_BRICK = """import sys, time
time.sleep(30)
sys.exit(2)
"""


def test_execution_identity_is_private_and_reloadable(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identities"
    identity = ExecutionIdentity(
        lease_id="lease.grant.cpu.1",
        kind=KIND_POSIX,
        pid=4242,
        pgid=4242,
        start_token="17",
        container_id=None,
        docker_executable=None,
    )
    path = save_execution_identity(identity_dir, identity)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(identity_dir.stat().st_mode) == 0o700
    loaded = load_execution_identity(identity_dir, "lease.grant.cpu.1")
    assert loaded == identity


def test_observe_and_stop_reaps_host_process_group() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    assert process.pid is not None
    identity = ExecutionIdentity(
        lease_id="lease.host.1",
        kind=KIND_POSIX,
        pid=process.pid,
        pgid=os.getpgid(process.pid),
        start_token=posix_start_token(process.pid),
        container_id=None,
        docker_executable=None,
    )
    assert observe_and_stop(identity) == OBSERVED_STOP
    process.wait(timeout=3)
    assert process.poll() is not None
    assert process_still_running(process.pid) is False


def test_start_token_mismatch_does_not_kill_live_pid() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    assert process.pid is not None
    token = posix_start_token(process.pid)
    try:
        if token is None:
            pytest.skip("no /proc start token on this host")
        identity = ExecutionIdentity(
            lease_id="lease.reuse.1",
            kind=KIND_POSIX,
            pid=process.pid,
            pgid=os.getpgid(process.pid),
            start_token="0",
            container_id=None,
            docker_executable=None,
        )
        assert token != "0"
        assert observe_and_stop(identity) == UNOBSERVED
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=3)


def test_cloud_instance_stop_is_forbidden() -> None:
    with pytest.raises(WorkerError) as captured:
        refuse_cloud_instance_stop(CLOUD_INSTANCE_STOP)
    assert captured.value.code == "cloud-instance-stop-forbidden"


def test_missing_identity_is_unobserved() -> None:
    assert observe_and_stop(None) == UNOBSERVED


def test_should_cancel_reaps_sleep_brick(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "sleep.py"
    brick.write_text(SLEEP_BRICK, encoding="utf-8")
    digest = artifacts.put(brick).digest
    ticks = {"n": 0}

    def _cancel() -> bool:
        ticks["n"] += 1
        return ticks["n"] >= 2

    identity_dir = tmp_path / "identities"
    result = execute_python_brick(
        artifacts,
        digest,
        timeout_seconds=5,
        identity_dir=identity_dir,
        lease_id="lease.sleep.1",
        should_cancel=_cancel,
    )
    assert result.disposition is SandboxDisposition.FAILED
    assert result.reason_code == "cancel-observed"
    loaded = load_execution_identity(identity_dir, "lease.sleep.1")
    assert loaded is not None
    assert loaded.pid is not None
    assert process_still_running(loaded.pid) is False


def _start_sleep_run(store: EventStore, spec) -> None:
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


def test_heartbeat_cancel_stops_host_process_and_records_observed_stop(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "sleep.py"
    brick.write_text(SLEEP_BRICK, encoding="utf-8")
    image = artifacts.put(brick)
    spec = _cpu_spec_with_image(image.digest)
    registry = build_registry([CORPUS / "block.json"])
    identity_dir = tmp_path / "identities"
    with EventStore(database) as store:
        _record_execute_local_authorization(store, spec, registry)
        _start_sleep_run(store, spec)
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
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
        clock=FrozenClock(NOW),
    )
    captured: list[WorkerError] = []

    def _run() -> None:
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
            identity_dir=identity_dir,
        )
        try:
            client.run_once(artifacts)
        except WorkerError as exc:
            captured.append(exc)

    try:
        server.start()
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if any(identity_dir.glob("*.json")):
                break
            time.sleep(0.05)
        else:
            pytest.fail("execution identity was not recorded")
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
        thread.join(timeout=10)
        assert thread.is_alive() is False
    finally:
        server.stop()
    assert captured
    assert captured[0].code == "cancel-observed"
    with EventStore(database, require_existing=True) as store:
        types = {item.event.type for item in store.read_events(limit=80)}
        reasons = [
            item.event.data.payload.get("reasonCode")
            for item in store.read_events(limit=80)
            if item.event.type == "work.failed"
        ]
        assert "work.failed" in types
        assert "cancel-observed" in reasons
        assert "work.completed" not in types
    leftover = load_execution_identity(identity_dir, "lease.grant.cpu.1")
    assert leftover is None or leftover.pid is None or process_still_running(leftover.pid) is False


def test_cancel_poll_timeout_stays_unknown(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "sleep.py"
    brick.write_text(SLEEP_BRICK, encoding="utf-8")
    digest = artifacts.put(brick).digest
    result = execute_python_brick(
        artifacts,
        digest,
        timeout_seconds=1,
        should_cancel=lambda: False,
    )
    assert result.disposition is SandboxDisposition.UNKNOWN
    assert result.reason_code == "worker.process.timeout"


def test_corrupt_identity_is_missing(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identities"
    save_execution_identity(
        identity_dir,
        ExecutionIdentity(
            lease_id="lease.bad.1",
            kind=KIND_POSIX,
            pid=1,
            pgid=1,
            start_token=None,
            container_id=None,
            docker_executable=None,
        ),
    )
    identity_path(identity_dir, "lease.bad.1").write_text("[", encoding="utf-8")
    assert load_execution_identity(identity_dir, "lease.bad.1") is None
    identity_path(identity_dir, "lease.bad.1").write_text("[]", encoding="utf-8")
    assert load_execution_identity(identity_dir, "lease.bad.1") is None
    identity_path(identity_dir, "lease.bad.1").write_text(
        '{"kind":"cloud-instance"}',
        encoding="utf-8",
    )
    assert load_execution_identity(identity_dir, "lease.bad.1") is None
    drop_execution_identity(identity_dir, "lease.missing")
    assert load_execution_identity(identity_dir, "lease.missing") is None
    identity_path(identity_dir, "lease.empty.fields").write_text(
        '{"kind":"posix-pg","pid":0,"pgid":true,"startToken":"","containerId":"","dockerExecutable":""}',
        encoding="utf-8",
    )
    empty = load_execution_identity(identity_dir, "lease.empty.fields")
    assert empty is not None
    assert empty.pid is None
    assert empty.pgid is None
    assert empty.start_token is None
    assert empty.container_id is None
    assert empty.docker_executable is None


def test_posix_identity_without_pids_is_unobserved() -> None:
    identity = ExecutionIdentity(
        lease_id="lease.empty.1",
        kind=KIND_POSIX,
        pid=None,
        pgid=None,
        start_token=None,
        container_id=None,
        docker_executable=None,
    )
    assert observe_and_stop(identity) == UNOBSERVED


def test_dead_pid_is_observed_stop() -> None:
    identity = ExecutionIdentity(
        lease_id="lease.dead.1",
        kind=KIND_POSIX,
        pid=999_999_991,
        pgid=999_999_991,
        start_token=None,
        container_id=None,
        docker_executable=None,
    )
    assert observe_and_stop(identity) == OBSERVED_STOP


def test_refuse_cloud_ignores_container_stop() -> None:
    refuse_cloud_instance_stop("container-stop")


class _DockerProc:
    def __init__(self, returncode: int, stdout: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_oci_stop_confirms_already_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _fake(args: list[str], executable: str) -> _DockerProc:
        calls.append(args)
        if args[0] == "inspect":
            return _DockerProc(0, b"false\n")
        return _DockerProc(0, b"")

    monkeypatch.setattr("llm_research_os.workers.supervise._docker", _fake)
    identity = ExecutionIdentity(
        lease_id="lease.oci.1",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="abc123",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == OBSERVED_STOP
    assert calls[0][0] == "inspect"
    assert calls[-1][0] == "rm"


def test_oci_stop_then_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    inspects = {"n": 0}

    def _fake(args: list[str], executable: str) -> _DockerProc:
        if args[0] == "inspect":
            inspects["n"] += 1
            if inspects["n"] == 1:
                return _DockerProc(0, b"true\n")
            return _DockerProc(0, b"false\n")
        return _DockerProc(0, b"")

    monkeypatch.setattr("llm_research_os.workers.supervise._docker", _fake)
    identity = ExecutionIdentity(
        lease_id="lease.oci.2",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="def456",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == OBSERVED_STOP


def test_oci_kill_after_stop_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    inspects = {"n": 0}

    def _fake(args: list[str], executable: str) -> _DockerProc:
        if args[0] == "inspect":
            inspects["n"] += 1
            if inspects["n"] <= 2:
                return _DockerProc(0, b"true\n")
            return _DockerProc(0, b"false\n")
        return _DockerProc(0, b"")

    monkeypatch.setattr("llm_research_os.workers.supervise._docker", _fake)
    identity = ExecutionIdentity(
        lease_id="lease.oci.3",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="ghi789",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == OBSERVED_STOP


def test_oci_missing_inspect_is_unobserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_research_os.workers.supervise._docker", lambda *_a, **_k: None)
    identity = ExecutionIdentity(
        lease_id="lease.oci.4",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="missing",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == UNOBSERVED
    assert inspect_container_running("/usr/bin/docker", "missing") is None


def test_oci_still_running_after_kill_is_unobserved(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(args: list[str], executable: str) -> _DockerProc:
        if args[0] == "inspect":
            return _DockerProc(0, b"true\n")
        return _DockerProc(0, b"")

    monkeypatch.setattr("llm_research_os.workers.supervise._docker", _fake)
    identity = ExecutionIdentity(
        lease_id="lease.oci.5",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="live",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == UNOBSERVED


def test_oci_identity_without_container_is_unobserved() -> None:
    identity = ExecutionIdentity(
        lease_id="lease.oci.6",
        kind=KIND_OCI,
        pid=1,
        pgid=1,
        start_token=None,
        container_id=None,
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == UNOBSERVED


def test_inspect_nonzero_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_research_os.workers.supervise._docker",
        lambda *_a, **_k: _DockerProc(1, b""),
    )
    assert inspect_container_running("/usr/bin/docker", "x") is None


def test_inspect_rejects_unknown_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_research_os.workers.supervise._docker",
        lambda *_a, **_k: _DockerProc(0, b"maybe\n"),
    )
    assert inspect_container_running("/usr/bin/docker", "x") is None


def test_oci_identity_roundtrip(tmp_path: Path) -> None:
    identity = ExecutionIdentity(
        lease_id="lease.oci.round",
        kind=KIND_OCI,
        pid=8,
        pgid=8,
        start_token=None,
        container_id="0123abcd",
        docker_executable="/usr/bin/docker",
    )
    save_execution_identity(tmp_path / "identities", identity)
    assert load_execution_identity(tmp_path / "identities", "lease.oci.round") == identity


def test_docker_os_error_is_unobserved(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("docker missing")

    monkeypatch.setattr("llm_research_os.workers.supervise.subprocess.run", _boom)
    identity = ExecutionIdentity(
        lease_id="lease.oci.err",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="err",
        docker_executable="/usr/bin/docker",
    )
    assert observe_and_stop(identity) == UNOBSERVED


def test_resumed_cancel_with_dead_identity_is_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    database = tmp_path / "research.db"
    identity_dir = tmp_path / "identities"
    try:
        _start_runtime(store)
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        save_execution_identity(
            identity_dir,
            ExecutionIdentity(
                lease_id=claimed.lease_id,
                kind=KIND_POSIX,
                pid=999_999_992,
                pgid=999_999_992,
                start_token=None,
                container_id=None,
                docker_executable=None,
            ),
        )
        _request_run_cancel(store, event_id="evt.run.cancel.requested.worker")
    finally:
        store.__exit__(None, None, None)

    def _forbid(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("resume must not spawn")

    monkeypatch.setattr("llm_research_os.workers.sandbox.subprocess.Popen", _forbid)
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
        clock=FrozenClock(NOW),
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
            identity_dir=identity_dir,
        )
        with pytest.raises(WorkerError) as captured:
            client.run_once(artifacts)
        assert captured.value.code == "cancel-observed"
    finally:
        server.stop()
    with EventStore(database, require_existing=True) as store:
        types = {item.event.type for item in store.read_events(limit=80)}
        assert "work.failed" in types
        assert "work.completed" not in types


def test_oci_cancel_unobserved_keeps_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_research_os.workers.sandbox.observe_and_stop",
        lambda _identity: UNOBSERVED,
    )
    done = threading.Thread(target=lambda: None)
    done.start()
    done.join()
    identity = ExecutionIdentity(
        lease_id="lease.oci.cancel",
        kind=KIND_OCI,
        pid=None,
        pgid=None,
        start_token=None,
        container_id="cid",
        docker_executable="/usr/bin/docker",
    )
    result = _finish_cancelled(None, None, identity, done, done, [], ())  # type: ignore[arg-type]
    assert result.disposition is SandboxDisposition.UNKNOWN
    assert result.reason_code == UNOBSERVED


def test_killpg_error_falls_back_to_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    assert process.pid is not None

    def _boom(target: int, sig: int) -> None:
        raise OSError("killpg denied")

    monkeypatch.setattr(os, "killpg", _boom)
    try:
        identity = ExecutionIdentity(
            lease_id="lease.fallback.1",
            kind=KIND_POSIX,
            pid=process.pid,
            pgid=os.getpgid(process.pid),
            start_token=posix_start_token(process.pid),
            container_id=None,
            docker_executable=None,
        )
        assert observe_and_stop(identity) == OBSERVED_STOP
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def test_ps_helper_handles_missing_binary_and_zombie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_research_os.workers.supervise import _ps_process_running

    monkeypatch.setattr("llm_research_os.workers.supervise.shutil.which", lambda _name: None)
    assert _ps_process_running(os.getpid()) is True

    class _Ps:
        def __init__(self, returncode: int, stdout: bytes) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        "llm_research_os.workers.supervise.shutil.which",
        lambda _name: "/bin/ps",
    )
    monkeypatch.setattr(
        "llm_research_os.workers.supervise.subprocess.run",
        lambda *_a, **_k: _Ps(0, b"Z\n"),
    )
    assert _ps_process_running(1) is False
    monkeypatch.setattr(
        "llm_research_os.workers.supervise.subprocess.run",
        lambda *_a, **_k: _Ps(1, b""),
    )
    assert _ps_process_running(1) is False
    monkeypatch.setattr(
        "llm_research_os.workers.supervise.subprocess.run",
        lambda *_a, **_k: _Ps(0, b""),
    )
    assert _ps_process_running(1) is False
