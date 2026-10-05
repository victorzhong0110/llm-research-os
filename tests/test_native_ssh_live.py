"""SSH onboarding uses a fixed command, pinned key, and verified Worker facts."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import platform
import re
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from test_native_ssh_onboard import HOST_KEY, PROJECT, SOURCE
from test_worker_protocol import HMAC_KEY, NOW, FrozenClock, _plane

from llm_research_os.cli import main, native_commands
from llm_research_os.execution import NativeSshError, parse_ssh_target, write_native_ssh_pack
from llm_research_os.execution import native_ssh_remote as remote
from llm_research_os.execution.native_ssh_live import _wheelhouse, probe_ssh_pack
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.tls import load_or_create_loopback_tls


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    workdir = tmp_path / "worker"
    workdir.mkdir(mode=0o700)
    target = parse_ssh_target(
        host="127.0.0.1",
        port=2222,
        user="researcher",
        workdir=str(workdir),
        host_key=HOST_KEY,
    )
    pack = tmp_path / "pack"
    write_native_ssh_pack(pack, target, project_id=PROJECT, source=SOURCE)
    identity = tmp_path / "identity"
    identity.write_text("fake private key")
    identity.chmod(0o600)
    # This local transport executes the exact remote shell command and stdin.
    # It exercises the production wire protocol without claiming a second host.
    #
    # The remote command is `python3 -I -c <source>`, so `python3` is resolved
    # from PATH *inside* this container. `_probe` requires 3.12+ on the worker
    # host and correctly refuses anything older, which is why these tests used
    # to fail on a host whose system python3 predates the minimum: the transport
    # was simulating a non-compliant host while the tests asserted `ready`.
    # Pin PATH to the interpreter running the suite so the simulated host meets
    # the documented minimum, whatever the ambient system python happens to be.
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"os.environ['PATH'] = {str(Path(sys.executable).resolve().parent)!r} + os.pathsep"
        " + os.environ['PATH']\n"
        "p = subprocess.run(sys.argv[-1], input=sys.stdin.buffer.read(), "
        "shell=True, capture_output=True)\n"
        "sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr)\n"
        "sys.exit(p.returncode)\n"
    )
    fake_ssh.chmod(0o700)
    return pack, identity, fake_ssh


def test_the_simulated_host_meets_the_python_minimum(tmp_path: Path) -> None:
    """The local transport must not depend on the ambient system python3.

    The remote command is `python3 -I -c ...`, resolved from PATH inside this
    container. If the host interpreter is older than the minimum the probe
    refuses it, and every test above fails for a reason that has nothing to do
    with what it is testing. Asserting the simulated host is compliant turns
    that environment coupling into an immediate, local failure.
    """
    _, _, fake_ssh = _setup(tmp_path)

    pinned = re.search(r"PATH'\] = '([^']+)'", fake_ssh.read_text())
    assert pinned, "_setup must pin PATH for the simulated host"
    interpreter = Path(pinned.group(1)) / "python3"
    assert interpreter.is_file(), f"pinned interpreter does not exist: {interpreter}"

    resolved = subprocess.run(
        [str(interpreter), "-c", "import sys;print(*sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=True,
    )
    major, minor = (int(part) for part in resolved.stdout.split())
    assert (major, minor) >= (3, 12), (
        f"the simulated worker host runs Python {major}.{minor}, below the 3.12 "
        "minimum the probe enforces; _setup did not pin PATH correctly"
    )


def test_pinned_probe_and_repairs_do_not_mutate_worker(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    result = probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert result["outcome"] == "ready"
    assert result["platform"] == platform.system().lower()
    assert remote._probe(tmp_path / "worker", None)["outcome"] == "ready"
    assert remote._probe(tmp_path / "worker", 0)["code"] == "port-invalid"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        assert sock.getsockname()[1]
        blocked = probe_ssh_pack(
            pack,
            identity_file=identity,
            port=sock.getsockname()[1],
            ssh_executable=str(fake_ssh),
        )
        assert blocked["code"] == "port-in-use"
        assert remote._probe(tmp_path / "worker", sock.getsockname()[1])["code"] == "port-in-use"
    assert list((tmp_path / "worker").iterdir()) == []
    known_hosts = pack / "known_hosts.native"
    known_hosts.write_text("[127.0.0.1]:2222 ssh-ed25519 changed\n")
    with pytest.raises(NativeSshError, match="pinned host key"):
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert not (tmp_path / "worker" / ".researchos").exists()


def test_worker_identity_requires_tls_and_registration(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    store, artifacts, plane, _image = _plane(tmp_path / "control")
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    server = LoopbackWorkerServer(
        tmp_path / "control" / "research.db",
        artifacts,
        hmac_key=HMAC_KEY,
        project_id=plane.project_id,
        source=plane.source,
        clock=FrozenClock(NOW),
        tls=tls,
    )
    server.start()
    try:
        before = store.last_sequence()
        credential = tmp_path / "credential.json"
        fields = {
            "controlPlaneUrl": server.base_url,
            "workerId": "worker.loopback.1",
            "session": server.session_for("worker.loopback.1"),
            "tlsFingerprint": tls.fingerprint,
        }
        credential.write_text(json.dumps(fields))
        credential.chmod(0o600)
        verified = probe_ssh_pack(
            pack,
            identity_file=identity,
            worker_credential=credential,
            ca_path=tls.cert_path,
            operation="verify-worker",
            ssh_executable=str(fake_ssh),
        )
        assert verified["tlsVerified"] is True
        assert verified["registered"] is True
        assert (
            remote._worker_identity(fields | {"caPem": tls.cert_path.read_text()})["outcome"]
            == "ready"
        )
        fields["workerId"] = "worker.unregistered"
        fields["session"] = server.session_for("worker.unregistered")
        credential.write_text(json.dumps(fields))
        denied = probe_ssh_pack(
            pack,
            identity_file=identity,
            worker_credential=credential,
            ca_path=tls.cert_path,
            operation="verify-worker",
            ssh_executable=str(fake_ssh),
        )
        assert denied["code"] == "worker-registration-unverified"
        assert (
            remote._worker_identity(fields | {"caPem": tls.cert_path.read_text()})["code"]
            == "worker-registration-unverified"
        )
        assert store.last_sequence() == before
        wrong_ca = tmp_path / "wrong.pem"
        wrong_ca.write_text(tls.cert_path.read_text() + "\n")
        with pytest.raises(NativeSshError, match="credential or CA is invalid"):
            probe_ssh_pack(
                pack,
                identity_file=identity,
                worker_credential=credential,
                ca_path=wrong_ca,
                operation="verify-worker",
                ssh_executable=str(fake_ssh),
            )
    finally:
        server.stop()
        store.__exit__(None, None, None)


def test_private_identity_and_remote_missing_workdir_refuse(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    identity.chmod(0o644)
    with pytest.raises(NativeSshError, match="private user-owned"):
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    identity.chmod(0o600)
    os.rmdir(tmp_path / "worker")
    result = probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert result["code"] == "workdir-missing"


def test_offline_install_is_idempotent_and_keeps_unrelated_files(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "llm_research_os-0.0.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("llm_research_os/__init__.py", "R07_TEST = True\n")
        archive.writestr(
            "llm_research_os-0.0.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: llm-research-os\nVersion: 0.0.1\n",
        )
        archive.writestr(
            "llm_research_os-0.0.1.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: r07-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("llm_research_os-0.0.1.dist-info/RECORD", "")
    unrelated = tmp_path / "worker" / "my-notes.txt"
    unrelated.write_text("preserve")
    first = probe_ssh_pack(
        pack,
        identity_file=identity,
        operation="install",
        wheel_dir=wheels,
        ssh_executable=str(fake_ssh),
    )
    assert first["outcome"] == "ready" and first["installed"] is True
    again = probe_ssh_pack(
        pack,
        identity_file=identity,
        operation="install",
        wheel_dir=wheels,
        ssh_executable=str(fake_ssh),
    )
    assert again["installed"] is False and again["digest"] == first["digest"]
    assert unrelated.read_text() == "preserve"
    assert not (Path(first["runtime"]) / "wheels").exists()
    assert (Path(first["runtime"]) / "venv" / "bin" / "python").exists()
    in_process = tmp_path / "in-process"
    in_process.mkdir()
    assert remote._install(in_process, _wheelhouse(wheels))["installed"] is True
    assert remote._install(tmp_path / "worker", _wheelhouse(wheels))["installed"] is False


def test_failed_install_cleans_only_new_runtime(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "llm_research_os-0.0.1-py3-none-any.whl").write_bytes(b"not a wheel")
    unrelated = tmp_path / "worker" / "keep"
    unrelated.write_text("mine")
    result = probe_ssh_pack(
        pack,
        identity_file=identity,
        operation="install",
        wheel_dir=wheels,
        ssh_executable=str(fake_ssh),
    )
    assert result["code"] == "install-failed"
    assert unrelated.read_text() == "mine"
    assert list((tmp_path / "worker" / ".researchos").iterdir()) == []
    assert remote._install(tmp_path / "worker", _wheelhouse(wheels))["code"] == "install-failed"


def test_disconnect_does_not_report_ready(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    fake_ssh.write_text("#!/bin/sh\nexit 255\n")
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert error.value.code == "ssh-disconnected"


def test_rotated_live_host_key_refuses(tmp_path: Path) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    fake_ssh.write_text("#!/bin/sh\necho 'Host key verification failed.' >&2\nexit 255\n")
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert error.value.code == "ssh-host-key-changed"


def test_cli_reports_blocked_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pack, identity, _fake_ssh = _setup(tmp_path)
    monkeypatch.setattr(
        native_commands,
        "probe_ssh_pack",
        lambda *args, **kwargs: {"outcome": "blocked", "code": "disk-low", "repair": "Free disk."},
    )
    assert (
        main(
            [
                "native",
                "ssh-doctor",
                str(pack),
                "--identity-file",
                str(identity),
                "--format",
                "json",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["code"] == "disk-low"


def test_remote_input_refusals_are_scoped(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir(mode=0o700)
    assert remote._workdir(str(workdir)) == workdir
    with pytest.raises(ValueError, match="workdir-invalid"):
        remote._workdir("relative/path")
    with pytest.raises(ValueError, match="workdir-missing"):
        remote._workdir(str(tmp_path / "missing"))
    assert remote._install(workdir, {})["code"] == "package-invalid"
    assert (
        remote._install(workdir, {"wheels": {}, "archive": "!", "package": "x"})["code"]
        == "package-invalid"
    )
    assert remote._worker_identity({})["code"] == "worker-credential-invalid"
    assert (
        remote._worker_identity(
            {
                "controlPlaneUrl": "http://localhost",
                "workerId": "w",
                "session": "s",
                "caPem": "c",
                "tlsFingerprint": "f",
            }
        )["code"]
        == "tls-required"
    )
    assert (
        remote._worker_identity(
            {
                "controlPlaneUrl": "https://localhost",
                "workerId": "w",
                "session": "s",
                "caPem": "c",
                "tlsFingerprint": "f",
            }
        )["code"]
        == "tls-fingerprint-mismatch"
    )


def test_remote_wheel_digest_and_existing_runtime_conflicts(tmp_path: Path) -> None:
    workdir = tmp_path / "worker"
    workdir.mkdir()
    name = "llm_research_os-0.0.1-py3-none-any.whl"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(name, b"wheel-bytes")
    document = {
        "wheels": {name: hashlib.sha256(b"different").hexdigest()},
        "archive": base64.b64encode(archive.getvalue()).decode(),
        "package": name,
    }
    assert remote._install(workdir, document)["code"] == "package-digest-mismatch"
    assert not (workdir / ".researchos").exists()
    document["wheels"] = {name: hashlib.sha256(b"wheel-bytes").hexdigest()}
    digest = hashlib.sha256(archive.getvalue()).hexdigest()
    root = workdir / ".researchos"
    root.mkdir(mode=0o700)
    (root / f"runtime-{digest[:24]}").mkdir()
    assert remote._install(workdir, document)["code"] == "install-conflict"
    assert (root / f"runtime-{digest[:24]}").is_dir()


def test_remote_probe_platform_and_disk_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import namedtuple

    monkeypatch.setattr(remote.platform, "system", lambda: "Windows")
    assert remote._probe(tmp_path, None)["code"] == "platform-unsupported"
    monkeypatch.setattr(remote.platform, "system", lambda: "Linux")
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(remote.shutil, "disk_usage", lambda _path: Usage(100, 99, 1))
    assert remote._probe(tmp_path, None)["code"] == "disk-low"


@pytest.mark.parametrize("operation", ["probe", "unknown", "install", "verify-worker"])
def test_remote_main_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import sys

    output = io.StringIO()
    workdir = tmp_path / "worker"
    workdir.mkdir(mode=0o700)
    document = {"operation": operation, "workdir": str(workdir)}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(document).encode())))
    monkeypatch.setattr(sys, "stdout", output)
    remote.main()
    result = json.loads(output.getvalue())
    assert result["outcome"] == ("ready" if operation == "probe" else "blocked")


@pytest.mark.parametrize("payload", [b"not-json", b"[]", b'{"workdir":"/missing"}'])
def test_remote_main_invalid_inputs(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    import sys

    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))
    monkeypatch.setattr(sys, "stdout", output)
    remote.main()
    assert json.loads(output.getvalue())["outcome"] == "blocked"


@pytest.mark.parametrize(
    ("script", "code"),
    [
        ("#!/bin/sh\necho not-json\n", "ssh-response-invalid"),
        ("#!/bin/sh\necho '{}'\n", "ssh-response-invalid"),
        ("#!/bin/sh\necho 'Permission denied' >&2\nexit 255\n", "ssh-auth-failed"),
        (
            "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * 40000)\n",
            "ssh-output-too-large",
        ),
    ],
)
def test_bounded_ssh_response_failures(tmp_path: Path, script: str, code: str) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    fake_ssh.write_text(script)
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert error.value.code == code


def test_tunnel_origin_and_private_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llm_research_os.execution import native_ssh_live as live

    pack, identity, fake_ssh = _setup(tmp_path)
    tls = load_or_create_loopback_tls(tmp_path / "tls")
    credential = tmp_path / "credential.json"
    fields = {
        "controlPlaneUrl": "https://127.0.0.1:8844",
        "workerId": "worker.tunnel",
        "session": "secret-session",
        "tlsFingerprint": tls.fingerprint,
    }
    credential.write_text(json.dumps(fields))
    credential.chmod(0o600)
    seen = {}

    def exchange(argv, data, *, timeout):
        seen["argv"] = argv
        seen["payload"] = json.loads(data)
        return b'{"outcome":"ready"}', b"", 0

    monkeypatch.setattr(live, "_exchange", exchange)
    probe_ssh_pack(
        pack,
        identity_file=identity,
        operation="verify-worker",
        worker_credential=credential,
        ca_path=tls.cert_path,
        tunnel_port=9922,
        ssh_executable=str(fake_ssh),
    )
    assert "127.0.0.1:9922:127.0.0.1:8844" in seen["argv"]
    assert seen["payload"]["controlPlaneUrl"] == "https://127.0.0.1:9922"
    assert seen["payload"]["tlsFingerprint"] == tls.fingerprint
    assert "secret-session" not in " ".join(seen["argv"])
    for origin in [
        "http://127.0.0.1:8844",
        "https://example.com:8844",
        "https://127.0.0.1:bad",
        "https://127.0.0.1:8844/path",
    ]:
        credential.write_text(json.dumps(fields | {"controlPlaneUrl": origin}))
        with pytest.raises(NativeSshError) as error:
            probe_ssh_pack(
                pack,
                identity_file=identity,
                operation="verify-worker",
                worker_credential=credential,
                ca_path=tls.cert_path,
                tunnel_port=9922,
                ssh_executable=str(fake_ssh),
            )
        assert error.value.code == "ssh-tunnel-invalid"


def test_missing_wheelhouse_and_invalid_pack(tmp_path: Path) -> None:
    from llm_research_os.execution.native_ssh_live import _wheelhouse

    pack, identity, fake_ssh = _setup(tmp_path)
    with pytest.raises(NativeSshError):
        probe_ssh_pack(pack, identity_file=identity, tunnel_port=9922, ssh_executable=str(fake_ssh))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    with pytest.raises(NativeSshError):
        _wheelhouse(wheels)
    (wheels / "not-wheel.txt").write_text("no")
    with pytest.raises(NativeSshError):
        _wheelhouse(wheels)
    (pack / "STATUS.json").write_text("{}")
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert error.value.code == "ssh-pack-invalid"


def test_remote_prerequisite_and_tls_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    workdir = tmp_path / "worker"
    workdir.mkdir(mode=0o770)
    workdir.chmod(0o770)
    with pytest.raises(ValueError, match="workdir-permission"):
        remote._workdir(str(workdir))
    monkeypatch.setattr(remote.sys, "version_info", (3, 11))
    assert remote._probe(workdir, None)["code"] == "python-too-old"
    cert = "invalid certificate"
    assert (
        remote._worker_identity(
            {
                "controlPlaneUrl": "https://localhost:1",
                "workerId": "w",
                "session": "s",
                "caPem": cert,
                "tlsFingerprint": "sha256:" + hashlib.sha256(cert.encode()).hexdigest(),
            }
        )["code"]
        == "worker-tls-unavailable"
    )
    output = io.StringIO()
    monkeypatch.setattr(remote, "MAX_INPUT", 5)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"too-large-input")))
    monkeypatch.setattr(sys, "stdout", output)
    remote.main()
    assert json.loads(output.getvalue())["code"] == "input-too-large"


def test_ssh_timeout_and_missing_client(tmp_path: Path) -> None:
    from llm_research_os.execution.native_ssh_live import _exchange

    with pytest.raises(NativeSshError) as error:
        _exchange([str(tmp_path / "missing")], b"", timeout=1)
    assert error.value.code == "ssh-client-missing"
    with pytest.raises(NativeSshError) as error:
        _exchange(["/bin/sh", "-c", "sleep 5"], b"data", timeout=0)
    assert error.value.code == "ssh-timeout"


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        ("install", "wheelhouse-required"),
        ("verify-worker", "worker-credential-required"),
        ("invalid", "ssh-operation-invalid"),
    ],
)
def test_operation_prerequisites_refuse_before_connection(
    tmp_path: Path, operation: str, code: str
) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    fake_ssh.unlink()
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(
            pack, identity_file=identity, operation=operation, ssh_executable=str(fake_ssh)
        )
    assert error.value.code == code


@pytest.mark.parametrize("kind", ["public", "incomplete", "private-ca", "oversize", "symlink"])
def test_unsafe_worker_credentials_are_refused(tmp_path: Path, kind: str) -> None:
    from llm_research_os.execution.native_ssh_live import _worker_payload

    tls = load_or_create_loopback_tls(tmp_path / "tls")
    credential = tmp_path / "credential.json"
    credential.write_text(
        json.dumps(
            {
                "controlPlaneUrl": "https://localhost:8844",
                "workerId": "w",
                "session": "s",
                "tlsFingerprint": tls.fingerprint,
            }
        )
    )
    credential.chmod(0o600)
    ca = tls.cert_path
    if kind == "public":
        credential.chmod(0o644)
    elif kind == "incomplete":
        credential.write_text("{}")
    elif kind == "private-ca":
        ca = tmp_path / "private.pem"
        ca.write_text("-----BEGIN PRIVATE KEY-----")
    elif kind == "oversize":
        credential.write_text("x" * 5000)
    else:
        link = tmp_path / "link.json"
        link.symlink_to(credential)
        credential = link
    with pytest.raises(NativeSshError) as error:
        _worker_payload(credential, ca)
    assert error.value.code == "worker-credential-invalid"


def test_install_prerequisite_failure_removes_only_new_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    name = "llm_research_os-0.0.1-py3-none-any.whl"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zipped:
        zipped.writestr(name, b"wheel")
    payload = {
        "wheels": {name: hashlib.sha256(b"wheel").hexdigest()},
        "archive": base64.b64encode(data.getvalue()).decode(),
        "package": name,
    }

    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ensurepip")

    monkeypatch.setattr(remote.venv.EnvBuilder, "create", unavailable)
    marker = tmp_path / "unrelated"
    marker.write_text("preserve")
    assert remote._install(tmp_path, payload)["code"] == "install-failed"
    assert marker.read_text() == "preserve"
    assert list((tmp_path / ".researchos").iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "oversize"])
def test_pack_files_are_bounded_and_regular(tmp_path: Path, kind: str) -> None:
    pack, identity, fake_ssh = _setup(tmp_path)
    status = pack / "STATUS.json"
    if kind == "symlink":
        other = tmp_path / "status.json"
        status.rename(other)
        status.symlink_to(other)
    else:
        status.write_text("x" * 9000)
    with pytest.raises(NativeSshError) as error:
        probe_ssh_pack(pack, identity_file=identity, ssh_executable=str(fake_ssh))
    assert error.value.code == "ssh-pack-invalid"


def test_denied_group_cleanup_preserves_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from llm_research_os.execution import native_ssh_live as live

    def denied(*args):
        raise PermissionError("group signaling denied")

    monkeypatch.setattr(live.os, "killpg", denied)
    with pytest.raises(NativeSshError) as error:
        live._exchange([sys.executable, "-c", "import time; time.sleep(5)"], b"data", timeout=0)
    assert error.value.code == "ssh-timeout"
