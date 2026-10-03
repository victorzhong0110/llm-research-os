"""Actual CPU child, independent Worker CAS, TLS barrier and conservative recovery."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_native_material_preparation import _worker
from test_native_reviewed_preparation import NOW, PROJECT, SOURCE
from test_native_reviewed_runtime import TASK, _world

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers import native_executor, native_outcome_client, native_start_client
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.native_claim import NativeControllerContext
from llm_research_os.workers.native_executor import execute_remote_native, reconcile_remote_native
from llm_research_os.workers.supervise import (
    OBSERVATION_EXITED,
    observe_process_group,
    posix_start_token,
)
from llm_research_os.workers.tls import load_or_create_loopback_tls


@pytest.fixture
def live_host():  # type: ignore[no-untyped-def]
    if posix_start_token(os.getpid()) is None:
        message = "host hides POSIX start identity; designated native remote CI must provide it"
        if os.environ.get("RESEARCHOS_NATIVE_REMOTE_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)


def _setup(tmp_path, task=TASK):  # type: ignore[no-untyped-def]
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    server = LoopbackWorkerServer(
        world.database,
        plane.artifacts,
        hmac_key=world.hmac_key,
        project_id=PROJECT,
        source=SOURCE,
        clock=lambda: NOW,
        tls=tls,
        native_context=NativeControllerContext(spec, registry),
    )
    server.start()
    client = WorkerClient(
        server.base_url,
        world.request.worker_id,
        server.session_for(world.request.worker_id),
        world.token,
        ca_path=tls.cert_path,
        tls_fingerprint=tls.fingerprint,
    )
    artifacts, workspace, staging = _worker(tmp_path)
    state = workspace.parent / "state"
    state.mkdir(mode=0o700)
    kwargs = dict(artifacts=artifacts, workspace=workspace, staging_root=staging, state_root=state)
    return world, plane, server, client, kwargs


def _snapshot(world, plane):  # type: ignore[no-untyped-def]
    return (
        RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id).rebuild().snapshot
    )


def _recover(client, world, kwargs):  # type: ignore[no-untyped-def]
    return reconcile_remote_native(
        replace(client),
        artifacts=LocalArtifactStore(kwargs["artifacts"].root),
        state_root=kwargs["state_root"],
        request=world.request,
    )


def _forbid_task_launch(monkeypatch):  # type: ignore[no-untyped-def]
    original = native_executor.subprocess.Popen

    def observe_only(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        # macOS OS observation uses fixed ps/pgrep subprocesses. Allow actual
        # observation while retaining the tripwire against any task/driver launch.
        assert isinstance(argv, list) and Path(argv[0]).name in {"ps", "pgrep"}, (
            "recovery attempted to launch a task"
        )
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(native_executor.subprocess, "Popen", observe_only)


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_actual_cpu_output_and_restart_replays_without_launch(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    try:
        result = execute_remote_native(client, **kwargs)
        assert result.disposition == "completed"
        assert result.output == {
            "rows": 1,
            "sha256": "815853a11c4f2e2e5355f547308cd7c6054f85ba6a324b2c37beb8edbec1fb93",
        }
        assert _snapshot(world, plane).status.value == "completed"
        assert kwargs["artifacts"].root != plane.artifacts.root
        assert not list(kwargs["workspace"].parent.rglob("*.sqlite"))
        assert world.hmac_key.hex() not in "".join(
            p.read_text() for p in kwargs["state_root"].iterdir() if p.stat().st_size
        )
        before = plane.store.last_sequence()
        _forbid_task_launch(monkeypatch)
        monkeypatch.setattr(WorkerClient, "poll", lambda *a: pytest.fail("recovery polled"))
        replay = _recover(client, world, kwargs)
        assert replay == result
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_actual_task_failure_is_observed_and_not_retryable(tmp_path):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(
        tmp_path, b"def main():\n    raise RuntimeError('reviewed fixture failure')\n"
    )
    try:
        result = execute_remote_native(client, **kwargs)
        assert result.disposition == "failed"
        assert _snapshot(world, plane).status.value == "failed"
        assert plane.rebuild().lease(result.lease_id).reason_code == "native-task-failed"
        assert _recover(client, world, kwargs) == result
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
@pytest.mark.parametrize("route", ["start", "outcome"])
def test_actual_lost_acknowledgement_retries_one_identity(tmp_path, monkeypatch, route):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    module = native_start_client if route == "start" else native_outcome_client
    connect = module._connection
    lost = []

    class LoseOnce:
        def __init__(self, connection):  # type: ignore[no-untyped-def]
            self.connection = connection

        def request(self, *a, **k):  # type: ignore[no-untyped-def]
            self.connection.request(*a, **k)

        def getresponse(self):  # type: ignore[no-untyped-def]
            response = self.connection.getresponse()
            response.read()
            lost.append(1)
            raise OSError("fixture lost acknowledgement")

        def close(self):  # type: ignore[no-untyped-def]
            self.connection.close()

    monkeypatch.setattr(
        module,
        "_connection",
        lambda *a, **k: connect(*a, **k) if lost else LoseOnce(connect(*a, **k)),
    )
    try:
        result = execute_remote_native(client, **kwargs)
        assert result.disposition == "completed" and lost == [1]
        assert len(list(kwargs["state_root"].glob("*.identity"))) == 1
        assert _snapshot(world, plane).status.value == "completed"
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_actual_barrier_refusal_never_imports_task(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    task = (
        b"from pathlib import Path\nPath('imported').write_text('yes')\ndef main():\n return {}\n"
    )
    world, plane, server, client, kwargs = _setup(tmp_path, task)

    def refuse(*a):  # type: ignore[no-untyped-def]
        raise WorkerError("fixture rejected start", code="native-start-refused")

    monkeypatch.setattr(native_executor, "publish_native_start", refuse)
    try:
        with pytest.raises(WorkerError):
            execute_remote_native(client, **kwargs)
        assert not (kwargs["workspace"] / "imported").exists()
        assert _snapshot(world, plane).attempts[0].status.value == "queued"
        identity = json.loads(next(kwargs["state_root"].glob("*.identity")).read_text())
        assert observe_process_group(identity["pgid"], identity["pid"]) == OBSERVATION_EXITED
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_actual_cancel_observes_process_group_stop(tmp_path):  # type: ignore[no-untyped-def]
    task = (
        b"import time\nfrom pathlib import Path\ndef main():\n"
        b" Path('started').write_text('yes')\n time.sleep(30)\n return {}\n"
    )
    world, plane, server, client, kwargs = _setup(tmp_path, task)
    results, errors = [], []

    def execute():  # type: ignore[no-untyped-def]
        try:
            results.append(execute_remote_native(client, **kwargs))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not (kwargs["workspace"] / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (kwargs["workspace"] / "started").exists(), errors
        _lifecycle(
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id),
            world.request,
            "run.cancel.requested",
            {"reasonCode": "user-requested"},
        )
        thread.join(timeout=15)
        assert not thread.is_alive() and not errors
        assert results[0].disposition == "cancelled"
        identity = json.loads(next(kwargs["state_root"].glob("*.identity")).read_text())
        assert observe_process_group(identity["pgid"], identity["pid"]) == OBSERVATION_EXITED
        assert _snapshot(world, plane).status.value == "cancelled"
        assert _recover(client, world, kwargs) == results[0]
    finally:
        thread.join(timeout=35)
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
@pytest.mark.parametrize("stage", ["upload", "outcome"])
def test_actual_stopped_child_result_survives_disconnect(tmp_path, monkeypatch, stage):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    target, attribute = (
        (WorkerClient, "upload_native_output")
        if stage == "upload"
        else (native_executor, "publish_native_outcome")
    )
    original = getattr(target, attribute)

    def disconnect(*a, **k):  # type: ignore[no-untyped-def]
        raise WorkerError("fixture disconnected", code="http-disconnect")

    monkeypatch.setattr(target, attribute, disconnect)
    try:
        with pytest.raises(WorkerError):
            execute_remote_native(client, **kwargs)
        assert _snapshot(world, plane).status.value == "running"
        monkeypatch.setattr(target, attribute, original)
        _forbid_task_launch(monkeypatch)
        monkeypatch.setattr(WorkerClient, "poll", lambda *a: pytest.fail("recovery polled"))
        result = _recover(client, world, kwargs)
        assert result.disposition == "completed"
        assert _recover(client, world, kwargs) == result
        assert _snapshot(world, plane).status.value == "completed"
    finally:
        server.stop()
        plane.store.close()


def test_lost_claim_retains_intent_and_never_retries_launch(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)

    def disconnect(*a):  # type: ignore[no-untyped-def]
        raise WorkerError("fixture lost claim", code="http-disconnect")

    monkeypatch.setattr(WorkerClient, "poll", disconnect)
    monkeypatch.setattr(
        native_executor.subprocess, "Popen", lambda *a, **k: pytest.fail("uncertain claim spawned")
    )
    try:
        with pytest.raises(WorkerError):
            execute_remote_native(client, **kwargs)
        assert len(list(kwargs["state_root"].glob("*.intent"))) == 1
        with pytest.raises(WorkerError) as exc:
            execute_remote_native(client, **kwargs)
        assert exc.value.code == "native-intent-exists"
        assert _recover(client, world, kwargs).disposition == "unknown"
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
@pytest.mark.parametrize("completed_first", [False, True])
def test_actual_pending_output_cancel_race_preserves_work_facts(
    tmp_path, monkeypatch, completed_first
):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    target, attribute = (
        (native_executor, "publish_native_outcome")
        if completed_first
        else (WorkerClient, "upload_native_output")
    )
    original = getattr(target, attribute)

    def disconnected(*a, **k):  # type: ignore[no-untyped-def]
        raise WorkerError("fixture disconnected", code="http-disconnect")

    monkeypatch.setattr(target, attribute, disconnected)
    try:
        with pytest.raises(WorkerError):
            execute_remote_native(client, **kwargs)
        _lifecycle(
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id),
            world.request,
            "run.cancel.requested",
            {"reasonCode": "user-requested"},
        )
        monkeypatch.setattr(target, attribute, original)
        result = _recover(client, world, kwargs)
        assert result.disposition == ("completed" if completed_first else "cancelled")
        assert _recover(client, world, kwargs) == result
        assert _snapshot(world, plane).status.value == result.disposition
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_actual_worker_crash_then_cancel_observes_existing_child(tmp_path):  # type: ignore[no-untyped-def]
    import subprocess
    import sys

    task = (
        b"import time\nfrom pathlib import Path\ndef main():\n"
        b" Path('started').write_text('yes')\n time.sleep(30)\n return {}\n"
    )
    world, plane, server, client, kwargs = _setup(tmp_path, task)
    # The Worker subprocess receives its scoped credentials through stdin, never
    # controller DB/key or shell/argv. Killing this owned Worker leaves the child's
    # independent recorded session for real restart observation.
    driver = """import json,sys
from pathlib import Path
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.native_executor import execute_remote_native
p=json.load(sys.stdin)
c=WorkerClient(p['url'],p['worker'],p['session'],p['token'],ca_path=Path(p['ca']),tls_fingerprint=p['pin'])
execute_remote_native(c,artifacts=LocalArtifactStore(Path(p['cas'])),workspace=Path(p['workspace']),staging_root=Path(p['staging']),state_root=Path(p['state']))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", driver],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(
        json.dumps(
            {
                "url": client.base_url,
                "worker": client.worker_id,
                "session": client.session,
                "token": client.grant_token,
                "ca": str(client.ca_path),
                "pin": client.tls_fingerprint,
                "cas": str(kwargs["artifacts"].root),
                "workspace": str(kwargs["workspace"]),
                "staging": str(kwargs["staging_root"]),
                "state": str(kwargs["state_root"]),
            }
        ).encode()
    )
    process.stdin.close()
    try:
        deadline = time.monotonic() + 15
        while not (kwargs["workspace"] / "started").exists() and time.monotonic() < deadline:
            assert process.poll() is None, "Worker exited before its actual task started"
            time.sleep(0.05)
        assert (kwargs["workspace"] / "started").exists()
        process.kill()
        process.wait(timeout=5)
        # Restart remains passive while the existing child is still running.
        assert _recover(client, world, kwargs).disposition == "running"
        _lifecycle(
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id),
            world.request,
            "run.cancel.requested",
            {"reasonCode": "user-requested"},
        )
        result = _recover(client, world, kwargs)
        assert result.disposition == "cancelled"
        assert _recover(client, world, kwargs) == result
        identity = json.loads(next(kwargs["state_root"].glob("*.identity")).read_text())
        assert observe_process_group(identity["pgid"], identity["pid"]) == OBSERVATION_EXITED
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process.stderr.close()
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("overlap", ["cas", "workspace", "staging"])
def test_executor_refuses_overlapping_state_before_network(tmp_path, monkeypatch, overlap):  # type: ignore[no-untyped-def]
    _, plane, server, client, kwargs = _setup(tmp_path)
    kwargs["state_root"] = (
        kwargs["artifacts"].root
        if overlap == "cas"
        else kwargs["workspace" if overlap == "workspace" else "staging_root"]
    )
    monkeypatch.setattr(
        WorkerClient,
        "fetch_native_material_index",
        lambda *a: pytest.fail("unsafe roots fetched metadata"),
    )
    try:
        with pytest.raises(WorkerError) as exc:
            execute_remote_native(client, **kwargs)
        assert exc.value.code == "native-state-invalid"
    finally:
        server.stop()
        plane.store.close()


def test_actual_wire_fresh_claim_reaches_fixed_child_boundary(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    _, plane, server, client, kwargs = _setup(tmp_path)
    calls = []

    def refuse_child(*a, **k):  # type: ignore[no-untyped-def]
        calls.append(a[0])
        raise WorkerError("fixture reached fixed child boundary", code="fixture-boundary")

    monkeypatch.setattr(native_executor.subprocess, "Popen", refuse_child)
    try:
        with pytest.raises(WorkerError, match="fixture reached fixed child boundary"):
            execute_remote_native(client, **kwargs)
        assert len(calls) == 1 and calls[0][1:3] == ["-I", "-B"]
        assert plane.rebuild().grant("grant.native").consumed_lease_id is not None
    finally:
        server.stop()
        plane.store.close()
