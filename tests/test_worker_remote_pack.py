from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_worker_protocol import HMAC_KEY, PROJECT, SOURCE

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.bind import require_worker_bind_host
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.remote_pack import (
    _refuse_key_in_worker,
    write_remote_worker_pack,
)
from llm_research_os.workers.tls import cert_covers_host, load_or_create_tls


def test_http_bind_still_rejects_unspecified_and_localhost(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    with pytest.raises(WorkerError) as captured:
        LoopbackWorkerServer(
            tmp_path / "research.db",
            LocalArtifactStore(artifacts_root),
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            host="0.0.0.0",
        )
    assert captured.value.code == "bind-unspecified"
    with pytest.raises(WorkerError) as captured:
        LoopbackWorkerServer(
            tmp_path / "research.db",
            LocalArtifactStore(artifacts_root),
            hmac_key=HMAC_KEY,
            project_id=PROJECT,
            source=SOURCE,
            host="localhost",
        )
    assert captured.value.code == "bind-not-loopback"


def test_tls_allows_unicast_and_rejects_unspecified() -> None:
    require_worker_bind_host("192.0.2.10", tls=True)
    require_worker_bind_host("127.0.0.1", tls=True)
    require_worker_bind_host("worker.example.test", tls=True)
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("0.0.0.0", tls=True)
    assert captured.value.code == "bind-unspecified"
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("::", tls=True)
    assert captured.value.code == "bind-unspecified"
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("224.0.0.1", tls=True)
    assert captured.value.code == "bind-multicast"
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("", tls=True)
    assert captured.value.code == "bind-host-invalid"
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("*", tls=True)
    assert captured.value.code == "bind-host-invalid"
    with pytest.raises(WorkerError) as captured:
        require_worker_bind_host("worker.example.test", tls=False)
    assert captured.value.code == "bind-not-loopback"


def test_remote_pack_is_pending_live_and_omits_private_key(tmp_path: Path) -> None:
    output = tmp_path / "pack"
    output.mkdir()
    status = write_remote_worker_pack(
        output,
        control_plane_url="https://192.0.2.10:8443",
        project_id=PROJECT,
        source=SOURCE,
    )
    assert status["crossMachine"] == "pending-live"
    assert status["localhostIsNotCrossMachine"] is True
    assert status["binding"] == "remote-https-json"
    assert (output / "STATUS.json").is_file()
    worker = output / "worker"
    assert (worker / "tls-cert.pem").is_file()
    assert not (worker / "tls-key.pem").exists()
    for path in worker.rglob("*"):
        assert "key" not in path.name.lower()
    assert (output / "control-state" / "tls-key.pem").is_file()
    template = json.loads((worker / "credential.template.json").read_text(encoding="utf-8"))
    assert template["session"] == "REPLACE-WITH-WS1"
    assert template["grantToken"] == "REPLACE-WITH-RG1"
    assert "pending-live" in (output / "README.md").read_text(encoding="utf-8")
    assert cert_covers_host(worker / "tls-cert.pem", "192.0.2.10")


def test_loopback_pack_is_not_cross_machine(tmp_path: Path) -> None:
    output = tmp_path / "loop"
    output.mkdir()
    status = write_remote_worker_pack(
        output,
        control_plane_url="https://127.0.0.1:8443",
        project_id=PROJECT,
        source=SOURCE,
    )
    assert status["binding"] == "loopback-not-cross-machine"
    assert status["crossMachine"] == "pending-live"
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "not a cross-machine proof" in readme.replace("*", "")


def test_pack_copies_ca_from_state_and_never_the_key(tmp_path: Path) -> None:
    state = tmp_path / "state"
    material = load_or_create_tls(state, host="127.0.0.1")
    output = tmp_path / "pack"
    output.mkdir()
    write_remote_worker_pack(
        output,
        control_plane_url="https://127.0.0.1:8443",
        project_id=PROJECT,
        source=SOURCE,
        state_dir=state,
    )
    worker_cert = output / "worker" / "tls-cert.pem"
    assert worker_cert.is_file()
    assert worker_cert.read_bytes() == material.cert_path.read_bytes()
    assert not (output / "worker" / "tls-key.pem").exists()
    assert stat.S_IMODE(worker_cert.stat().st_mode) == 0o600


def test_pack_rejects_http_and_userinfo(tmp_path: Path) -> None:
    output = tmp_path / "pack"
    output.mkdir()
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            output,
            control_plane_url="http://192.0.2.10:8443",
            project_id=PROJECT,
            source=SOURCE,
        )
    assert captured.value.code == "remote-url-not-https"
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            tmp_path / "pack2",
            control_plane_url="https://user:pass@192.0.2.10:8443",
            project_id=PROJECT,
            source=SOURCE,
        )
    assert captured.value.code == "remote-url-invalid"
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            tmp_path / "pack3",
            control_plane_url="https://192.0.2.10:8443/v0",
            project_id=PROJECT,
            source=SOURCE,
        )
    assert captured.value.code == "remote-url-invalid"
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            tmp_path / "pack4",
            control_plane_url="https://192.0.2.10:8443?x=1",
            project_id=PROJECT,
            source=SOURCE,
        )
    assert captured.value.code == "remote-url-invalid"


def test_pack_refuses_non_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "pack"
    output.mkdir()
    (output / "stale.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            output,
            control_plane_url="https://192.0.2.10:8443",
            project_id=PROJECT,
            source=SOURCE,
        )
    assert captured.value.code == "pack-exists"


def test_tls_san_mismatch_on_existing_loopback_cert(tmp_path: Path) -> None:
    state = tmp_path / "state"
    load_or_create_tls(state, host="127.0.0.1")
    with pytest.raises(WorkerError) as captured:
        load_or_create_tls(state, host="192.0.2.10")
    assert captured.value.code == "tls-san-mismatch"


def test_pack_refuses_missing_ca_and_san_mismatch(tmp_path: Path) -> None:
    missing = tmp_path / "empty-state"
    missing.mkdir()
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            tmp_path / "pack-missing",
            control_plane_url="https://127.0.0.1:8443",
            project_id=PROJECT,
            source=SOURCE,
            state_dir=missing,
        )
    assert captured.value.code == "tls-material-invalid"
    state = tmp_path / "loop-state"
    load_or_create_tls(state, host="127.0.0.1")
    with pytest.raises(WorkerError) as captured:
        write_remote_worker_pack(
            tmp_path / "pack-mismatch",
            control_plane_url="https://192.0.2.10:8443",
            project_id=PROJECT,
            source=SOURCE,
            state_dir=state,
        )
    assert captured.value.code == "tls-san-mismatch"


def test_pack_refuses_worker_private_key(tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "tls-key.pem").write_text("secret", encoding="utf-8")
    with pytest.raises(WorkerError) as captured:
        _refuse_key_in_worker(worker)
    assert captured.value.code == "pack-private-key"


def test_incomplete_tls_material_fails(tmp_path: Path) -> None:
    state = tmp_path / "half"
    state.mkdir()
    (state / "tls-cert.pem").write_text("not-a-pair", encoding="utf-8")
    with pytest.raises(WorkerError) as captured:
        load_or_create_tls(state, host="127.0.0.1")
    assert captured.value.code == "tls-material-invalid"


def test_hostname_tls_san_covers_dns(tmp_path: Path) -> None:
    material = load_or_create_tls(tmp_path / "dns-state", host="worker.example.test")
    assert cert_covers_host(material.cert_path, "worker.example.test")
    assert not cert_covers_host(material.cert_path, "127.0.0.1")


def test_workers_pack_cli_writes_pending_live_status(tmp_path: Path) -> None:
    output = tmp_path / "cli-pack"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "workers",
            "pack",
            str(output),
            "--url",
            "https://192.0.2.10:8443",
            "--project",
            PROJECT,
            "--source",
            SOURCE,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    status = json.loads(completed.stdout)
    assert status["crossMachine"] == "pending-live"
    assert not (output / "worker" / "tls-key.pem").exists()


def test_workers_pack_cli_rejects_http_url(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "workers",
            "pack",
            str(tmp_path / "bad"),
            "--url",
            "http://192.0.2.10:8443",
            "--project",
            PROJECT,
            "--source",
            SOURCE,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "remote-url-not-https" in completed.stderr
