"""Isolated Worker process. Must not import EventStore or the control-plane CAS root."""

from __future__ import annotations

from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.credentials import load_worker_credential
from llm_research_os.workers.errors import WorkerError


def run_isolated_worker(*, credential_path: Path, artifacts_root: Path) -> dict[str, str]:
    """Claim one grant over pinned loopback HTTPS and execute from a private CAS."""

    credential = load_worker_credential(credential_path)
    if not credential.control_plane_url.startswith("https://"):
        raise WorkerError(
            "isolated Worker requires loopback HTTPS",
            code="tls-required",
        )
    artifacts_root.mkdir(parents=True, exist_ok=True)
    client = WorkerClient(
        base_url=credential.control_plane_url,
        worker_id=credential.worker_id,
        session=credential.session,
        grant_token=credential.grant_token,
        ca_path=credential.tls_ca_path,
        tls_fingerprint=credential.tls_fingerprint,
    )
    completed = client.run_once(LocalArtifactStore(artifacts_root))
    if completed is None:
        raise WorkerError("worker poll returned no work", code="work-missing")
    return completed
