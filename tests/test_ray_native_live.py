"""Designated real Ray CPU jobs over the reviewed native TLS Worker boundary."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from dataclasses import replace

import pytest
from test_native_remote_executor import _setup, _snapshot
from test_native_remote_executor import live_host as live_host
from test_native_reviewed_preparation import PROJECT
from test_native_worker_cli import _credential

from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.ray_native_job import RayNativeJob
from llm_research_os.workers.ray_probe import RAY_PROBE_VERSION, RayJobsProbe, RayProbeError
from llm_research_os.workers.supervise import OBSERVATION_EXITED, observe_process_group

pytestmark = [pytest.mark.ray_native_live, pytest.mark.usefixtures("live_host")]
_RAY_TOKEN = secrets.token_hex(32)


@pytest.fixture
def ray_backend():  # type: ignore[no-untyped-def]
    if os.environ.get("RESEARCHOS_RAY_NATIVE_REQUIRED") != "1":
        pytest.skip("optional compute gate requires RESEARCHOS_RAY_NATIVE_REQUIRED=1")
    # The designated gate must fail on missing Ray; no importorskip or mocked OS.
    os.environ["RAY_USAGE_STATS_ENABLED"] = "0"
    os.environ["RAY_AUTH_MODE"] = "token"
    os.environ["RAY_AUTH_TOKEN"] = _RAY_TOKEN
    os.environ["RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER"] = "0"
    os.environ["RAY_gcs_rpc_server_connect_timeout_s"] = "5"  # noqa: SIM112 - Ray exact key
    # Ray caches auth mode/token at import; configure before the first import.
    import ray

    assert ray.__version__ == RAY_PROBE_VERSION
    assert not ray.is_initialized(), "integration may only start its own cluster"
    with tempfile.TemporaryDirectory(prefix="rn-", dir="/tmp") as scratch:
        try:
            context = ray.init(
                address="local",
                num_cpus=1,
                include_dashboard=True,
                dashboard_host="127.0.0.1",
                dashboard_port=0,
                _node_ip_address="127.0.0.1",
                _temp_dir=scratch,
                object_store_memory=80 * 1024 * 1024,
                _memory=256 * 1024 * 1024,
                logging_level="ERROR",
            )
            assert len([n for n in ray.nodes() if n["Alive"]]) == 1
            yield RayJobsProbe("http://" + context.dashboard_url, os.environ["RAY_AUTH_TOKEN"])
        finally:
            ray.shutdown()  # no reuse or global ray stop


def _job(tmp_path, backend, world, client, kwargs):  # type: ignore[no-untyped-def]
    root = kwargs["workspace"].parent / "ray-state"
    root.mkdir(mode=0o700)
    return RayNativeJob(
        backend,
        world.request,
        _credential(client, kwargs),
        kwargs["artifacts"].root,
        kwargs["workspace"],
        kwargs["staging_root"],
        kwargs["state_root"],
        root,
    )


def _wait(job):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 60
    result = job.observe()
    while result.backend_status in {"PENDING", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(0.25)
        result = job.observe()
    return result


@pytest.mark.parametrize("lost_ack", [False, True])
def test_actual_ray_cpu_result_and_saved_receipt_replay(
    tmp_path, ray_backend, monkeypatch, lost_ack
):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    job = _job(tmp_path, ray_backend, world, client, kwargs)
    post_calls = []
    original = RayJobsProbe._call

    def lose_once(self, method, path, body=None, **extra):  # type: ignore[no-untyped-def]
        response = original(self, method, path, body, **extra)
        if method == "POST" and path == "/api/jobs/":
            post_calls.append(1)
            if lost_ack:
                raise RayProbeError("fixture discarded real POST acknowledgement")
        return response

    monkeypatch.setattr(RayJobsProbe, "_call", lose_once)
    try:
        submitted = job.submit_once()
        if lost_ack:
            assert submitted.backend_status == "UNKNOWN"
        replay = replace(job).submit_once()
        assert replay.submission_id == submitted.submission_id
        assert _wait(job).backend_status == "SUCCEEDED"
        result = job.reconcile()
        assert result.disposition == "completed" and result.receipt is not None
        assert result.output == {
            "rows": 1,
            "sha256": "815853a11c4f2e2e5355f547308cd7c6054f85ba6a324b2c37beb8edbec1fb93",
        }
        assert _snapshot(world, plane).status.value == "completed"
        before = plane.store.last_sequence()
        assert replace(job).reconcile() == result
        assert plane.store.last_sequence() == before and len(post_calls) == 1
        assert kwargs["artifacts"].root != plane.artifacts.root
        text = "".join(p.read_text() for p in job.ray_state_root.iterdir() if p.stat().st_size)
        assert (
            client.grant_token not in text
            and client.session not in text
            and world.hmac_key.hex() not in text
        )
        assert not list(job.ray_state_root.rglob("*.sqlite"))
    finally:
        server.stop()
        plane.store.close()


def test_ray_stop_status_requires_controller_cancel_and_actual_group_observation(
    tmp_path, ray_backend
):  # type: ignore[no-untyped-def]
    source = (
        b"import time\nfrom pathlib import Path\ndef main():\n"
        b" Path('started').write_text('yes')\n time.sleep(30)\n return {}\n"
    )
    world, plane, server, client, kwargs = _setup(tmp_path, source)
    job = _job(tmp_path, ray_backend, world, client, kwargs)
    try:
        result = job.submit_once()
        deadline = time.monotonic() + 60
        while not (kwargs["workspace"] / "started").exists() and time.monotonic() < deadline:
            assert job.observe().backend_status in {"PENDING", "RUNNING"}
            time.sleep(0.1)
        assert (kwargs["workspace"] / "started").exists()
        status, response = ray_backend._call(
            "POST", "/api/jobs/" + result.submission_id + "/stop", {}
        )
        assert status == 200 and response["stopped"] is True
        assert _wait(job).backend_status == "STOPPED"
        assert _snapshot(world, plane).status.value == "running"  # vendor ack appended no Run fact
        _lifecycle(
            RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id),
            world.request,
            "run.cancel.requested",
            {"reasonCode": "user-requested"},
        )
        deadline = time.monotonic() + 10
        while True:
            try:
                observed = job.reconcile()
                break
            except WorkerError as exc:
                assert exc.code == "native-state-busy" and time.monotonic() < deadline
                time.sleep(0.1)
        assert observed.disposition == "cancelled"
        identity = json.loads(next(kwargs["state_root"].glob("*.identity")).read_text())
        assert observe_process_group(identity["pgid"], identity["pid"]) == OBSERVATION_EXITED
        assert _snapshot(world, plane).status.value == "cancelled"
        assert job.reconcile() == observed
    finally:
        server.stop()
        plane.store.close()
