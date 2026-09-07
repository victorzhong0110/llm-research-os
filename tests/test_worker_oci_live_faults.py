from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from test_worker_oci import (
    AUTH_EVENT_ID,
    HMAC_KEY,
    NOW,
    OCI_CORPUS,
    PROJECT,
    SOURCE,
    FrozenClock,
    _build_local_python_image,
    _require_oci_backend,
)
from test_worker_recovery import ATTEMPT_ID, RUN_ID, _identities, _request_run_cancel

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization import PlanAuthorizationPolicy
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.models import AttemptStatus, RunStatus
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.workers.binding import brick_execution_digest
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerCallError, WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.models import IMAGE_MEDIA_OCI_IMAGE, WORKER_RUNTIME_OCI_CONTAINER
from llm_research_os.workers.oci import OciBackend
from llm_research_os.workers.plane import WorkerPlane
from llm_research_os.workers.recovery import reconcile_worker_run
from llm_research_os.workers.runtime import WorkerRuntime
from llm_research_os.workers.supervise import (
    UNOBSERVED,
    ExecutionIdentity,
    inspect_container_running,
    load_execution_identity,
    observe_and_stop,
    remove_oci_container,
)

WORKER_ID = "worker.oci.1"
GRANT_ID = "grant.oci.live.1"
LEASE_ID = "lease.grant.oci.live.1"
OCI_LAUNCH_CONFIG: dict[str, object] = {"network": "denied", "wallTimeSeconds": 20}
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


@pytest.fixture(scope="module")
def oci_live_runtime(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[OciBackend, str]]:
    backend = _require_oci_backend()
    image = _build_local_python_image(backend, tmp_path_factory.mktemp("oci-live-image"))
    try:
        yield backend, image
    finally:
        _reap_ancestor_containers(backend, image)


def _reap_ancestor_containers(backend: OciBackend, image: str) -> None:
    listed = subprocess.run(
        [backend.executable, "ps", "-aq", "--filter", f"ancestor={image}"],
        check=False,
        capture_output=True,
        timeout=10,
    )
    if listed.returncode != 0:
        return
    for container_id in listed.stdout.decode("utf-8", errors="replace").split():
        if container_id:
            remove_oci_container(backend.executable, container_id)


def _oci_spec(image_digest: str, brick_digest: str, config: Mapping[str, object]) -> ResearchSpec:
    payload = load_spec(OCI_CORPUS / "spec.yaml").model_dump(mode="json", by_alias=True)
    node = payload["workflows"][0]["graph"]["nodes"][0]["config"]
    node["imageDigest"] = image_digest
    node["config"] = dict(config)
    node["inputs"]["brickDigest"] = brick_digest
    return ResearchSpec.model_validate(payload)


def _record_oci_live_authorization(store: EventStore, spec: ResearchSpec) -> tuple[str, str]:
    registry = build_registry([OCI_CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.oci",),
    )
    result = authorize_plan(report, policy)
    document = snapshot_json_document(
        load_document(OCI_CORPUS / "authorization-event.json", reject_symlinks=True)
    )
    assert type(document) is dict
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    recorded = record_plan_authorization_event(
        store,
        report,
        policy,
        validate_plan_authorization_event_request_document(document),
    )
    return recorded.stored.event.id, recorded.stored.event.sequence


def _start_oci_runtime(store: EventStore, spec: ResearchSpec) -> tuple[WorkerRuntime, object]:
    registry = build_registry([OCI_CORPUS / "block.json"])
    report = TrustedKernel(registry).dry_run(spec, workflow_id=spec.workflows[0].id)
    assert report.digests.plan is not None
    policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=("execute.oci",),
    )
    authorization = authorize_plan(report, policy)
    stored = store.get_event(AUTH_EVENT_ID)
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


def _queue_oci_live(
    tmp_path: Path,
    image_digest: str,
    brick: str,
    *,
    config: Mapping[str, object] | None = None,
) -> tuple[Path, LocalArtifactStore, Path, str, ResearchSpec]:
    launch = dict(config) if config is not None else dict(OCI_LAUNCH_CONFIG)
    database = tmp_path / "research.db"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    path = tmp_path / "live-oci-brick.py"
    path.write_text(brick, encoding="utf-8")
    stored = artifacts.put(path)
    spec = _oci_spec(image_digest, stored.digest, launch)
    registry = build_registry([OCI_CORPUS / "block.json"])
    identity_dir = tmp_path / "identities"
    with EventStore(database) as store:
        _record_oci_live_authorization(store, spec)
        _start_oci_runtime(store, spec)
        plane = WorkerPlane(
            store,
            artifacts=artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        plane.register(
            worker_id=WORKER_ID,
            actor_id="researcher.alice",
            event_id="evt.worker.registered.oci.live.1",
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
        )
        stored_auth = plane.store.get_event(AUTH_EVENT_ID)
        assert stored_auth is not None
        config_digest = brick_execution_digest(
            image_digest=image_digest,
            config=launch,
            inputs={"brickDigest": stored.digest},
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
        )
        plane.record_grant(
            grant_id=GRANT_ID,
            worker_id=WORKER_ID,
            task_id="task.oci",
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            nonce="nonce.oci.live.1",
            expires_at="2099-01-01T00:00:00Z",
            actor_id="researcher.alice",
            event_id="evt.grant.recorded.oci.live.1",
            authorization_event_id=stored_auth.event.id,
            authorization_sequence=stored_auth.event.sequence,
            image_digest=image_digest,
            config_digest=config_digest,
            spec=spec,
            registry=registry,
            time="2026-09-07T12:00:00Z",
            workflow_id="workflow.oci",
        )
        plane.enqueue(
            task_id="task.oci",
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            image_digest=image_digest,
            event_id="evt.work.queued.task.oci.live",
            config=dict(launch),
            inputs={"brickDigest": stored.digest},
            image_media_type=IMAGE_MEDIA_OCI_IMAGE,
            runtime=WORKER_RUNTIME_OCI_CONTAINER,
            time="2026-09-07T12:00:00Z",
        )
        token = plane.issue_token(GRANT_ID)
    return database, artifacts, identity_dir, token, spec


def _server(
    database: Path, artifacts: LocalArtifactStore, *, port: int = 0
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


def _client(server: LoopbackWorkerServer, token: str, identity_dir: Path) -> WorkerClient:
    return WorkerClient(
        base_url=server.base_url,
        worker_id=WORKER_ID,
        session=server.session_for(WORKER_ID),
        grant_token=token,
        identity_dir=identity_dir,
        timeout_seconds=30,
    )


def _wait_oci_identity(identity_dir: Path) -> ExecutionIdentity:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        loaded = load_execution_identity(identity_dir, LEASE_ID)
        if loaded is not None and loaded.container_id:
            return loaded
        time.sleep(0.05)
    pytest.fail("OCI execution identity was not recorded")


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
) -> subprocess.Popen[bytes]:
    script = tmp_path / "live-oci-worker.py"
    script.write_text(_WORKER_MAIN, encoding="utf-8")
    config = tmp_path / "live-oci-worker.json"
    error_path = tmp_path / "live-oci-worker-error.txt"
    config.write_text(
        json.dumps(
            {
                "baseUrl": server.base_url,
                "workerId": WORKER_ID,
                "session": server.session_for(WORKER_ID),
                "grantToken": token,
                "identityDir": str(identity_dir),
                "artifacts": str(artifacts.root),
                "timeoutSeconds": 30,
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


def _count_oci_spawns(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    from llm_research_os.workers import client as client_mod

    original = client_mod.execute_oci_python_brick
    spawns = {"n": 0}

    def _count(*args: object, **kwargs: object) -> object:
        spawns["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client_mod, "execute_oci_python_brick", _count)
    return spawns


def _cleanup_identity(identity_dir: Path) -> None:
    leftover = load_execution_identity(identity_dir, LEASE_ID)
    if leftover is not None:
        observe_and_stop(leftover)


def _reconcile_cancelled(database: Path, artifacts: LocalArtifactStore, spec: ResearchSpec) -> None:
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
            report=TrustedKernel(build_registry([OCI_CORPUS / "block.json"])).dry_run(
                spec, workflow_id=spec.workflows[0].id
            ),
            revision=1,
        )
        assert snapshot.status is RunStatus.CANCELLED
        assert snapshot.attempts[0].status is AttemptStatus.CANCELLED


@pytest.mark.oci_live
def test_live_oci_running_cancel_stops_container_then_reconciles(
    tmp_path: Path, oci_live_runtime: tuple[OciBackend, str]
) -> None:
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
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
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.live")
        thread.join(timeout=15)
        assert thread.is_alive() is False
        assert inspect_container_running(backend.executable, identity.container_id) is not True
    finally:
        _cleanup_identity(identity_dir)
        server.stop()
    assert captured and captured[0].code == "cancel-observed"
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types
    _reconcile_cancelled(database, artifacts, spec)


@pytest.mark.oci_live
def test_live_oci_timeout_removes_container_stays_unknown(
    tmp_path: Path,
    oci_live_runtime: tuple[OciBackend, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, spec = _queue_oci_live(
        tmp_path,
        image,
        SLEEP_BRICK,
        config={"network": "denied", "wallTimeSeconds": 2},
    )
    spawns = _count_oci_spawns(monkeypatch)
    container_ids: list[str] = []
    server = _server(database, artifacts)
    try:
        server.start()

        def _capture_identity() -> None:
            identity = _wait_oci_identity(identity_dir)
            if identity.container_id is not None:
                container_ids.append(identity.container_id)

        watcher = threading.Thread(target=_capture_identity, daemon=True)
        watcher.start()
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir).run_once(artifacts)
        watcher.join(timeout=2)
        assert captured.value.code == "worker.process.timeout"
        leftover = load_execution_identity(identity_dir, LEASE_ID)
        assert leftover is None
        first_spawns = spawns["n"]
        assert first_spawns == 1
        for container_id in container_ids:
            assert inspect_container_running(backend.executable, container_id) is not True
        with pytest.raises(WorkerError) as resumed:
            _client(server, token, identity_dir).run_once(artifacts)
        assert resumed.value.code == "work-already-claimed"
        assert spawns["n"] == first_spawns
    finally:
        _cleanup_identity(identity_dir)
        server.stop()
    types = _event_types(database)
    assert "work.failed" not in types
    assert "work.completed" not in types
    with EventStore(database, require_existing=True) as store:
        runtime = _runtime_for(store)
        report = TrustedKernel(build_registry([OCI_CORPUS / "block.json"])).dry_run(
            spec, workflow_id=spec.workflows[0].id
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


@pytest.mark.oci_live
def test_live_oci_killed_worker_leaves_container_recovery_does_not_spawn(
    tmp_path: Path,
    oci_live_runtime: tuple[OciBackend, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform == "win32":
        pytest.skip("SIGKILL orphan recovery is a POSIX Worker outcome")
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, _spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
    spawns = _count_oci_spawns(monkeypatch)
    server = _server(database, artifacts)
    worker: subprocess.Popen[bytes] | None = None
    try:
        server.start()
        worker = _spawn_worker_process(tmp_path, server, token, identity_dir, artifacts)
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        assert inspect_container_running(backend.executable, identity.container_id) is True
        assert worker.pid is not None
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir).run_once(artifacts)
        assert captured.value.code == "work-already-claimed"
        assert spawns["n"] == 0
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.kill")
        with pytest.raises(WorkerError) as stopped:
            _client(server, token, identity_dir).run_once(artifacts)
        assert stopped.value.code == "cancel-observed"
        assert inspect_container_running(backend.executable, identity.container_id) is not True
        assert spawns["n"] == 0
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        _cleanup_identity(identity_dir)
        server.stop()
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types


@pytest.mark.oci_live
def test_live_oci_control_plane_restart_keeps_container_then_observes_cancel(
    tmp_path: Path, oci_live_runtime: tuple[OciBackend, str]
) -> None:
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
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
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        server.stop()
        original_stopped = True
        restarted = _server(database, artifacts, port=port)
        restarted.start()
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.restart")
        assert thread is not None
        thread.join(timeout=15)
        assert thread.is_alive() is False
        assert inspect_container_running(backend.executable, identity.container_id) is not True
    finally:
        if thread is not None and thread.is_alive():
            _cleanup_identity(identity_dir)
            thread.join(timeout=5)
        if restarted is not None:
            restarted.stop()
        elif not original_stopped:
            server.stop()
        _cleanup_identity(identity_dir)
    assert captured
    assert captured[0].code == "cancel-observed"
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types
    _reconcile_cancelled(database, artifacts, spec)


@pytest.mark.oci_live
def test_live_oci_external_stop_is_observed(
    tmp_path: Path, oci_live_runtime: tuple[OciBackend, str]
) -> None:
    if sys.platform == "win32":
        pytest.skip("SIGKILL orphan recovery is a POSIX Worker outcome")
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
    server = _server(database, artifacts)
    worker: subprocess.Popen[bytes] | None = None
    try:
        server.start()
        worker = _spawn_worker_process(tmp_path, server, token, identity_dir, artifacts)
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        assert worker.pid is not None
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        stopped = subprocess.run(
            [backend.executable, "stop", "-t", "1", identity.container_id],
            check=False,
            capture_output=True,
            timeout=15,
        )
        assert stopped.returncode == 0
        assert inspect_container_running(backend.executable, identity.container_id) is False
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.stop")
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir).run_once(artifacts)
        assert captured.value.code == "cancel-observed"
        assert inspect_container_running(backend.executable, identity.container_id) is not True
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        _cleanup_identity(identity_dir)
        server.stop()
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types
    _reconcile_cancelled(database, artifacts, spec)


@pytest.mark.oci_live
def test_live_oci_inspect_failure_stays_unknown(
    tmp_path: Path, oci_live_runtime: tuple[OciBackend, str]
) -> None:
    if sys.platform == "win32":
        pytest.skip("SIGKILL orphan recovery is a POSIX Worker outcome")
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, _spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
    server = _server(database, artifacts)
    worker: subprocess.Popen[bytes] | None = None
    try:
        server.start()
        worker = _spawn_worker_process(tmp_path, server, token, identity_dir, artifacts)
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        assert worker.pid is not None
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        remove_oci_container(backend.executable, identity.container_id)
        assert inspect_container_running(backend.executable, identity.container_id) is None
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.inspect")
        with pytest.raises(WorkerError) as captured:
            _client(server, token, identity_dir).run_once(artifacts)
        assert captured.value.code == UNOBSERVED
        types = _event_types(database)
        assert "work.failed" not in types
        assert "work.completed" not in types
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        _cleanup_identity(identity_dir)
        server.stop()


@pytest.mark.oci_live
def test_live_oci_recovery_while_container_alive_does_not_spawn(
    tmp_path: Path,
    oci_live_runtime: tuple[OciBackend, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, image = oci_live_runtime
    database, artifacts, identity_dir, token, spec = _queue_oci_live(tmp_path, image, SLEEP_BRICK)
    spawns = _count_oci_spawns(monkeypatch)
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
        identity = _wait_oci_identity(identity_dir)
        assert identity.container_id is not None
        assert spawns["n"] == 1
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with pytest.raises(WorkerError) as second:
            _client(server, token, identity_dir).run_once(artifacts)
        assert second.value.code == "work-already-claimed"
        assert spawns["n"] == 1
        assert inspect_container_running(backend.executable, identity.container_id) is True
        with EventStore(database, require_existing=True) as store:
            _request_run_cancel(store, event_id="evt.run.cancel.requested.oci.second")
        thread.join(timeout=15)
        assert thread.is_alive() is False
        assert inspect_container_running(backend.executable, identity.container_id) is not True
    finally:
        _cleanup_identity(identity_dir)
        server.stop()
    assert captured and captured[0].code == "cancel-observed"
    types = _event_types(database)
    assert "work.failed" in types
    assert "work.completed" not in types
    _reconcile_cancelled(database, artifacts, spec)
