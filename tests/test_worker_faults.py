from __future__ import annotations

import errno
import json
import sys
from datetime import timedelta
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlparse

import pytest
from test_worker_protocol import (
    HMAC_KEY,
    NOW,
    PROJECT,
    SOURCE,
    FrozenClock,
    _grant_and_queue,
    _plane,
)

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage import EventStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerCallError, WorkerError, WorkerSandboxError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.sandbox import SandboxDisposition, execute_python_brick
from llm_research_os.workers.tokens import issue_worker_session

ROOT = Path(__file__).parents[1]
SLEEP_BRICK = """import sys, time
time.sleep(30)
sys.exit(2)
"""
KILL_BRICK = """import os, signal
os.kill(os.getpid(), signal.SIGKILL)
"""
FAIL_BRICK = """import sys
sys.exit(2)
"""


def test_sandbox_timeout_is_unknown_not_failed(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "sleep.py"
    brick.write_text(SLEEP_BRICK, encoding="utf-8")
    digest = artifacts.put(brick).digest
    result = execute_python_brick(artifacts, digest, timeout_seconds=1)
    assert result.disposition is SandboxDisposition.UNKNOWN
    assert result.reason_code == "worker.process.timeout"
    assert result.result_digest is None


def test_expired_lease_cannot_complete(tmp_path: Path) -> None:
    clock = FrozenClock(NOW)
    store, artifacts, plane, image = _plane(tmp_path, clock=clock, lease_seconds=1)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        clock.instant = NOW + timedelta(seconds=120)
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id=claimed.lease_id,
                result_digest=result.result_digest,
                artifact_digest=record.digest,
            )
        assert captured.value.code == "lease-expired"
        expired = plane.expire_lease(lease_id=claimed.lease_id)
        assert expired.event.type == "work.lease.expired"
    finally:
        store.__exit__(None, None, None)


def test_heartbeat_does_not_append_facts(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        before = store.last_sequence()
        session = issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1")
        for _ in range(200):
            plane.heartbeat(
                worker_id="worker.loopback.1",
                session=session,
                lease_id=claimed.lease_id,
            )
        assert store.last_sequence() == before
    finally:
        store.__exit__(None, None, None)


def test_missing_artifact_after_upload_failure_cannot_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None

        def _enospc(_self: LocalArtifactStore, payload: bytes) -> object:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(LocalArtifactStore, "put_bytes", _enospc)
        with pytest.raises(OSError, match="No space left on device") as disk:
            artifacts.put_bytes(result.stdout)
        assert disk.value.errno == errno.ENOSPC
        with pytest.raises(WorkerCallError) as captured:
            plane.complete(
                worker_id="worker.loopback.1",
                grant_token=token,
                lease_id=claimed.lease_id,
                result_digest=result.result_digest,
                artifact_digest="sha256:" + ("0" * 64),
            )
        assert captured.value.code == "artifact-missing"
        lease = plane.rebuild().lease(claimed.lease_id)
        assert lease is not None
        assert lease.status == "leased"
    finally:
        store.__exit__(None, None, None)


def test_control_plane_restart_reuses_hmac_key(tmp_path: Path) -> None:
    store, artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        restarted = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        resumed = restarted.poll(worker_id="worker.loopback.1", grant_token=token)
        assert resumed is not None
        assert resumed.lease_id == claimed.lease_id
        result = execute_python_brick(artifacts, image)
        assert result.result_digest is not None
        record = artifacts.put_bytes(result.stdout)
        stored = restarted.complete(
            worker_id="worker.loopback.1",
            grant_token=token,
            lease_id=claimed.lease_id,
            result_digest=result.result_digest,
            artifact_digest=record.digest,
        )
        assert stored.event.type == "work.completed"
    finally:
        store.__exit__(None, None, None)


def test_http_loopback_poll_execute_complete(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    image = artifacts.put(ROOT / "examples" / "m2-checkpoint" / "brick.py")
    with EventStore(database) as store:
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
            time="2026-09-07T12:00:00Z",
        )
        token = _grant_and_queue(plane, image.digest)
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
        )
        receipt = client.run_once(artifacts)
        assert receipt is not None
        assert receipt["type"] == "work.completed"
    finally:
        server.stop()
    with EventStore(database, require_existing=True) as store:
        types = [item.event.type for item in store.read_events(limit=40)]
        assert "work.completed" in types
        assert types.count("work.leased") == 1


def test_killed_sandbox_process_is_unknown_not_failed(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("SIGKILL is a POSIX sandbox outcome")
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "kill.py"
    brick.write_text(KILL_BRICK, encoding="utf-8")
    digest = artifacts.put(brick).digest
    result = execute_python_brick(artifacts, digest)
    assert result.disposition is SandboxDisposition.UNKNOWN
    assert result.reason_code == "worker.process.lost"
    assert result.result_digest is None


def test_nonzero_brick_exit_is_failed_not_unknown(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "fail.py"
    brick.write_text(FAIL_BRICK, encoding="utf-8")
    digest = artifacts.put(brick).digest
    result = execute_python_brick(artifacts, digest)
    assert result.disposition is SandboxDisposition.FAILED
    assert result.reason_code == "worker.brick.failed"


def test_disconnect_before_complete_leaves_lease_open(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    image = artifacts.put(ROOT / "examples" / "m2-checkpoint" / "brick.py")
    with EventStore(database) as store:
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
            time="2026-09-07T12:00:00Z",
        )
        token = _grant_and_queue(plane, image.digest)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        client = WorkerClient(
            base_url=server.base_url,
            worker_id="worker.loopback.1",
            session=server.session_for("worker.loopback.1"),
            grant_token=token,
        )
    finally:
        server.stop()
    with pytest.raises(WorkerError) as captured:
        client.complete(
            lease_id=claimed.lease_id,
            result_digest="sha256:" + ("0" * 64),
            artifact_digest="sha256:" + ("1" * 64),
        )
    assert captured.value.code == "http-disconnect"
    with EventStore(database, require_existing=True) as store:
        types = [item.event.type for item in store.read_events(limit=40)]
        assert "work.leased" in types
        assert "work.completed" not in types


def test_http_heartbeat_and_unknown_path_do_not_append_facts(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    image = artifacts.put(ROOT / "examples" / "m2-checkpoint" / "brick.py")
    with EventStore(database) as store:
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
            time="2026-09-07T12:00:00Z",
        )
        token = _grant_and_queue(plane, image.digest)
        claimed = plane.poll(worker_id="worker.loopback.1", grant_token=token)
        assert claimed is not None
        before = store.last_sequence()
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        parsed = urlparse(server.base_url)
        body = json.dumps(
            {"workerId": "worker.loopback.1", "leaseId": claimed.lease_id},
            ensure_ascii=True,
        ).encode("utf-8")
        connection = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            connection.request(
                "POST",
                "/v0alpha1/work/heartbeat",
                body=body,
                headers={
                    "Authorization": (f"Bearer {server.session_for('worker.loopback.1')}"),
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            response.read()
            assert response.status == 204
        finally:
            connection.close()
        missing = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            missing.request("POST", "/v0alpha1/missing", body=b"{}", headers={})
            missing_response = missing.getresponse()
            missing_response.read()
            assert missing_response.status == 404
        finally:
            missing.close()
    finally:
        server.stop()
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == before


def test_sandbox_rejects_invalid_timeout_and_bad_reports(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    brick = tmp_path / "plain.py"
    brick.write_text("print('not-json')\n", encoding="utf-8")
    digest = artifacts.put(brick).digest
    with pytest.raises(WorkerSandboxError) as captured:
        execute_python_brick(artifacts, digest, timeout_seconds=0)
    assert captured.value.code == "sandbox-timeout"
    plain = execute_python_brick(artifacts, digest)
    assert plain.disposition is SandboxDisposition.FAILED
    assert plain.reason_code == "worker.brick.invalid-json"
    report = tmp_path / "report.py"
    report.write_text(
        "import json, sys; json.dump({'kind': 'nope'}, sys.stdout)\n",
        encoding="utf-8",
    )
    bad_kind = execute_python_brick(artifacts, artifacts.put(report).digest)
    assert bad_kind.reason_code == "worker.brick.invalid-report"
    failed = tmp_path / "failed.py"
    failed.write_text(
        "import json, sys; json.dump({'kind': 'PythonBrickReport', 'status': 'err'}, sys.stdout)\n",
        encoding="utf-8",
    )
    bad_status = execute_python_brick(artifacts, artifacts.put(failed).digest)
    assert bad_status.reason_code == "worker.brick.failed"


def test_http_rejects_missing_session_and_invalid_wait(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    with EventStore(database):
        pass
    server = LoopbackWorkerServer(
        database,
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=PROJECT,
        source=SOURCE,
    )
    try:
        server.start()
        parsed = urlparse(server.base_url)
        body = json.dumps(
            {"workerId": "worker.loopback.1", "grantToken": "rg1.x.y", "waitSeconds": 0},
            ensure_ascii=True,
        ).encode("utf-8")
        missing = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            missing.request(
                "POST",
                "/v0alpha1/work/poll",
                body=body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
            response = missing.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 401
            assert payload["code"] == "worker-session-missing"
        finally:
            missing.close()
        wait = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
        try:
            wait_body = json.dumps(
                {
                    "workerId": "worker.loopback.1",
                    "grantToken": "rg1.x.y",
                    "waitSeconds": 9,
                },
                ensure_ascii=True,
            ).encode("utf-8")
            wait.request(
                "POST",
                "/v0alpha1/work/poll",
                body=wait_body,
                headers={
                    "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(wait_body)),
                },
            )
            wait_response = wait.getresponse()
            wait_payload = json.loads(wait_response.read().decode("utf-8"))
            assert wait_response.status == 400
            assert wait_payload["code"] == "http-invalid"
        finally:
            wait.close()
    finally:
        server.stop()
