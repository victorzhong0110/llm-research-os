"""Control-plane process for the isolated Worker binding (ADR-0044)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage import EventStore
from llm_research_os.workers.credentials import load_or_create_hmac_key
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.tls import TlsMaterial, load_or_create_tls


def bind_isolated_control_plane(
    *,
    database: Path,
    artifacts_root: Path,
    state_dir: Path,
    project_id: str,
    source: str,
    experiment_revision: int = 1,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[LoopbackWorkerServer, TlsMaterial]:
    """Construct the loopback HTTPS server. Caller prints the URL and serves."""

    artifacts_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(database, require_existing=True):
        pass
    hmac_key = load_or_create_hmac_key(state_dir)
    tls = load_or_create_tls(state_dir, host=host)
    server = LoopbackWorkerServer(
        database,
        LocalArtifactStore(artifacts_root),
        hmac_key=hmac_key,
        project_id=project_id,
        source=source,
        host=host,
        port=port,
        experiment_revision=experiment_revision,
        tls=tls,
    )
    return server, tls


def serve_isolated_control_plane(
    *,
    database: Path,
    artifacts_root: Path,
    state_dir: Path,
    project_id: str,
    source: str,
    experiment_revision: int = 1,
    host: str = "127.0.0.1",
    port: int = 0,
) -> None:
    """Bind HTTPS, print one URL receipt, then serve. Loopback is not a cross-machine proof."""

    server, tls = bind_isolated_control_plane(
        database=database,
        artifacts_root=artifacts_root,
        state_dir=state_dir,
        project_id=project_id,
        source=source,
        experiment_revision=experiment_revision,
        host=host,
        port=port,
    )
    receipt = {
        "url": server.base_url,
        "tlsFingerprint": tls.fingerprint,
        "projectId": project_id,
    }
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("control-plane stopped", file=sys.stderr)
    finally:
        server.close_listener()
