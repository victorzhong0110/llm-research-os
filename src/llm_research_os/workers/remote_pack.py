"""Remote Worker pack: CA + scripts + pending-live status. Not a two-host proof."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlparse

from llm_research_os.workers.bind import require_worker_bind_host
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.tls import (
    cert_covers_host,
    load_or_create_tls,
    pem_fingerprint,
)

_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_CERT_NAME = "tls-cert.pem"
_KEY_NAME = "tls-key.pem"
_API_VERSION = "researchos.dev/v0alpha1"


def write_remote_worker_pack(
    output: Path,
    *,
    control_plane_url: str,
    project_id: str,
    source: str,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Write a runnable pack. STATUS is always pending-live."""

    parsed = _require_https_url(control_plane_url)
    host = parsed.hostname
    if host is None:
        raise WorkerError("control-plane URL host is missing", code="remote-url-invalid")
    require_worker_bind_host(host, tls=True)
    if output.exists() and any(output.iterdir()):
        raise WorkerError("remote Worker pack directory is not empty", code="pack-exists")
    control_state = output / "control-state"
    worker_dir = output / "worker"
    scripts_dir = output / "scripts"
    worker_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    if state_dir is not None:
        source_cert = state_dir / _CERT_NAME
        if not source_cert.is_file():
            raise WorkerError("control-plane CA is missing", code="tls-material-invalid")
        shutil.copy2(source_cert, worker_dir / _CERT_NAME)
        os.chmod(worker_dir / _CERT_NAME, _PRIVATE_FILE_MODE)
        if not cert_covers_host(worker_dir / _CERT_NAME, host):
            raise WorkerError(
                "TLS certificate SAN does not cover the control-plane host",
                code="tls-san-mismatch",
            )
        fingerprint = pem_fingerprint(worker_dir / _CERT_NAME)
    else:
        material = load_or_create_tls(control_state, host=host)
        shutil.copy2(material.cert_path, worker_dir / _CERT_NAME)
        os.chmod(worker_dir / _CERT_NAME, _PRIVATE_FILE_MODE)
        fingerprint = material.fingerprint
    _refuse_key_in_worker(worker_dir)
    loopback = host in {"127.0.0.1", "::1", "localhost"}
    status = {
        "apiVersion": _API_VERSION,
        "kind": "RemoteWorkerPack",
        "crossMachine": "pending-live",
        "localhostIsNotCrossMachine": True,
        "binding": "loopback-not-cross-machine" if loopback else "remote-https-json",
        "controlPlaneUrl": control_plane_url,
        "tlsFingerprint": fingerprint,
        "projectId": project_id,
        "source": source,
    }
    (output / "STATUS.json").write_text(
        json.dumps(status, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (worker_dir / "credential.template.json").write_text(
        json.dumps(
            {
                "apiVersion": _API_VERSION,
                "kind": "WorkerCredential",
                "controlPlaneUrl": control_plane_url,
                "workerId": "REPLACE-WITH-WORKER-ID",
                "session": "REPLACE-WITH-WS1",
                "grantToken": "REPLACE-WITH-RG1",
                "tlsCaPath": _CERT_NAME,
                "tlsFingerprint": fingerprint,
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(_pack_readme(loopback), encoding="utf-8")
    (scripts_dir / "serve.sh").write_text(_serve_script(), encoding="utf-8")
    (scripts_dir / "run-worker.sh").write_text(_worker_script(), encoding="utf-8")
    os.chmod(scripts_dir / "serve.sh", 0o700)
    os.chmod(scripts_dir / "run-worker.sh", 0o700)
    _refuse_key_in_worker(worker_dir)
    return status


def _require_https_url(url: str) -> ParseResult:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WorkerError("remote Worker URL must be https", code="remote-url-not-https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkerError(
            "remote Worker URL cannot carry userinfo, query, or fragment",
            code="remote-url-invalid",
        )
    if parsed.hostname is None or parsed.path not in {"", "/"}:
        raise WorkerError("remote Worker URL host is invalid", code="remote-url-invalid")
    return parsed


def _refuse_key_in_worker(worker_dir: Path) -> None:
    for path in worker_dir.rglob("*"):
        name = path.name.lower()
        if "key" in name and path.is_file():
            raise WorkerError(
                "worker pack must not contain a private key",
                code="pack-private-key",
            )


def _pack_readme(loopback: bool) -> str:
    extra = (
        "This pack uses a loopback URL. That is **not** a cross-machine proof.\n"
        if loopback
        else (
            "Live two-host verification is still `pending-live`. "
            "Do not treat this pack as a completed remote run.\n"
        )
    )
    return (
        "# Remote Worker pack (pending-live)\n\n"
        "Issue #38 stays open. This pack does not spend GPU and does not "
        "prove a second machine.\n\n"
        f"{extra}\n"
        "The control plane and Worker MUST use different working directories "
        "and different CAS roots. Copy `worker/tls-cert.pem` only. Never copy "
        "`tls-key.pem`. Do not paste a private key into the Worker host.\n\n"
        "Fill `worker/credential.template.json` with a live `ws1` session and "
        "`rg1` grant on the control-plane host, then run `scripts/run-worker.sh` "
        "on the Worker host. Auth, download, upload, and reconnect are the "
        "ADR-0044 isolated HTTPS path.\n"
    )


def _serve_script() -> str:
    return """#!/bin/sh
set -eu
# Loopback --host is not a cross-machine proof (ADR-0021).
DATABASE=${DATABASE:?}
CONTROL_CAS=${CONTROL_CAS:?}
STATE=${STATE:?}
PROJECT=${PROJECT:?}
SOURCE=${SOURCE:?}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8443}
exec uv run researchos workers serve "$DATABASE" \\
  --artifacts "$CONTROL_CAS" \\
  --state "$STATE" \\
  --project "$PROJECT" \\
  --source "$SOURCE" \\
  --host "$HOST" \\
  --port "$PORT"
"""


def _worker_script() -> str:
    return """#!/bin/sh
set -eu
CREDENTIAL=${CREDENTIAL:?}
WORKER_CAS=${WORKER_CAS:?}
exec uv run researchos workers run "$CREDENTIAL" --artifacts "$WORKER_CAS"
"""
