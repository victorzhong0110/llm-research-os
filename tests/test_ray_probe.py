"""Bounded Ray API fixtures verify adapter semantics, not real cluster acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_research_os.workers.ray_probe import (
    _CPU_SOURCE,
    RAY_PROBE_VERSION,
    RayJobsProbe,
    RayProbeError,
    _probe_lock,
    _result,
)

TOKEN = "a" * 64


@pytest.fixture
def backend(tmp_path: Path):  # type: ignore[no-untyped-def]
    state = tmp_path / "probe-state"
    state.mkdir(mode=0o700)
    jobs = {}
    calls = []
    controls = {"version": RAY_PROBE_VERSION, "lose": False, "refuse": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # type: ignore[no-untyped-def]
            pass

        def do_GET(self):  # type: ignore[no-untyped-def]
            calls.append(("GET", self.path))
            if self.headers["Authorization"] != "Bearer " + TOKEN:
                self.reply(401, {})
            elif self.path == "/api/version":
                self.reply(200, {"ray_version": controls["version"], "version": "4"})
            else:
                ident = self.path.split("/")[3]
                job = jobs.get(ident)
                if job is None:
                    self.reply(404, {})
                elif self.path.endswith("/logs"):
                    self.reply(200, {"logs": job["logs"]})
                else:
                    self.reply(200, {key: value for key, value in job.items() if key != "logs"})

        def do_POST(self):  # type: ignore[no-untyped-def]
            calls.append(("POST", self.path))
            if self.headers["Authorization"] != "Bearer " + TOKEN:
                self.reply(401, {})
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/stop"):
                self.reply(200, {"stopped": True})
            elif controls["refuse"]:
                self.reply(400, {})
            else:
                ident = body["submission_id"]
                jobs[ident] = {**body, "status": "RUNNING", "logs": ""}
                if controls["lose"]:
                    self.connection.close()
                else:
                    self.reply(200, {"submission_id": ident})

        def reply(self, status, body):  # type: ignore[no-untyped-def]
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RayJobsProbe(f"http://127.0.0.1:{server.server_port}", TOKEN)
    yield client, state, jobs, calls, controls
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_probe_replay_and_cluster_history_loss_never_resubmit(backend):  # type: ignore[no-untyped-def]
    client, state, jobs, calls, _ = backend
    result = client.submit_once(name="cpu-1", device="cpu", state_root=state)
    assert result.backend_status == "RUNNING"
    assert result.project_task_starts == result.lifecycle_facts_appended == 0
    job = jobs[result.submission_id]
    assert job["entrypoint_num_gpus"] == 0 and job["entrypoint_num_cpus"] == 1
    assert job["runtime_env"] == {}  # no package installation or arbitrary environment
    assert TOKEN not in next(state.glob("*.intent")).read_text()
    assert TOKEN not in repr(client)
    before = len([call for call in calls if call == ("POST", "/api/jobs/")])
    assert replace(client).submit_once(name="cpu-1", device="cpu", state_root=state) == result
    jobs.clear()
    assert (
        client.submit_once(name="cpu-1", device="cpu", state_root=state).backend_status == "UNKNOWN"
    )
    assert len([call for call in calls if call == ("POST", "/api/jobs/")]) == before == 1


@pytest.mark.parametrize("fault", ["lose", "refuse"])
def test_ambiguous_or_refused_submit_retains_intent_and_never_retries(backend, fault):  # type: ignore[no-untyped-def]
    client, state, _, calls, controls = backend
    controls[fault] = True
    result = client.submit_once(name="cpu-2", device="cpu", state_root=state)
    assert result.backend_status == "UNKNOWN"
    assert next(state.glob("*.intent")).exists()
    controls[fault] = False
    client.submit_once(name="cpu-2", device="cpu", state_root=state)
    assert calls.count(("POST", "/api/jobs/")) == 1


def test_probe_stop_ack_is_separate_from_backend_status(backend):  # type: ignore[no-untyped-def]
    client, state, _, _, _ = backend
    client.submit_once(name="stop", device="cpu", state_root=state)
    assert client.request_stop(name="stop", device="cpu", state_root=state) is True
    assert client.observe(name="stop", device="cpu", state_root=state).backend_status == "RUNNING"


@pytest.mark.parametrize("fault", ["device", "token", "intent", "metadata", "entrypoint", "env"])
def test_changed_scope_or_corruption_refuses_without_new_submission(backend, fault):  # type: ignore[no-untyped-def]
    client, state, jobs, calls, _ = backend
    result = client.submit_once(name="bound", device="cpu", state_root=state)
    device = "cpu"
    if fault == "device":
        device = "cuda"
    elif fault == "token":
        client = replace(client, token="b" * 64)
    elif fault == "intent":
        next(state.glob("*.intent")).write_bytes(b"changed")
    elif fault == "metadata":
        jobs[result.submission_id]["metadata"] = {}
    elif fault == "entrypoint":
        jobs[result.submission_id]["entrypoint"] = "arbitrary"
    else:
        jobs[result.submission_id]["runtime_env"] = {"pip": ["unapproved"]}
    with pytest.raises(RayProbeError, match="binding differs"):
        client.submit_once(name="bound", device=device, state_root=state)
    assert calls.count(("POST", "/api/jobs/")) == 1


@pytest.mark.parametrize("fault", ["version", "collision", "public-root", "busy"])
def test_probe_refusals_precede_submission(backend, fault):  # type: ignore[no-untyped-def]
    client, state, jobs, calls, controls = backend
    lock = None
    binding = client._binding("refuse", "cpu")
    if fault == "version":
        controls["version"] = "0.0.0"
    elif fault == "collision":
        jobs[binding["submission_id"]] = {"status": "RUNNING", "logs": ""}
    elif fault == "public-root":
        state.chmod(0o755)
    else:
        lock = _probe_lock(state, binding["submission_id"])
        lock.__enter__()
    try:
        with pytest.raises(RayProbeError):
            client.submit_once(name="refuse", device="cpu", state_root=state)
        assert not list(state.glob("*.intent"))
        assert calls.count(("POST", "/api/jobs/")) == 0
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


def test_cpu_source_really_computes_and_result_requires_one_exact_marker(tmp_path: Path) -> None:
    source = tmp_path / "probe.py"
    source.write_text(_CPU_SOURCE)
    result = subprocess.run([sys.executable, "-I", str(source)], capture_output=True, check=True)
    logs = result.stdout.decode()
    assert _result(logs, "cpu")["value"] == 85344
    for bad in (logs + logs, "", logs.replace("85344", "85345"), logs.replace('"cpu"', '"cuda"')):
        with pytest.raises(RayProbeError, match=r"marker|invalid"):
            _result(bad, "cpu")


def test_cuda_probe_binds_one_gpu_and_verifies_actual_compute_marker(backend):  # type: ignore[no-untyped-def]
    client, state, jobs, _, _ = backend
    result = client.submit_once(name="cuda", device="cuda", state_root=state)
    job = jobs[result.submission_id]
    assert job["entrypoint_num_gpus"] == 1
    job["status"] = "SUCCEEDED"
    job["logs"] = (
        'RESEARCHOS_RAY_PROBE={"device":"cuda","value":32768.0,"python":"3.12","platform":"Linux","torch":"test","cuda":"test","gpu":"fixture"}'
    )
    assert client.observe(name="cuda", device="cuda", state_root=state).result["value"] == 32768
    # This is protocol fixture validation, not GPU runtime evidence.
    job["logs"] = "exit 0"
    with pytest.raises(RayProbeError, match="marker"):
        client.observe(name="cuda", device="cuda", state_root=state)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:8265",
        "http://localhost:8265",
        "https://127.0.0.1:8265",
        "http://127.0.0.1:8265/path",
        "http://127.0.0.1:8265?x=1",
    ],
)
def test_probe_rejects_nonlocal_or_ambiguous_endpoints(endpoint: str) -> None:
    with pytest.raises(RayProbeError, match="loopback"):
        RayJobsProbe(endpoint, TOKEN)


@pytest.mark.parametrize("fault", ["missing", "symlink", "hardlink", "oversized"])
def test_probe_state_refuses_missing_or_unsafe_intent(backend, fault):  # type: ignore[no-untyped-def]
    client, state, _, calls, _ = backend
    if fault == "missing":
        with pytest.raises(RayProbeError, match="missing"):
            client.observe(name="state", device="cpu", state_root=state)
        with pytest.raises(RayProbeError, match="missing"):
            client.request_stop(name="state", device="cpu", state_root=state)
        return
    client.submit_once(name="state", device="cpu", state_root=state)
    intent = next(state.glob("*.intent"))
    if fault == "symlink":
        victim = state / "victim"
        victim.write_bytes(b"preserve")
        intent.unlink()
        intent.symlink_to(victim)
    elif fault == "hardlink":
        (state / "alias").hardlink_to(intent)
    else:
        intent.write_bytes(b"x" * 4097)
    with pytest.raises((RayProbeError, OSError)):
        client.submit_once(name="state", device="cpu", state_root=state)
    assert calls.count(("POST", "/api/jobs/")) == 1


@pytest.mark.parametrize(
    "fault", ["large", "short", "encoding", "invalid", "nonobject", "disconnect"]
)
def test_ray_transport_is_bounded_single_attempt_and_always_closes(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from llm_research_os.workers import ray_probe

    calls = []
    reads = []
    closed = []

    class Response:
        status = 200

        def getheader(self, name):  # type: ignore[no-untyped-def]
            if name == "Content-Length":
                return "20000" if fault == "large" else "2"
            if name == "Content-Encoding" and fault == "encoding":
                return "gzip"
            return None

        def read(self, limit):  # type: ignore[no-untyped-def]
            reads.append(limit)
            return (
                b"{"
                if fault == "short"
                else b"xx"
                if fault == "invalid"
                else b"[]"
                if fault == "nonobject"
                else b"{}"
            )

    class Connection:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["timeout"] == 10

        def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(1)
            if fault == "disconnect":
                raise OSError(TOKEN)

        def getresponse(self):  # type: ignore[no-untyped-def]
            return Response()

        def close(self):  # type: ignore[no-untyped-def]
            closed.append(1)

    monkeypatch.setattr(ray_probe, "HTTPConnection", Connection)
    with pytest.raises(RayProbeError, match="unavailable") as exc:
        RayJobsProbe("http://127.0.0.1:8265", TOKEN)._call("GET", "/api/version")
    assert TOKEN not in str(exc.value)
    assert len(calls) == len(closed) == 1
    assert reads == ([] if fault in {"large", "encoding", "disconnect"} else [16385])


def test_unknown_probe_cannot_emit_stop_and_nonstring_status_refuses(backend):  # type: ignore[no-untyped-def]
    client, state, jobs, calls, _ = backend
    result = client.submit_once(name="unknown", device="cpu", state_root=state)
    jobs[result.submission_id]["status"] = []
    with pytest.raises(RayProbeError, match="binding"):
        client.observe(name="unknown", device="cpu", state_root=state)
    jobs.clear()
    assert client.request_stop(name="unknown", device="cpu", state_root=state) is False
    assert not any(call[1].endswith("/stop") for call in calls)
