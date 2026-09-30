"""Fixed stdin-only SSH bootstrap program; executed with remote Python -I."""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import io
import json
import os
import platform
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import venv
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

MAX_INPUT = 48 * 1024 * 1024
MIN_FREE = 100 * 1024 * 1024


def _fail(code: str, repair: str) -> dict[str, object]:
    return {"outcome": "blocked", "code": code, "repair": repair}


def _workdir(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.startswith("/") or raw == "/":
        raise ValueError("workdir-invalid")
    path = Path(raw)
    if any(part in {".", ".."} for part in path.parts) or path.is_symlink():
        raise ValueError("workdir-invalid")
    if not path.is_dir() or path.resolve() != path:
        raise ValueError("workdir-missing")
    details = path.stat()
    if details.st_uid != os.getuid() or not os.access(path, os.W_OK | os.X_OK):
        raise ValueError("workdir-permission")
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError("workdir-permission")
    return path


def _probe(path: Path, port: object) -> dict[str, object]:
    system = platform.system().lower()
    if system not in {"linux", "darwin"}:
        return _fail("platform-unsupported", "Use a supported Linux or macOS host.")
    if sys.version_info < (3, 12):  # noqa: UP036 - verifies the independently installed host
        return _fail("python-too-old", "Install Python 3.12 or newer on the host.")
    free = shutil.disk_usage(path).free
    if free < MIN_FREE:
        return _fail("disk-low", "Free at least 100 MiB in the dedicated workdir.")
    if port is not None:
        if type(port) is not int or not 1 <= port <= 65535:
            return _fail("port-invalid", "Choose a port in 1..65535.")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return _fail("port-in-use", "Choose a free local port.")
    return {
        "outcome": "ready",
        "platform": system,
        "architecture": platform.machine(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "freeBytes": free,
        "workdir": str(path),
        "installer": "venv+pip --no-index",
    }


def _install(path: Path, document: dict[str, object]) -> dict[str, object]:
    manifest = document.get("wheels")
    archive = document.get("archive")
    package = document.get("package")
    if (
        not isinstance(manifest, dict)
        or not isinstance(archive, str)
        or not isinstance(package, str)
    ):
        return _fail("package-invalid", "Supply the pinned wheelhouse archive.")
    try:
        data = base64.b64decode(archive, validate=True)
    except (ValueError, binascii.Error):
        return _fail("package-invalid", "Supply valid wheelhouse bytes.")
    if len(data) > 32 * 1024 * 1024 or not 1 <= len(manifest) <= 32:
        return _fail("package-too-large", "Reduce the wheelhouse to 32 MiB and 32 wheels.")
    if package not in manifest or not package.startswith("llm_research_os-"):
        return _fail("package-invalid", "Supply the llm-research-os wheel.")
    wheels: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        if len(zipped.infolist()) != len(manifest) or set(zipped.namelist()) != set(manifest):
            return _fail("package-invalid", "Wheelhouse manifest does not match archive.")
        if sum(info.file_size for info in zipped.infolist()) > 32 * 1024 * 1024:
            return _fail("package-too-large", "Reduce the uncompressed wheelhouse to 32 MiB.")
        for name, digest in manifest.items():
            if (
                not isinstance(name, str)
                or not name.endswith(".whl")
                or "/" in name
                or "\\" in name
                or not isinstance(digest, str)
            ):
                return _fail("package-invalid", "Wheel filenames or digests are invalid.")
            info = zipped.getinfo(name)
            if info.file_size > 16 * 1024 * 1024 or info.compress_size > 16 * 1024 * 1024:
                return _fail("package-too-large", "A wheel exceeds 16 MiB.")
            wheel = zipped.read(name)
            if hashlib.sha256(wheel).hexdigest() != digest:
                return _fail("package-digest-mismatch", "Rebuild the pinned wheelhouse.")
            wheels[name] = wheel
    identity = hashlib.sha256(data).hexdigest()
    root = path / ".researchos"
    if root.is_symlink():
        return _fail("install-path-invalid", "Remove the unsafe .researchos symlink manually.")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        return _fail("install-path-invalid", "Use a private user-owned install directory.")
    final = root / f"runtime-{identity[:24]}"
    marker = final / "wheelhouse.sha256"
    if final.exists() or final.is_symlink():
        if final.is_symlink() or not marker.is_file() or marker.read_text() != identity:
            return _fail("install-conflict", "Existing runtime differs; inspect it manually.")
        python = final / "venv" / "bin" / "python"
        if not python.is_file():
            return _fail(
                "install-conflict", "The recorded runtime is incomplete; inspect it manually."
            )
        try:
            checked = subprocess.run(  # noqa: S603 - fixed package metadata verification
                [
                    str(python),
                    "-I",
                    "-c",
                    "import importlib.metadata as m; m.version('llm-research-os')",
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return _fail("install-conflict", "The recorded runtime cannot be verified.")
        if checked.returncode != 0:
            return _fail("install-conflict", "The pinned package is missing from the runtime.")
        return {"outcome": "ready", "runtime": str(final), "installed": False, "digest": identity}
    created = False
    try:
        final.mkdir(mode=0o700)
        created = True
        wheel_dir = final / "wheels"
        wheel_dir.mkdir()
        for name, wheel in wheels.items():
            (wheel_dir / name).write_bytes(wheel)
        venv.EnvBuilder(with_pip=True, clear=False).create(final / "venv")
        python = final / "venv" / "bin" / "python"
        result = subprocess.run(  # noqa: S603 - installed venv Python and fixed pip arguments
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheel_dir),
                str(wheel_dir / package),
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if result.returncode != 0:
            shutil.rmtree(final)
            return _fail("install-failed", "Supply compatible dependency wheels for this host.")
        (final / "wheelhouse.sha256").write_text(identity)
        shutil.rmtree(wheel_dir)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        if created:
            shutil.rmtree(final)
        return _fail("install-failed", "Check Python venv/pip, disk space and compatible wheels.")
    except BaseException:
        if created:
            shutil.rmtree(final)
        raise
    return {"outcome": "ready", "runtime": str(final), "installed": True, "digest": identity}


def _worker_identity(document: dict[str, object]) -> dict[str, object]:
    endpoint = document.get("controlPlaneUrl")
    worker_id = document.get("workerId")
    session = document.get("session")
    cert = document.get("caPem")
    fingerprint = document.get("tlsFingerprint")
    if not all(
        isinstance(item, str) and item for item in (endpoint, worker_id, session, cert, fingerprint)
    ):
        return _fail(
            "worker-credential-invalid", "Supply a complete Worker credential and pinned CA."
        )
    if (
        not isinstance(endpoint, str)
        or not isinstance(worker_id, str)
        or not isinstance(session, str)
        or not isinstance(cert, str)
        or not isinstance(fingerprint, str)
    ):
        return _fail("worker-credential-invalid", "Supply complete Worker credentials.")
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or url.hostname is None
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        return _fail("tls-required", "Use an HTTPS control-plane URL without userinfo or paths.")
    if "sha256:" + hashlib.sha256(cert.encode()).hexdigest() != fingerprint:
        return _fail("tls-fingerprint-mismatch", "Use the pinned control-plane CA.")
    try:
        context = ssl.create_default_context(cadata=cert)
        connection = http.client.HTTPSConnection(
            url.hostname, url.port or 443, timeout=8, context=context
        )
        body = json.dumps({"workerId": worker_id}).encode()
        connection.request(
            "POST",
            "/v0alpha1/work/identity",
            body,
            {"Authorization": "Bearer " + session, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(4097)
        connection.close()
    except (OSError, ssl.SSLError, ValueError):
        return _fail(
            "worker-tls-unavailable", "Check route, TLS certificate and control-plane port."
        )
    if len(raw) > 4096 or response.status != 200:
        return _fail(
            "worker-registration-unverified", "Register the Worker and verify its session."
        )
    try:
        identity = json.loads(raw)
    except ValueError:
        return _fail("worker-response-invalid", "Inspect the control-plane Worker endpoint.")
    if (
        not isinstance(identity, dict)
        or identity.get("workerId") != worker_id
        or identity.get("registered") is not True
    ):
        return _fail("worker-registration-unverified", "Register the Worker on the control plane.")
    return {
        "outcome": "ready",
        "workerId": worker_id,
        "registered": True,
        "runtime": identity.get("runtime"),
        "tlsVerified": True,
    }


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            result = _fail("input-too-large", "Reduce the onboarding input.")
        else:
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("input-invalid")
            path = _workdir(document.get("workdir"))
            result = _probe(path, document.get("port"))
            if result["outcome"] == "ready":
                if document.get("operation") == "install":
                    result = _install(path, document)
                elif document.get("operation") == "verify-worker":
                    result = _worker_identity(document)
                elif document.get("operation") != "probe":
                    result = _fail("operation-invalid", "Use probe, install, or verify-worker.")
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        code = (
            str(exc)
            if str(exc) in {"workdir-invalid", "workdir-missing", "workdir-permission"}
            else "remote-probe-failed"
        )
        result = _fail(code, "Check the dedicated workdir, Python and available disk space.")
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
