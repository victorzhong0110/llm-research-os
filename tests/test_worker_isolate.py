from __future__ import annotations

import ast
import json
import shutil
import stat
import subprocess
import sys
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
from llm_research_os.workers.credentials import (
    WorkerCredential,
    load_hmac_key,
    load_or_create_hmac_key,
    load_worker_credential,
    redact_worker_log,
    write_hmac_key,
    write_worker_credential,
)
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.isolated import run_isolated_worker
from llm_research_os.workers.serve import bind_isolated_control_plane, serve_isolated_control_plane
from llm_research_os.workers.tls import load_or_create_loopback_tls, pem_fingerprint
from llm_research_os.workers.tokens import issue_worker_session

ROOT = Path(__file__).parents[1]


def test_isolated_module_does_not_import_event_store() -> None:
    tree = ast.parse((ROOT / "src/llm_research_os/workers/isolated.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            assert "storage" not in node.module.split(".")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "storage" not in alias.name.split(".")


def test_worker_downloads_image_into_private_cas(tmp_path: Path) -> None:
    store, _control_artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        server = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        worker_root = tmp_path / "worker-cas"
        worker_root.mkdir()
        worker_artifacts = LocalArtifactStore(worker_root)
        server.start()
        try:
            client = WorkerClient(
                base_url=server.base_url,
                worker_id="worker.loopback.1",
                session=server.session_for("worker.loopback.1"),
                grant_token=token,
            )
            completed = client.run_once(worker_artifacts)
            assert completed is not None
            worker_artifacts.verify(image)
            assert worker_root.resolve() != plane.artifacts.root.resolve()
        finally:
            server.stop()
    finally:
        store.__exit__(None, None, None)


def test_image_fetch_requires_the_grant_image(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        server = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        server.start()
        try:
            parsed = urlparse(server.base_url)
            connection = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=10)
            try:
                connection.request(
                    "GET",
                    f"/v0alpha1/artifacts/sha256/{'b' * 64}",
                    headers={
                        "Authorization": f"Bearer {server.session_for('worker.loopback.1')}",
                        "X-ResearchOS-Grant": token,
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
            assert response.status == 400
            assert payload["code"] == "execution-binding-mismatch"
        finally:
            server.stop()
    finally:
        store.__exit__(None, None, None)


def test_reconnect_retries_disconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        server = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
        )
        server.start()
        try:
            client = WorkerClient(
                base_url=server.base_url,
                worker_id="worker.loopback.1",
                session=server.session_for("worker.loopback.1"),
                grant_token=token,
            )
            calls = {"n": 0}
            original = WorkerClient._raw_once

            def _flaky(
                self: WorkerClient,
                method: str,
                path: str,
                payload: bytes,
                *,
                content_type: str,
                grant: bool,
            ) -> tuple[int, bytes]:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise WorkerError("worker transport is unavailable", code="http-disconnect")
                return original(
                    self,
                    method,
                    path,
                    payload,
                    content_type=content_type,
                    grant=grant,
                )

            monkeypatch.setattr(WorkerClient, "_raw_once", _flaky)
            worker_root = tmp_path / "worker-cas"
            worker_root.mkdir()
            worker_artifacts = LocalArtifactStore(worker_root)
            completed = client.run_once(worker_artifacts)
            assert completed is not None
            assert calls["n"] >= 2
        finally:
            server.stop()
    finally:
        store.__exit__(None, None, None)


def test_loopback_https_uses_pinned_ca_and_private_cas(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        tls = load_or_create_loopback_tls(tmp_path / "tls")
        server = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
            tls=tls,
        )
        assert server.base_url.startswith("https://127.0.0.1:")
        server.start()
        try:
            worker_root = tmp_path / "worker-cas"
            worker_root.mkdir()
            worker_artifacts = LocalArtifactStore(worker_root)
            client = WorkerClient(
                base_url=server.base_url,
                worker_id="worker.loopback.1",
                session=server.session_for("worker.loopback.1"),
                grant_token=token,
                ca_path=tls.cert_path,
                tls_fingerprint=tls.fingerprint,
            )
            completed = client.run_once(worker_artifacts)
            assert completed is not None
            worker_artifacts.verify(image)
        finally:
            server.stop()
    finally:
        store.__exit__(None, None, None)


def test_control_plane_restart_reloads_hmac_key(tmp_path: Path) -> None:
    state = tmp_path / "state"
    write_hmac_key(state / "hmac.key", HMAC_KEY)
    assert load_hmac_key(state / "hmac.key") == HMAC_KEY
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        tls = load_or_create_loopback_tls(state)
        first = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=load_hmac_key(state / "hmac.key"),
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
            tls=tls,
        )
        session = first.session_for("worker.loopback.1")
        first.start()
        first.stop()
        second = LoopbackWorkerServer(
            tmp_path / "research.db",
            plane.artifacts,
            hmac_key=load_hmac_key(state / "hmac.key"),
            project_id=PROJECT,
            source=SOURCE,
            clock=FrozenClock(NOW),
            tls=tls,
        )
        second.start()
        try:
            client = WorkerClient(
                base_url=second.base_url,
                worker_id="worker.loopback.1",
                session=session,
                grant_token=token,
                ca_path=tls.cert_path,
                tls_fingerprint=tls.fingerprint,
            )
            worker_root = tmp_path / "worker-cas"
            worker_root.mkdir()
            worker_artifacts = LocalArtifactStore(worker_root)
            assert client.run_once(worker_artifacts) is not None
        finally:
            second.stop()
    finally:
        store.__exit__(None, None, None)


def test_credential_file_is_private_and_logs_redact_tokens(tmp_path: Path) -> None:
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    credential = WorkerCredential(
        control_plane_url="https://127.0.0.1:1",
        worker_id="worker.loopback.1",
        session=issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1"),
        grant_token="rg1." + ("a" * 32),
        tls_ca_path=tls.cert_path,
        tls_fingerprint=tls.fingerprint,
    )
    path = tmp_path / "credential.json"
    write_worker_credential(path, credential)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR
    leaked = redact_worker_log(
        f"failed {credential.session} {credential.grant_token}",
        *credential.secrets(),
    )
    assert credential.session not in leaked
    assert credential.grant_token not in leaked
    loaded = load_worker_credential(path)
    assert loaded.worker_id == credential.worker_id
    assert loaded.tls_fingerprint == credential.tls_fingerprint
    with pytest.raises(WorkerError, match="already exists"):
        write_worker_credential(path, credential)
    key = load_or_create_hmac_key(tmp_path / "hmac-state")
    assert load_or_create_hmac_key(tmp_path / "hmac-state") == key
    other = tmp_path / "hmac-state" / "hmac.key"
    with pytest.raises(WorkerError, match="does not match"):
        write_hmac_key(other, b"b" * 32)
    bad = tmp_path / "bad-credential.json"
    bad.write_text('{"apiVersion":"researchos.dev/v0alpha1","kind":"Nope"}', encoding="utf-8")
    with pytest.raises(WorkerError, match="kind is invalid"):
        load_worker_credential(bad)


def test_run_isolated_worker_and_bind_control_plane(tmp_path: Path) -> None:
    store, _artifacts, plane, image = _plane(tmp_path)
    try:
        token = _grant_and_queue(plane, image)
        write_hmac_key(tmp_path / "state" / "hmac.key", HMAC_KEY)
        server, tls = bind_isolated_control_plane(
            database=tmp_path / "research.db",
            artifacts_root=plane.artifacts.root,
            state_dir=tmp_path / "state",
            project_id=PROJECT,
            source=SOURCE,
        )
        assert server.base_url.startswith("https://127.0.0.1:")
        server.start()
        try:
            worker_dir = tmp_path / "worker"
            worker_dir.mkdir()
            ca = worker_dir / "tls-cert.pem"
            shutil.copy2(tls.cert_path, ca)
            credential_path = worker_dir / "credential.json"
            write_worker_credential(
                credential_path,
                WorkerCredential(
                    control_plane_url=server.base_url,
                    worker_id="worker.loopback.1",
                    session=server.session_for("worker.loopback.1"),
                    grant_token=token,
                    tls_ca_path=ca,
                    tls_fingerprint=pem_fingerprint(ca),
                ),
            )
            completed = run_isolated_worker(
                credential_path=credential_path,
                artifacts_root=worker_dir / "artifacts",
            )
            assert completed["type"] == "work.completed"
        finally:
            server.stop()
        http_path = worker_dir / "http.json"
        http_cred = load_worker_credential(credential_path)
        write_worker_credential(
            http_path,
            WorkerCredential(
                control_plane_url="http://127.0.0.1:1",
                worker_id=http_cred.worker_id,
                session=http_cred.session,
                grant_token=http_cred.grant_token,
                tls_ca_path=http_cred.tls_ca_path,
                tls_fingerprint=http_cred.tls_fingerprint,
            ),
        )
        with pytest.raises(WorkerError) as captured:
            run_isolated_worker(
                credential_path=http_path,
                artifacts_root=worker_dir / "http-cas",
            )
        assert captured.value.code == "tls-required"
    finally:
        store.__exit__(None, None, None)


def test_serve_prints_receipt_then_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    store, _artifacts, plane, _image = _plane(tmp_path)
    try:
        write_hmac_key(tmp_path / "state" / "hmac.key", HMAC_KEY)
    finally:
        store.__exit__(None, None, None)

    def _interrupt(self: LoopbackWorkerServer) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(LoopbackWorkerServer, "serve_forever", _interrupt)
    serve_isolated_control_plane(
        database=tmp_path / "research.db",
        artifacts_root=plane.artifacts.root,
        state_dir=tmp_path / "state",
        project_id=PROJECT,
        source=SOURCE,
    )
    printed = capsys.readouterr().out  # type: ignore[attr-defined]
    receipt = json.loads(printed.strip().splitlines()[0])
    assert receipt["url"].startswith("https://127.0.0.1:")
    assert receipt["tlsFingerprint"].startswith("sha256:")


def test_isolated_https_processes_do_not_share_cas(tmp_path: Path) -> None:
    control = tmp_path / "control"
    worker = tmp_path / "worker"
    state = control / "state"
    store, _artifacts, plane, image = _plane(control)
    try:
        token = _grant_and_queue(plane, image)
        write_hmac_key(state / "hmac.key", HMAC_KEY)
        database = control / "research.db"
        control_cas = plane.artifacts.root
    finally:
        store.__exit__(None, None, None)
    serve = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "workers",
            "serve",
            str(database),
            "--artifacts",
            str(control_cas),
            "--state",
            str(state),
            "--project",
            PROJECT,
            "--source",
            SOURCE,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert serve.stdout is not None
        line = serve.stdout.readline()
        receipt = json.loads(line)
        url = receipt["url"]
        assert url.startswith("https://127.0.0.1:")
        ca = worker / "tls-cert.pem"
        worker.mkdir()
        shutil.copy2(state / "tls-cert.pem", ca)
        credential_path = worker / "credential.json"
        write_worker_credential(
            credential_path,
            WorkerCredential(
                control_plane_url=url,
                worker_id="worker.loopback.1",
                session=issue_worker_session(HMAC_KEY, worker_id="worker.loopback.1"),
                grant_token=token,
                tls_ca_path=ca,
                tls_fingerprint=pem_fingerprint(ca),
            ),
        )
        worker_cas = worker / "artifacts"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "llm_research_os",
                "workers",
                "run",
                str(credential_path),
                "--artifacts",
                str(worker_cas),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        assert "rg1." not in completed.stdout
        assert "rg1." not in completed.stderr
        assert str(database) not in completed.args
        LocalArtifactStore(worker_cas).verify(image)
        with EventStore(database, require_existing=True) as replay:
            types = [item.event.type for item in replay.read_events(limit=40)]
        assert "work.completed" in types
        assert control_cas.resolve() != worker_cas.resolve()
    finally:
        serve.terminate()
        serve.wait(timeout=10)


def test_lease_seconds_reads_researchos_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_research_os.workers.http import _lease_seconds
    from llm_research_os.workers.plane import DEFAULT_LEASE_SECONDS

    monkeypatch.delenv("RESEARCHOS_LEASE_SECONDS", raising=False)
    assert _lease_seconds() == DEFAULT_LEASE_SECONDS
    monkeypatch.setenv("RESEARCHOS_LEASE_SECONDS", "1800")
    assert _lease_seconds() == 1800
    monkeypatch.setenv("RESEARCHOS_LEASE_SECONDS", "0")
    assert _lease_seconds() == DEFAULT_LEASE_SECONDS
    monkeypatch.setenv("RESEARCHOS_LEASE_SECONDS", "not-an-int")
    assert _lease_seconds() == DEFAULT_LEASE_SECONDS
