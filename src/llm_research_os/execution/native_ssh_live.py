"""Pinned SSH bootstrap with fixed remote code and bounded streams."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import time
import zipfile
from pathlib import Path
from typing import IO, Any, Literal, cast
from urllib.parse import urlsplit

from llm_research_os.execution.errors import NativeSshError
from llm_research_os.execution.native_ssh import NativeSshTarget, parse_ssh_target

MAX_WHEELHOUSE = 32 * 1024 * 1024
MAX_REPLY = 32 * 1024
MAX_STDERR = 8 * 1024


def probe_ssh_pack(
    pack: Path,
    *,
    identity_file: Path,
    operation: Literal["probe", "install", "verify-worker"] = "probe",
    wheel_dir: Path | None = None,
    worker_credential: Path | None = None,
    ca_path: Path | None = None,
    port: int | None = None,
    tunnel_port: int | None = None,
    ssh_executable: str | None = None,
) -> dict[str, Any]:
    """Probe or prepare one user-owned host without starting Worker tasks."""

    target, known_hosts = _read_pack(pack)
    identity = _private_identity(identity_file)
    if tunnel_port is not None and operation != "verify-worker":
        raise NativeSshError("tunnel is only for Worker verification", code="ssh-tunnel-invalid")
    payload: dict[str, object] = {"operation": operation, "workdir": target.workdir, "port": port}
    if operation == "install":
        if wheel_dir is None:
            raise NativeSshError("wheelhouse is required", code="wheelhouse-required")
        payload.update(_wheelhouse(wheel_dir))
    elif operation == "verify-worker":
        if worker_credential is None or ca_path is None:
            raise NativeSshError(
                "Worker credential and CA are required", code="worker-credential-required"
            )
        payload.update(_worker_payload(worker_credential, ca_path))
    elif operation != "probe":
        raise NativeSshError("SSH operation is invalid", code="ssh-operation-invalid")
    executable = ssh_executable or shutil.which("ssh")
    if executable is None:
        raise NativeSshError("OpenSSH client is missing", code="ssh-client-missing")
    remote_source = Path(__file__).with_name("native_ssh_remote.py").read_text(encoding="utf-8")
    # OpenSSH passes its last argument to a remote shell. The command is wholly
    # fixed program text; target, credentials and package bytes travel on stdin.
    command = "python3 -I -c " + shlex.quote(remote_source)
    tunnel: list[str] = []
    if tunnel_port is not None:
        if type(tunnel_port) is not int or not 1 <= tunnel_port <= 65535:
            raise NativeSshError("tunnel port is invalid", code="ssh-tunnel-invalid")
        try:
            url = urlsplit(str(payload["controlPlaneUrl"]))
            local_port = url.port
            valid = (
                url.scheme == "https"
                and url.hostname in {"127.0.0.1", "localhost"}
                and local_port is not None
                and url.path in {"", "/"}
                and not (url.username or url.password or url.query or url.fragment)
            )
        except ValueError:
            valid = False
        if not valid:
            raise NativeSshError(
                "tunnel requires a local HTTPS Worker origin", code="ssh-tunnel-invalid"
            )
        payload["controlPlaneUrl"] = f"https://{url.hostname}:{tunnel_port}"
        tunnel = [
            "-o",
            "ExitOnForwardFailure=yes",
            "-R",
            f"127.0.0.1:{tunnel_port}:127.0.0.1:{local_port}",
        ]
    argv = [
        executable,
        "-F",
        "/dev/null",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes" if not tunnel else "ClearAllForwardings=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
        "-i",
        str(identity),
        "-p",
        str(target.port),
        "-l",
        target.user,
        *tunnel,
        "--",
        target.host,
        command,
    ]
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    if len(data) > 48 * 1024 * 1024:
        raise NativeSshError("SSH input exceeds limit", code="ssh-input-too-large")
    stdout, stderr, code = _exchange(argv, data, timeout=150 if operation == "install" else 25)
    if code != 0:
        detail = stderr.decode(errors="replace").lower()
        reason = (
            "ssh-host-key-changed"
            if "host key verification failed" in detail
            or "remote host identification has changed" in detail
            else "ssh-auth-failed"
            if "permission denied" in detail
            else "ssh-tunnel-failed"
            if "remote port forwarding failed" in detail
            else "ssh-disconnected"
        )
        raise NativeSshError("SSH connection or remote probe failed", code=reason)
    try:
        result = json.loads(stdout)
    except ValueError:
        raise NativeSshError(
            "remote probe returned invalid JSON", code="ssh-response-invalid"
        ) from None
    if type(result) is not dict or result.get("outcome") not in {"ready", "blocked"}:
        raise NativeSshError("remote probe returned invalid outcome", code="ssh-response-invalid")
    return result


def _read_pack(pack: Path) -> tuple[NativeSshTarget, Path]:
    status_path = pack / "STATUS.json"
    known_hosts = pack / "known_hosts.native"
    if pack.is_symlink() or status_path.is_symlink() or known_hosts.is_symlink():
        raise NativeSshError("SSH pack contains a symlink", code="ssh-pack-invalid")
    try:
        if status_path.stat().st_size > 8192 or known_hosts.stat().st_size > 2048:
            raise NativeSshError("SSH pack is too large", code="ssh-pack-invalid")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if type(status) is not dict or status.get("kind") != "NativeSshOnboardingPack":
            raise ValueError("invalid status")
        target = parse_ssh_target(
            host=status.get("host"),
            port=status.get("port"),
            user=status.get("user"),
            workdir=status.get("workdir"),
            host_key=status.get("hostKey"),
            profile=status.get("profile"),
        )
        key_type, key_body = target.host_key.split(":", 1)
        marker = target.host if target.port == 22 else f"[{target.host}]:{target.port}"
        if known_hosts.read_text(encoding="utf-8") != f"{marker} {key_type} {key_body}\n":
            raise NativeSshError("pinned host key differs from pack", code="ssh-host-key-changed")
    except NativeSshError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        raise NativeSshError("SSH pack is missing or invalid", code="ssh-pack-invalid") from exc
    return target, known_hosts.resolve(strict=True)


def _private_identity(path: Path) -> Path:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("not a regular identity")
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise OSError("identity is not private")
        return path.resolve(strict=True)
    except OSError:
        raise NativeSshError(
            "SSH identity must be a private user-owned file", code="ssh-identity-invalid"
        ) from None


def _wheelhouse(directory: Path) -> dict[str, object]:
    if directory.is_symlink() or not directory.is_dir():
        raise NativeSshError("wheelhouse is invalid", code="wheelhouse-invalid")
    paths = sorted(directory.iterdir())
    if not 1 <= len(paths) <= 32:
        raise NativeSshError("wheelhouse count is invalid", code="wheelhouse-invalid")
    buffer = io.BytesIO()
    manifest: dict[str, str] = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in paths:
            if path.is_symlink() or not path.is_file() or not path.name.endswith(".whl"):
                raise NativeSshError(
                    "wheelhouse contains an invalid file", code="wheelhouse-invalid"
                )
            if path.stat().st_size > 16 * 1024 * 1024:
                raise NativeSshError("wheel exceeds size limit", code="wheelhouse-too-large")
            data = path.read_bytes()
            manifest[path.name] = hashlib.sha256(data).hexdigest()
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
            if buffer.tell() > MAX_WHEELHOUSE:
                raise NativeSshError("wheelhouse exceeds size limit", code="wheelhouse-too-large")
    package = next(
        (
            name
            for name in manifest
            if name.startswith("llm_research_os-") and name.endswith(".whl")
        ),
        None,
    )
    if package is None:
        raise NativeSshError("llm-research-os wheel is missing", code="wheelhouse-invalid")
    return {
        "wheels": manifest,
        "archive": base64.b64encode(buffer.getvalue()).decode(),
        "package": package,
    }


def _worker_payload(credential: Path, ca_path: Path) -> dict[str, object]:
    if credential.is_symlink() or ca_path.is_symlink():
        raise NativeSshError("Worker credential path is invalid", code="worker-credential-invalid")
    try:
        details = credential.stat()
        if details.st_uid != os.getuid() or details.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("credential is not private")
        if credential.stat().st_size > 4096 or ca_path.stat().st_size > 16384:
            raise ValueError("oversized credential")
        document = json.loads(credential.read_text(encoding="utf-8"))
        pem = ca_path.read_text(encoding="ascii")
        if type(document) is not dict or not all(
            isinstance(document.get(key), str) and document[key]
            for key in ("controlPlaneUrl", "workerId", "session", "tlsFingerprint")
        ):
            raise ValueError("incomplete credential")
        if "PRIVATE KEY" in pem or not pem.startswith("-----BEGIN CERTIFICATE-----"):
            raise ValueError("invalid CA")
        if "sha256:" + hashlib.sha256(pem.encode()).hexdigest() != document["tlsFingerprint"]:
            raise ValueError("CA fingerprint mismatch")
    except (OSError, UnicodeError, ValueError) as exc:
        raise NativeSshError(
            "Worker credential or CA is invalid", code="worker-credential-invalid"
        ) from exc
    return {
        key: document[key] for key in ("controlPlaneUrl", "workerId", "session", "tlsFingerprint")
    } | {"caPem": pem}


def _exchange(argv: list[str], data: bytes, *, timeout: int) -> tuple[bytes, bytes, int]:
    try:
        child = subprocess.Popen(  # noqa: S603 - fixed OpenSSH command with validated target
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        raise NativeSshError("could not start OpenSSH", code="ssh-client-missing") from None
    if child.stdin is None or child.stdout is None or child.stderr is None:
        child.kill()
        raise NativeSshError("SSH pipes are unavailable", code="ssh-io-failed")
    streams = (child.stdin, child.stdout, child.stderr)
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    output = bytearray()
    errors = bytearray()
    offset = 0
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(child.stdin, selectors.EVENT_WRITE)
    selector.register(child.stdout, selectors.EVENT_READ)
    selector.register(child.stderr, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise NativeSshError("SSH operation timed out", code="ssh-timeout")
            for key, _ in selector.select(timeout=min(0.2, deadline - time.monotonic())):
                stream = cast(IO[bytes], key.fileobj)
                if stream is child.stdin:
                    try:
                        written = os.write(child.stdin.fileno(), data[offset : offset + 65536])
                    except BlockingIOError:
                        written = 0
                    except BrokenPipeError:
                        selector.unregister(child.stdin)
                        child.stdin.close()
                        continue
                    offset += written
                    if offset == len(data) and not child.stdin.closed:
                        selector.unregister(child.stdin)
                        child.stdin.close()
                else:
                    chunk = os.read(stream.fileno(), 8192)
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                    else:
                        target = output if stream is child.stdout else errors
                        target.extend(chunk)
                        if len(target) > (MAX_REPLY if stream is child.stdout else MAX_STDERR):
                            raise NativeSshError(
                                "SSH output exceeds limit", code="ssh-output-too-large"
                            )
        return bytes(output), bytes(errors), child.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeSshError("SSH connection failed", code="ssh-disconnected") from exc
    finally:
        selector.close()
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except OSError:
                # The direct child is ours; a denied group signal must not
                # mask the original timeout/output failure.
                with contextlib.suppress(OSError):
                    child.kill()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                child.wait(timeout=5)
        for stream in streams:
            if not stream.closed:
                stream.close()
