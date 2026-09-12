"""Worker credential and HMAC-key files. Tokens must not enter EventStore or logs (TM-007)."""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.secrets.redaction import message_without_secrets
from llm_research_os.spec.io import load_document
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.tls import pem_fingerprint
from llm_research_os.workers.tokens import HMAC_KEY_BYTES, require_hmac_key

_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_HMAC_NAME = "hmac.key"
_API_VERSION = "researchos.dev/v0alpha1"
_KIND = "WorkerCredential"


@dataclass(frozen=True, slots=True)
class WorkerCredential:
    control_plane_url: str
    worker_id: str
    session: str
    grant_token: str
    tls_ca_path: Path
    tls_fingerprint: str

    def secrets(self) -> tuple[str, ...]:
        return (self.session, self.grant_token)


def hmac_key_path(state_dir: Path) -> Path:
    return state_dir / _HMAC_NAME


def load_or_create_hmac_key(state_dir: Path) -> bytes:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = hmac_key_path(state_dir)
    if path.is_file():
        return load_hmac_key(path)
    key = secrets.token_bytes(HMAC_KEY_BYTES)
    _write_private(path, key)
    return require_hmac_key(key)


def load_hmac_key(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise WorkerError("HMAC key must be a regular file", code="hmac-key-invalid")
    return require_hmac_key(path.read_bytes())


def write_hmac_key(path: Path, key: bytes) -> None:
    require_hmac_key(key)
    if path.exists():
        existing = load_hmac_key(path)
        if existing != key:
            raise WorkerError("HMAC key file does not match", code="hmac-key-mismatch")
        return
    _write_private(path, key)


def load_worker_credential(path: Path) -> WorkerCredential:
    document = snapshot_json_document(load_document(path, reject_symlinks=True))
    if type(document) is not dict:
        raise WorkerError("worker credential must be a JSON object", code="credential-invalid")
    if document.get("apiVersion") != _API_VERSION or document.get("kind") != _KIND:
        raise WorkerError("worker credential kind is invalid", code="credential-invalid")
    url = _require_str(document, "controlPlaneUrl")
    worker_id = _require_str(document, "workerId")
    session = _require_str(document, "session")
    grant_token = _require_str(document, "grantToken")
    ca_value = _require_str(document, "tlsCaPath")
    fingerprint = _require_str(document, "tlsFingerprint")
    ca_path = Path(ca_value)
    if not ca_path.is_absolute():
        ca_path = (path.parent / ca_path).resolve()
    actual = pem_fingerprint(ca_path)
    if actual != fingerprint:
        raise WorkerError(
            "TLS CA fingerprint does not match the credential",
            code="tls-fingerprint-mismatch",
        )
    return WorkerCredential(
        control_plane_url=url,
        worker_id=worker_id,
        session=session,
        grant_token=grant_token,
        tls_ca_path=ca_path,
        tls_fingerprint=fingerprint,
    )


def write_worker_credential(path: Path, credential: WorkerCredential) -> None:
    if path.exists():
        raise WorkerError("worker credential already exists", code="credential-exists")
    payload = json.dumps(
        {
            "apiVersion": _API_VERSION,
            "kind": _KIND,
            "controlPlaneUrl": credential.control_plane_url,
            "workerId": credential.worker_id,
            "session": credential.session,
            "grantToken": credential.grant_token,
            "tlsCaPath": str(credential.tls_ca_path),
            "tlsFingerprint": credential.tls_fingerprint,
        },
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    _write_private(path, (payload + "\n").encode("utf-8"))


def redact_worker_log(message: str, *secrets: str) -> str:
    return message_without_secrets(message, *secrets)


def _require_str(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if type(value) is not str or value == "":
        raise WorkerError("worker credential is missing a field", code="credential-invalid")
    return value


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, _PRIVATE_FILE_MODE)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, _PRIVATE_FILE_MODE)
