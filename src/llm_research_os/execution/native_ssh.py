"""Validated SSH onboarding target and pending-live pack (M3 slice 1).

This module never opens a socket, runs ssh, or writes a private key. It
validates a restricted onboarding shape and writes a runnable checklist pack
whose STATUS stays ``pending-live`` until a researcher provisions a host.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from llm_research_os.execution.errors import NativeSshError
from llm_research_os.execution.native_identity import (
    is_native_runtime_profile,
)

NATIVE_SSH_PROFILE: Literal["restricted-v0alpha1"] = "restricted-v0alpha1"
NATIVE_SSH_API_VERSION: Literal["researchos.dev/v0alpha1"] = "researchos.dev/v0alpha1"
NATIVE_SSH_TRANSPORT: Literal["ssh-pending"] = "ssh-pending"

_HOST_KEY_TYPES = (
    "ssh-ed25519:",
    "ecdsa-sha2-nistp256:",
    "ecdsa-sha2-nistp384:",
    "ssh-rsa:",
)
_HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/=]{44,512}$")
_PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_LIVE_STEPS = (
    "connect",
    "workdir",
    "restricted-command",
    "cancel",
)


@dataclass(frozen=True, slots=True)
class NativeSshTarget:
    """Validated restricted SSH onboarding target without key material."""

    host: str
    port: int
    user: str
    workdir: str
    host_key: str
    profile: str


def parse_ssh_target(
    *,
    host: object,
    port: object,
    user: object,
    workdir: object,
    host_key: object,
    profile: object = NATIVE_SSH_PROFILE,
) -> NativeSshTarget:
    """Validate a restricted onboarding target without dialing a network."""

    clean_host = _require_host(host)
    clean_port = _require_port(port)
    clean_user = _require_user(user)
    clean_workdir = _require_workdir(workdir)
    clean_key = _require_host_key(host_key)
    clean_profile = profile if type(profile) is str else ""
    if not is_native_runtime_profile(clean_profile):
        raise NativeSshError(
            "ssh onboarding profile is invalid",
            code="ssh-profile-invalid",
        )
    return NativeSshTarget(
        host=clean_host,
        port=clean_port,
        user=clean_user,
        workdir=clean_workdir,
        host_key=clean_key,
        profile=clean_profile,
    )


def write_native_ssh_pack(
    output: Path,
    target: NativeSshTarget,
    *,
    project_id: str,
    source: str,
    include_web: bool = False,
) -> dict[str, Any]:
    """Write a pending-live onboarding pack without contacting the host."""

    if type(target) is not NativeSshTarget:
        raise NativeSshError("ssh onboarding target is invalid", code="ssh-target-invalid")
    if type(project_id) is not str or _PROJECT_PATTERN.fullmatch(project_id) is None:
        raise NativeSshError("ssh onboarding project is invalid", code="ssh-project-invalid")
    if type(source) is not str or not source.startswith("https://") or " " in source:
        raise NativeSshError("ssh onboarding source is invalid", code="ssh-source-invalid")
    if not isinstance(output, Path):
        raise NativeSshError("ssh onboarding output is invalid", code="ssh-output-invalid")
    if output.exists() and any(output.iterdir()):
        raise NativeSshError(
            "ssh onboarding output directory is not empty",
            code="pack-exists",
        )
    output.mkdir(parents=True, exist_ok=True)
    status = _status_document(target, project_id=project_id, source=source)
    web_page: str | None = None
    if include_web:
        from llm_research_os.execution.native_web import write_onboarding_page

        web_page = write_onboarding_page(output, target, project_id=project_id, source=source)
    status["webPage"] = web_page
    # NOTE: the web writer is imported lazily because native_web renders
    # these fragments and therefore imports this module back.
    (output / "STATUS.json").write_text(
        json.dumps(status, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "ENVIRONMENT.json").write_text(
        json.dumps(_environment_document(target), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (output / "ONBOARDING.md").write_text(_onboarding_markdown(target), encoding="utf-8")
    (output / "ACCEPTANCE.md").write_text(_acceptance_markdown(), encoding="utf-8")
    config_path = output / "ssh_config.fragment"
    config_path.write_text(_ssh_config_fragment(target), encoding="utf-8")
    os.chmod(config_path, _PRIVATE_FILE_MODE)
    (output / "authorized_keys.fragment").write_text(_authorized_keys_fragment(), encoding="utf-8")
    return status


def ssh_config_fragment(target: NativeSshTarget) -> str:
    """Return the pending-live client config fragment for one target."""

    if type(target) is not NativeSshTarget:
        raise NativeSshError("ssh onboarding target is invalid", code="ssh-target-invalid")
    return _ssh_config_fragment(target)


def authorized_keys_fragment() -> str:
    """Return the restricted authorized_keys prefix with a key placeholder."""

    return _authorized_keys_fragment()


def _require_host(host: object) -> str:
    if type(host) is not str or host == "":
        raise NativeSshError("ssh onboarding host is invalid", code="ssh-host-invalid")
    if host in {"0.0.0.0", "::", "*"}:  # noqa: S104
        raise NativeSshError(
            "ssh onboarding host is unspecified",
            code="ssh-host-unspecified",
        )
    if any(token in host for token in ("@", "/", "?", "#", " ")):
        raise NativeSshError("ssh onboarding host is invalid", code="ssh-host-invalid")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or "\\" in host or host.startswith("-") or ".." in host:
            raise NativeSshError(
                "ssh onboarding host is invalid", code="ssh-host-invalid"
            ) from None
        if _HOSTNAME_PATTERN.fullmatch(host) is None:
            raise NativeSshError(
                "ssh onboarding host is invalid", code="ssh-host-invalid"
            ) from None
        return host
    if ip.is_unspecified:
        raise NativeSshError(
            "ssh onboarding host is unspecified",
            code="ssh-host-unspecified",
        )
    if ip.is_multicast or (ip.is_reserved and not ip.is_loopback):
        raise NativeSshError("ssh onboarding host is invalid", code="ssh-host-invalid")
    return host


def _require_port(port: object) -> int:
    if type(port) is not int or isinstance(port, bool):
        raise NativeSshError("ssh onboarding port is invalid", code="ssh-port-invalid")
    if not 1 <= port <= 65535:
        raise NativeSshError("ssh onboarding port is invalid", code="ssh-port-invalid")
    return port


def _require_user(user: object) -> str:
    if type(user) is not str or _USER_PATTERN.fullmatch(user) is None:
        raise NativeSshError("ssh onboarding user is invalid", code="ssh-user-invalid")
    if user == "root":
        raise NativeSshError(
            "ssh onboarding user must not be root",
            code="ssh-user-forbidden",
        )
    return user


def _require_workdir(workdir: object) -> str:
    if type(workdir) is not str:
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    if len(workdir) < 2 or len(workdir) > 256 or not workdir.startswith("/"):
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    if workdir == "/":
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    if any(token in workdir for token in ("\n", "\r", "\x00", "~", " ")):
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    segments = workdir.split("/")[1:]
    if any(segment in {"", ".", ".."} for segment in segments):
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    if any(re.fullmatch(r"[A-Za-z0-9._-]{1,64}", segment) is None for segment in segments):
        raise NativeSshError("ssh onboarding workdir is invalid", code="ssh-workdir-invalid")
    return workdir


def _require_host_key(host_key: object) -> str:
    if type(host_key) is not str or host_key == "":
        raise NativeSshError(
            "ssh onboarding host key is missing",
            code="ssh-host-key-missing",
        )
    if "PRIVATE" in host_key.upper():
        raise NativeSshError("ssh onboarding host key is invalid", code="ssh-host-key-invalid")
    prefix = next((item for item in _HOST_KEY_TYPES if host_key.startswith(item)), None)
    if prefix is None:
        raise NativeSshError("ssh onboarding host key is invalid", code="ssh-host-key-invalid")
    body = host_key[len(prefix) :]
    if type(body) is not str or _BASE64_PATTERN.fullmatch(body) is None:
        raise NativeSshError("ssh onboarding host key is invalid", code="ssh-host-key-invalid")
    try:
        base64.b64decode(body, validate=True)
    except (ValueError, binascii.Error):
        raise NativeSshError(
            "ssh onboarding host key is invalid", code="ssh-host-key-invalid"
        ) from None
    return host_key


def _status_document(target: NativeSshTarget, *, project_id: str, source: str) -> dict[str, Any]:
    loopback = target.host in {"127.0.0.1", "::1", "localhost"}
    key_type = target.host_key.split(":", 1)[0]
    return {
        "apiVersion": NATIVE_SSH_API_VERSION,
        "kind": "NativeSshOnboardingPack",
        "crossMachine": "pending-live",
        "transport": NATIVE_SSH_TRANSPORT,
        "liveStatus": "pending-live",
        "secondHost": "not-provisioned",
        "profile": target.profile,
        "host": target.host,
        "port": target.port,
        "user": target.user,
        "workdir": target.workdir,
        "hostKeyType": key_type,
        "hostKey": target.host_key,
        "loopbackIsNotCrossMachine": True,
        "binding": "loopback-not-cross-machine" if loopback else "ssh-pending-live",
        "projectId": project_id,
        "source": source,
        "sharedRootsForbidden": True,
        "privateKeyInPack": False,
        "liveSteps": list(_LIVE_STEPS),
    }


def _environment_document(target: NativeSshTarget) -> dict[str, Any]:
    return {
        "apiVersion": NATIVE_SSH_API_VERSION,
        "kind": "NativeSshEnvironment",
        "crossMachine": "pending-live",
        "secondHost": "not-provisioned",
        "profile": target.profile,
        "transport": NATIVE_SSH_TRANSPORT,
        "host": target.host,
        "port": target.port,
        "user": target.user,
        "workdir": target.workdir,
        "privateKey": "forbidden",
        "passwordAuthentication": "forbidden",
        "agentForwarding": "forbidden",
        "liveSteps": list(_LIVE_STEPS),
    }


def _onboarding_markdown(target: NativeSshTarget) -> str:
    return (
        "# Native SSH onboarding (pending-live)\n\n"
        "This pack does not dial SSH and does not prove a second host. "
        "Live verification stays `pending-live` until a researcher provisions one.\n\n"
        f"Target user and host are recorded in STATUS.json. Workdir is `{target.workdir}`. "
        "Profile is `restricted-v0alpha1`: no root login, no password, no agent "
        "forwarding, one isolated workdir, bounded wall time and output.\n\n"
        "1. Generate a dedicated key on the operator machine:\n\n"
        "   ```bash\n"
        "   ssh-keygen -t ed25519 -f ~/.ssh/researchos_native_ed25519 -C researchos-native\n"
        "   ```\n\n"
        "   Never copy the private key into this pack or the repository.\n\n"
        "2. Pin the host key before first use:\n\n"
        "   ```bash\n"
        "   ssh-keyscan -t ed25519 -p "
        f"{target.port} {target.host} | tee known_hosts.native\n"
        "   ```\n\n"
        "   Compare the output with the `hostKey` in STATUS.json. Abort on mismatch.\n\n"
        "3. Provision the isolated workdir on the target host and append\n"
        "   `authorized_keys.fragment` for the dedicated public key only. Keep the\n"
        "   `command=` prefix, `no-agent-forwarding`, `no-X11-forwarding`, `no-pty`,\n"
        "   and `no-port-forwarding` options.\n\n"
        "4. Copy `ssh_config.fragment` and connect once with batch mode:\n\n"
        "   ```bash\n"
        "   ssh -F ssh_config.fragment researchos-native true\n"
        "   ```\n\n"
        "5. SSH transport execution stays `ssh-transport-not-implemented` in this\n"
        "   slice. `researchos native run --transport ssh` must fail closed. Do not\n"
        "   treat onboarding as a live run.\n"
    )


def _acceptance_markdown() -> str:
    return (
        "# Native SSH acceptance (pending-live)\n\n"
        "This pack is runnable as a checklist. It is **not** a live two-host proof.\n\n"
        "Pending live steps after a researcher names a second host:\n\n"
        "1. Connect in batch mode with the pinned host key.\n"
        "2. Show the isolated workdir exists and is not `/` or `/tmp`.\n"
        "3. Run only the restricted command prefix from `authorized_keys.fragment`.\n"
        "4. Cancel then observe stop; unknown stays unknown.\n\n"
        "Loopback targets are `loopback-not-cross-machine`. Paid cloud, public\n"
        "service, and plugin isolation remain out of scope for this slice.\n"
    )


def _ssh_config_fragment(target: NativeSshTarget) -> str:
    return (
        "# Native SSH fragment (pending-live). Do not add keys here.\n"
        "Host researchos-native\n"
        f"    HostName {target.host}\n"
        f"    User {target.user}\n"
        f"    Port {target.port}\n"
        "    IdentityFile ~/.ssh/researchos_native_ed25519\n"
        "    PasswordAuthentication no\n"
        "    ChallengeResponseAuthentication no\n"
        "    ForwardAgent no\n"
        "    ForwardX11 no\n"
        "    StrictHostKeyChecking yes\n"
        "    BatchMode yes\n"
    )


def _authorized_keys_fragment() -> str:
    return (
        "# Restricted prefix for the dedicated public key only. Replace the\n"
        "# placeholder with one `ssh-ed25519 AAAA... comment` line.\n"
        'command="researchos-native-run --profile restricted-v0alpha1",'
        "no-agent-forwarding,no-X11-forwarding,no-pty,no-port-forwarding "
        "ssh-ed25519 REPLACE-WITH-DEDICATED-PUBLIC-KEY\n"
    )
