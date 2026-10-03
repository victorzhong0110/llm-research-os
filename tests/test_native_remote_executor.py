"""Actual CPU child, independent Worker CAS, TLS barrier and conservative recovery."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace

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
        monkeypatch.setattr(
            native_executor.subprocess,
            "Popen",
            lambda *a, **k: pytest.fail("recovery launched a child"),
        )
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
        monkeypatch.setattr(
            native_executor.subprocess, "Popen", lambda *a, **k: pytest.fail("recovery relaunched")
        )
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
