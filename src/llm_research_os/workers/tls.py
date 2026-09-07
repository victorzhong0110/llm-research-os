"""Loopback TLS material for the isolated Worker binding. Not a cross-machine proof."""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from llm_research_os.artifacts.store import DIGEST_PATTERN
from llm_research_os.workers.errors import WorkerError

_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_CERT_NAME = "tls-cert.pem"
_KEY_NAME = "tls-key.pem"


@dataclass(frozen=True, slots=True)
class TlsMaterial:
    cert_path: Path
    key_path: Path
    fingerprint: str

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert_path, self.key_path)
        return context

    def client_context(self) -> ssl.SSLContext:
        return client_tls_context(self.cert_path, self.fingerprint)


def client_tls_context(ca_path: Path, fingerprint: str) -> ssl.SSLContext:
    actual = pem_fingerprint(ca_path)
    if actual != fingerprint:
        raise WorkerError(
            "TLS CA fingerprint does not match the credential",
            code="tls-fingerprint-mismatch",
        )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(ca_path)
    return context


def pem_fingerprint(path: Path) -> str:
    digest = "sha256:" + hashlib.sha256(_read_regular_file(path)).hexdigest()
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise WorkerError("TLS fingerprint is invalid", code="tls-fingerprint-invalid")
    return digest


def load_or_create_loopback_tls(directory: Path) -> TlsMaterial:
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / _CERT_NAME
    key_path = directory / _KEY_NAME
    if cert_path.is_file() and key_path.is_file():
        return TlsMaterial(cert_path, key_path, pem_fingerprint(cert_path))
    if cert_path.exists() or key_path.exists():
        raise WorkerError("TLS material is incomplete", code="tls-material-invalid")
    _generate_loopback_cert(cert_path, key_path)
    _private_file(cert_path)
    _private_file(key_path)
    return TlsMaterial(cert_path, key_path, pem_fingerprint(cert_path))


def _generate_loopback_cert(cert_path: Path, key_path: Path) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise WorkerError(
            "openssl is required to mint loopback TLS material",
            code="tls-openssl-missing",
        )
    completed = subprocess.run(  # noqa: S603
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=False,
        capture_output=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")},
        close_fds=True,
    )
    if completed.returncode != 0 or not cert_path.is_file() or not key_path.is_file():
        raise WorkerError("could not mint loopback TLS material", code="tls-openssl-failed")


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise WorkerError("TLS file must be a regular file", code="tls-material-invalid")
    return path.read_bytes()


def _private_file(path: Path) -> None:
    os.chmod(path, _PRIVATE_FILE_MODE)
