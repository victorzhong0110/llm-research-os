from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

import llm_research_os.execution.native_ssh as ssh_module
from llm_research_os.cli import main
from llm_research_os.execution import NativeSshError, parse_ssh_target, write_native_ssh_pack
from llm_research_os.execution.native_ssh import NativeSshTarget

HOST_KEY = "ssh-ed25519:" + "A" * 68
PROJECT = "example-native"
SOURCE = "https://researchos.dev/projects/example-native"


def _target(**overrides: object) -> NativeSshTarget:
    fields: dict[str, object] = {
        "host": "192.0.2.10",
        "port": 22,
        "user": "researcher",
        "workdir": "/home/researcher/native",
        "host_key": HOST_KEY,
        "profile": "restricted-v0alpha1",
    }
    fields.update(overrides)
    return parse_ssh_target(
        host=fields["host"],
        port=fields["port"],
        user=fields["user"],
        workdir=fields["workdir"],
        host_key=fields["host_key"],
        profile=fields["profile"],
    )


def test_valid_target_round_trip() -> None:
    target = _target()
    assert target.host == "192.0.2.10"
    assert target.port == 22
    assert target.user == "researcher"
    assert target.workdir == "/home/researcher/native"
    assert target.profile == "restricted-v0alpha1"


def test_hostname_and_loopback_targets_are_valid() -> None:
    assert _target(host="worker.example.org").host == "worker.example.org"
    loopback = _target(host="127.0.0.1")
    assert loopback.host == "127.0.0.1"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("host", "", "ssh-host-invalid"),
        ("host", "0.0.0.0", "ssh-host-unspecified"),
        ("host", "::", "ssh-host-unspecified"),
        ("host", "user@host", "ssh-host-invalid"),
        ("host", "224.0.0.1", "ssh-host-invalid"),
        ("host", "-bad", "ssh-host-invalid"),
        ("host", "fe80::1%eth0\nProxyCommand x", "ssh-host-invalid"),
        ("host", "192.0.2.10;ProxyCommand=x", "ssh-host-invalid"),
        ("host", "192.0.2.10|nc", "ssh-host-invalid"),
        ("host", "host`id`", "ssh-host-invalid"),
        ("host", "host$(id)", "ssh-host-invalid"),
        ("host", None, "ssh-host-invalid"),
        ("port", 0, "ssh-port-invalid"),
        ("port", 70000, "ssh-port-invalid"),
        ("port", True, "ssh-port-invalid"),
        ("port", "22", "ssh-port-invalid"),
        ("user", "", "ssh-user-invalid"),
        ("user", "root", "ssh-user-forbidden"),
        ("user", "bad user", "ssh-user-invalid"),
        ("user", None, "ssh-user-invalid"),
        ("workdir", "/", "ssh-workdir-invalid"),
        ("workdir", "relative", "ssh-workdir-invalid"),
        ("workdir", "/tmp/../etc", "ssh-workdir-invalid"),
        ("workdir", "/home/a b", "ssh-workdir-invalid"),
        ("workdir", None, "ssh-workdir-invalid"),
        ("host_key", "", "ssh-host-key-missing"),
        ("host_key", "ssh-rsa:short", "ssh-host-key-invalid"),
        ("host_key", "unknown-type:AAAA", "ssh-host-key-invalid"),
        ("host_key", "ssh-ed25519:!!!", "ssh-host-key-invalid"),
        ("host_key", "PRIVATE KEY DATA", "ssh-host-key-invalid"),
        ("profile", "default", "ssh-profile-invalid"),
        ("profile", None, "ssh-profile-invalid"),
    ),
)
def test_invalid_targets_fail_closed(field: str, value: object, code: str) -> None:
    with pytest.raises(NativeSshError, match="ssh onboarding") as captured:
        _target(**{field: value})
    assert captured.value.code == code


def test_pack_is_pending_live_without_private_key(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    status = write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    assert status["crossMachine"] == "pending-live"
    assert status["transport"] == "ssh-pending"
    assert status["liveStatus"] == "pending-live"
    assert status["secondHost"] == "not-provisioned"
    assert status["privateKeyInPack"] is False
    assert (output / "STATUS.json").is_file()
    assert (output / "ONBOARDING.md").is_file()
    assert (output / "ACCEPTANCE.md").is_file()
    assert (output / "ssh_config.fragment").is_file()
    assert (output / "authorized_keys.fragment").is_file()
    assert (output / "ENVIRONMENT.json").is_file()
    assert (output / "known_hosts.native").is_file()
    config = (output / "ssh_config.fragment").read_text(encoding="utf-8")
    assert "PasswordAuthentication no" in config
    assert "ForwardAgent no" in config
    assert "BatchMode yes" in config
    assert "UserKnownHostsFile known_hosts.native" in config
    assert "GlobalKnownHostsFile /dev/null" in config
    assert "StrictHostKeyChecking yes" in config
    assert "PRIVATE" not in config.upper()
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known == f"192.0.2.10 ssh-ed25519 {'A' * 68}\n"
    onboarding = (output / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "known_hosts.native" in onboarding
    assert "hostKey" in onboarding
    authorized = (output / "authorized_keys.fragment").read_text(encoding="utf-8")
    assert "no-agent-forwarding" in authorized
    assert "PRIVATE" not in authorized.upper()
    for path in output.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "PRIVATE KEY" not in text


def test_pack_refuses_non_empty_output(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    output.mkdir()
    (output / "existing.txt").write_text("existing", encoding="utf-8")
    with pytest.raises(NativeSshError, match="not empty") as captured:
        write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    assert captured.value.code == "pack-exists"


def test_pack_rejects_invalid_project_and_source(tmp_path: Path) -> None:
    target = _target()
    with pytest.raises(NativeSshError, match="project is invalid") as captured:
        write_native_ssh_pack(tmp_path / "a", target, project_id="", source=SOURCE)
    assert captured.value.code == "ssh-project-invalid"
    with pytest.raises(NativeSshError, match="source is invalid") as captured:
        write_native_ssh_pack(tmp_path / "b", target, project_id=PROJECT, source="http://x")
    assert captured.value.code == "ssh-source-invalid"


def test_pack_never_dials_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"network called: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(socket, "socket", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    target = _target()
    status = write_native_ssh_pack(tmp_path / "pack", target, project_id=PROJECT, source=SOURCE)
    assert status["crossMachine"] == "pending-live"


def test_ssh_onboard_cli_writes_pack(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "pack"
    assert (
        main(
            [
                "native",
                "ssh-onboard",
                str(output),
                "--host",
                "192.0.2.10",
                "--user",
                "researcher",
                "--port",
                "2222",
                "--workdir",
                "/home/researcher/native",
                "--host-key",
                HOST_KEY,
                "--project",
                PROJECT,
                "--source",
                SOURCE,
                "--format",
                "json",
            ]
        )
        == 0
    )
    rendered = capsys.readouterr()
    assert rendered.err == ""
    status = json.loads(rendered.out)
    assert status["crossMachine"] == "pending-live"
    assert status["port"] == 2222
    assert (output / "STATUS.json").is_file()


def test_ssh_onboard_cli_text_labels_pending_live(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "pack"
    assert (
        main(
            [
                "native",
                "ssh-onboard",
                str(output),
                "--host",
                "192.0.2.10",
                "--user",
                "researcher",
                "--workdir",
                "/home/researcher/native",
                "--host-key",
                HOST_KEY,
                "--project",
                PROJECT,
                "--source",
                SOURCE,
                "--format",
                "text",
            ]
        )
        == 0
    )
    rendered = capsys.readouterr()
    assert "pending-live" in rendered.out
    assert "not-implemented" in rendered.out
    assert "researcher" in rendered.out


def test_ssh_onboard_cli_rejects_root_and_bad_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "native",
                "ssh-onboard",
                str(tmp_path / "a"),
                "--host",
                "192.0.2.10",
                "--user",
                "root",
                "--workdir",
                "/home/researcher/native",
                "--host-key",
                HOST_KEY,
                "--project",
                PROJECT,
                "--source",
                SOURCE,
                "--format",
                "json",
            ]
        )
        == 2
    )
    root_output = capsys.readouterr()
    assert root_output.out == ""
    assert "ssh-user-forbidden" in root_output.err
    assert (
        main(
            [
                "native",
                "ssh-onboard",
                str(tmp_path / "b"),
                "--host",
                "192.0.2.10",
                "--user",
                "researcher",
                "--workdir",
                "/home/researcher/native",
                "--host-key",
                "bad-key",
                "--project",
                PROJECT,
                "--source",
                SOURCE,
                "--format",
                "json",
            ]
        )
        == 2
    )
    key_output = capsys.readouterr()
    assert key_output.out == ""
    assert "ssh-host-key-invalid" in key_output.err


def test_target_is_frozen() -> None:
    target = _target()
    with pytest.raises(AttributeError):
        target.host = "other"  # type: ignore[misc]


def test_module_does_not_import_banned_clients() -> None:
    source = Path(ssh_module.__file__).read_text(encoding="utf-8")
    assert "import socket" not in source
    assert "import subprocess" not in source
    assert "paramiko" not in source


def test_host_injection_payloads_rejected() -> None:
    payloads = (
        "fe80::1%eth0\nProxyCommand x",
        "fe80::1%eth0\rProxyCommand x",
        "192.0.2.10;id",
        "192.0.2.10|ProxyCommand",
        "192.0.2.10&sleep",
        "host$(reboot)",
        "host`reboot`",
        'host"evil"',
        "host'evil'",
        "bad\\host",
    )
    for host in payloads:
        with pytest.raises(NativeSshError, match="host is invalid") as captured:
            _target(host=host)
        assert captured.value.code == "ssh-host-invalid"


def test_scoped_ipv6_with_safe_zone_accepted() -> None:
    target = _target(host="fe80::1%eth0")
    assert target.host == "fe80::1%eth0"


def test_scoped_ipv6_ssh_config_is_parseable(tmp_path: Path) -> None:
    target = _target(host="fe80::1%eth0")
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    fragment = output / "ssh_config.fragment"
    config = fragment.read_text(encoding="utf-8")
    assert "HostName fe80::1%%eth0\n" in config
    assert "HostName fe80::1%eth0\n" not in config
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known.startswith("fe80::1%eth0 ")
    ssh = shutil.which("ssh")
    if ssh is None:
        pytest.skip("ssh is not available")
    completed = subprocess.run(
        [ssh, "-G", "-F", str(fragment), "researchos-native"],
        check=False,
        capture_output=True,
        text=True,
        cwd=output,
    )
    assert completed.returncode == 0, completed.stderr
    assert "unknown key" not in completed.stderr
    assert "hostname fe80::1%eth0" in completed.stdout.lower()


def test_pack_writes_known_hosts_for_non_default_port(tmp_path: Path) -> None:
    target = _target(port=2222, host="2001:db8::10")
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known == f"[2001:db8::10]:2222 ssh-ed25519 {'A' * 68}\n"
    config = (output / "ssh_config.fragment").read_text(encoding="utf-8")
    assert "UserKnownHostsFile known_hosts.native" in config
    assert "GlobalKnownHostsFile /dev/null" in config


@pytest.mark.parametrize(
    ("key_prefix", "key_type"),
    (
        ("ssh-ed25519:", "ssh-ed25519"),
        ("ecdsa-sha2-nistp256:", "ecdsa-sha2-nistp256"),
        ("ecdsa-sha2-nistp384:", "ecdsa-sha2-nistp384"),
        ("ssh-rsa:", "ssh-rsa"),
    ),
)
def test_known_hosts_line_maps_every_accepted_key_type(
    tmp_path: Path, key_prefix: str, key_type: str
) -> None:
    target = _target(host_key=key_prefix + "A" * 68)
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known == f"192.0.2.10 {key_type} {'A' * 68}\n"


def test_known_hosts_brackets_hostname_on_non_default_port(tmp_path: Path) -> None:
    target = _target(port=2222, host="worker.example.org")
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known == f"[worker.example.org]:2222 ssh-ed25519 {'A' * 68}\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_key_material_pack_files_are_owner_only(tmp_path: Path) -> None:
    output = tmp_path / "pack"
    write_native_ssh_pack(output, _target(), project_id=PROJECT, source=SOURCE)
    assert stat.S_IMODE((output / "known_hosts.native").stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "ssh_config.fragment").stat().st_mode) == 0o600
