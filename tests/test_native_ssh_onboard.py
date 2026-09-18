from __future__ import annotations

import ipaddress
import json
import re
import shutil
import socket
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
_ZONE_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_IFACE_HEADER = re.compile(r"^(\S+):\s")
_INET6_LINE = re.compile(r"\binet6\s+(\S+)")
_IP_IFACE = re.compile(r"^\d+:\s+([^:@\s]+)")


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


def _valid_zone(name: str) -> bool:
    return _ZONE_RE.fullmatch(name) is not None


def _is_loopback_zone(name: str) -> bool:
    return name == "lo" or name.startswith("lo")


def _indexed_zones() -> list[str]:
    try:
        return [name for _index, name in socket.if_nameindex() if _valid_zone(name)]
    except OSError:
        return []


def _split_inet6_token(token: str) -> tuple[str, str | None]:
    address = token.split("/", 1)[0]
    if "%" not in address:
        return address, None
    raw, zone = address.split("%", 1)
    return raw, zone


def _parse_proc_if_inet6(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        raw, name = parts[0], parts[5]
        if not _valid_zone(name):
            continue
        try:
            addr = ipaddress.IPv6Address(bytes.fromhex(raw))
        except ValueError:
            continue
        if addr.is_link_local:
            found.append((str(addr), name))
    return found


def _parse_ifconfig_inet6(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    current: str | None = None
    for line in text.splitlines():
        header = _IFACE_HEADER.match(line)
        if header is not None:
            current = header.group(1)
            continue
        match = _INET6_LINE.search(line)
        if match is None:
            continue
        raw, zone = _split_inet6_token(match.group(1))
        try:
            addr = ipaddress.IPv6Address(raw)
        except ValueError:
            continue
        name = zone if zone is not None and _valid_zone(zone) else current
        if name is None or not _valid_zone(name) or not addr.is_link_local:
            continue
        found.append((str(addr), name))
    return found


def _parse_ip_addr_inet6(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    current: str | None = None
    for line in text.splitlines():
        header = _IP_IFACE.match(line)
        if header is not None:
            current = header.group(1)
            continue
        match = _INET6_LINE.search(line)
        if match is None or current is None:
            continue
        raw, zone = _split_inet6_token(match.group(1))
        try:
            addr = ipaddress.IPv6Address(raw)
        except ValueError:
            continue
        name = zone if zone is not None and _valid_zone(zone) else current
        if not _valid_zone(name) or not addr.is_link_local:
            continue
        found.append((str(addr), name))
    return found


def _read_text_if_present(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="ascii", errors="replace")


def _command_stdout(argv: list[str]) -> str | None:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout


def _link_local_pairs() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    proc_text = _read_text_if_present(Path("/proc/net/if_inet6"))
    if proc_text is not None:
        found.extend(_parse_proc_if_inet6(proc_text))
    ifconfig = shutil.which("ifconfig")
    if ifconfig is not None:
        text = _command_stdout([ifconfig, "-a"]) or _command_stdout([ifconfig])
        if text is not None:
            found.extend(_parse_ifconfig_inet6(text))
    ip_bin = shutil.which("ip")
    if ip_bin is not None:
        text = _command_stdout([ip_bin, "-6", "addr", "show"])
        if text is not None:
            found.extend(_parse_ip_addr_inet6(text))
    unique: list[tuple[str, str]] = []
    for pair in found:
        if pair not in unique:
            unique.append(pair)
    return unique


def _usable_scoped_ipv6_host() -> str | None:
    indexed = _indexed_zones()
    indexed_set = set(indexed)
    pairs = [
        pair
        for pair in _link_local_pairs()
        if not indexed_set or pair[1] in indexed_set
    ]
    preferred = [pair for pair in pairs if not _is_loopback_zone(pair[1])]
    loopback = [pair for pair in pairs if _is_loopback_zone(pair[1])]
    chosen = preferred or loopback
    if chosen:
        address, zone = chosen[0]
        return f"{address}%{zone}"
    names = [name for name in indexed if not _is_loopback_zone(name)] or indexed
    if not names:
        return None
    return f"fe80::1%{names[0]}"


def _ssh_g_hostname(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.lower().startswith("hostname "):
            return line.split(None, 1)[1].strip()
    raise AssertionError(f"ssh -G did not print hostname:\n{stdout}")


def _zone_index(zone: str) -> int | None:
    if zone.isdigit():
        try:
            return socket.if_nametoindex(socket.if_indextoname(int(zone)))
        except (OSError, OverflowError, ValueError):
            try:
                return int(zone)
            except ValueError:
                return None
    try:
        return socket.if_nametoindex(zone)
    except OSError:
        return None


def _is_openssh_normalized_scoped_host(dumped: str, host: str) -> bool:
    if host.count("%") != 1:
        return False
    expected_raw, expected_zone = host.split("%", 1)
    try:
        expected_ip = ipaddress.IPv6Address(expected_raw)
    except ValueError:
        return False
    dumped_raw = dumped
    dumped_zone: str | None = None
    if "%" in dumped:
        dumped_raw, dumped_zone = dumped.split("%", 1)
    try:
        dumped_ip = ipaddress.IPv6Address(dumped_raw)
    except ValueError:
        return False
    if dumped_ip != expected_ip:
        return False
    if dumped_zone is None:
        # Apple ssh -G may drop the zone after a successful parse.
        return True
    if dumped_zone == expected_zone:
        return True
    left = _zone_index(dumped_zone)
    right = _zone_index(expected_zone)
    return left is not None and left == right


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


def test_scoped_ipv6_ssh_config_percent_escapes(tmp_path: Path) -> None:
    target = _target(host="fe80::1%eth0")
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    config = (output / "ssh_config.fragment").read_text(encoding="utf-8")
    assert "HostName fe80::1%%eth0\n" in config
    assert "HostName fe80::1%eth0\n" not in config
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known.startswith("fe80::1%eth0 ")


def test_openssh_hostname_normalization_accepts_zone_or_bare_address() -> None:
    assert _is_openssh_normalized_scoped_host("fe80::1%eth0", "fe80::1%eth0")
    assert _is_openssh_normalized_scoped_host("fe80::1", "fe80::1%eth0")
    assert _is_openssh_normalized_scoped_host("FE80:0:0:0:0:0:0:1", "fe80::1%en0")
    assert not _is_openssh_normalized_scoped_host("fe80::2", "fe80::1%eth0")
    assert not _is_openssh_normalized_scoped_host("192.0.2.10", "fe80::1%eth0")


def test_link_local_parsers_read_linux_and_macos_ifconfig() -> None:
    linux = (
        "lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n"
        "        inet6 ::1  prefixlen 128  scopeid 0x10<host>\n"
        "enp0s3: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n"
        "        inet6 fe80::802b:38ff:fe3d:bcd0  prefixlen 64  scopeid 0x20<link>\n"
    )
    macos = (
        "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n"
        "\tinet6 ::1 prefixlen 128\n"
        "\tinet6 fe80::1%lo0 prefixlen 64 scopeid 0x1\n"
        "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
        "\tinet6 fe80::aede:48ff:fe00:1122%en0 prefixlen 64 scopeid 0x4\n"
    )
    proc = (
        "00000000000000000000000000000001 01 80 10 80       lo\n"
        "fe80000000000000802b38fffe3dbcd0 02 40 20 80   enp0s3\n"
    )
    assert _parse_ifconfig_inet6(linux) == [
        ("fe80::802b:38ff:fe3d:bcd0", "enp0s3"),
    ]
    assert _parse_ifconfig_inet6(macos) == [
        ("fe80::1", "lo0"),
        ("fe80::aede:48ff:fe00:1122", "en0"),
    ]
    assert _parse_proc_if_inet6(proc) == [
        ("fe80::802b:38ff:fe3d:bcd0", "enp0s3"),
    ]
    ip_text = (
        "1: lo: <LOOPBACK,UP,LOWER_UP>\n"
        "    inet6 ::1/128 scope host\n"
        "2: enp0s3: <BROADCAST,MULTICAST,UP,LOWER_UP>\n"
        "    inet6 fe80::802b:38ff:fe3d:bcd0/64 scope link\n"
    )
    assert _parse_ip_addr_inet6(ip_text) == [
        ("fe80::802b:38ff:fe3d:bcd0", "enp0s3"),
    ]


def test_usable_scoped_ipv6_host_uses_an_existing_zone() -> None:
    host = _usable_scoped_ipv6_host()
    if host is None:
        pytest.skip("no usable IPv6 link-local interface")
    assert host.count("%") == 1
    address, zone = host.split("%", 1)
    ipaddress.IPv6Address(address)
    assert _valid_zone(zone)
    names = {name for _index, name in socket.if_nameindex()}
    assert zone in names


def test_scoped_ipv6_ssh_config_is_parseable(tmp_path: Path) -> None:
    synthetic = _target(host="fe80::1%eth0")
    unit_output = tmp_path / "unit"
    write_native_ssh_pack(unit_output, synthetic, project_id=PROJECT, source=SOURCE)
    unit_config = (unit_output / "ssh_config.fragment").read_text(encoding="utf-8")
    assert "HostName fe80::1%%eth0\n" in unit_config
    assert "HostName fe80::1%eth0\n" not in unit_config

    host = _usable_scoped_ipv6_host()
    if host is None:
        pytest.skip("no usable IPv6 link-local interface")
    target = _target(host=host)
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    fragment = output / "ssh_config.fragment"
    config = fragment.read_text(encoding="utf-8")
    escaped = host.replace("%", "%%")
    assert f"HostName {escaped}\n" in config
    assert f"HostName {host}\n" not in config
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known.startswith(f"{host} ")
    ssh = shutil.which("ssh")
    if ssh is None:
        pytest.skip("ssh is not available")
    completed = subprocess.run(
        [ssh, "-n", "-G", "-F", str(fragment), "researchos-native"],
        check=False,
        capture_output=True,
        text=True,
        cwd=output,
        stdin=subprocess.DEVNULL,
    )
    assert completed.returncode == 0, completed.stderr
    assert "unknown key" not in completed.stderr.lower()
    dumped = _ssh_g_hostname(completed.stdout)
    # Linux OpenSSH reprints addr%zone. Apple ssh -G may drop the zone
    # after a successful parse; that is not a live connection.
    assert _is_openssh_normalized_scoped_host(dumped, host), (
        f"ssh -G hostname {dumped!r} is not a normalization of {host!r}"
    )


def test_pack_writes_known_hosts_for_non_default_port(tmp_path: Path) -> None:
    target = _target(port=2222, host="2001:db8::10")
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    known = (output / "known_hosts.native").read_text(encoding="utf-8")
    assert known == f"[2001:db8::10]:2222 ssh-ed25519 {'A' * 68}\n"
    config = (output / "ssh_config.fragment").read_text(encoding="utf-8")
    assert "UserKnownHostsFile known_hosts.native" in config
    assert "GlobalKnownHostsFile /dev/null" in config
