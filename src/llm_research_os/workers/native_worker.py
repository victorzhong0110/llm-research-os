"""Native Worker command service; credentials and execution state remain Worker-local."""

from __future__ import annotations

import os
from pathlib import Path

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.execution.native_reviewed import parse_native_reviewed_request
from llm_research_os.execution.native_reviewed_documents import MAX_REVIEWED_REQUEST_BYTES
from llm_research_os.execution.native_reviewed_preparation import load_bounded_file
from llm_research_os.execution.native_transfer import _directory
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.credentials import credential_from_document
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_executor import (
    _read,
    execute_remote_native,
    reconcile_remote_native,
)
from llm_research_os.workers.native_outcome_documents import NativeOutcomeReceipt


def run_native_worker(
    *,
    credential_path: Path,
    artifacts_root: Path,
    state_root: Path,
    workspace: Path | None = None,
    staging_root: Path | None = None,
    request_path: Path | None = None,
) -> NativeOutcomeReceipt:
    if (request_path is None and (workspace is None or staging_root is None)) or (
        request_path is not None and (workspace is not None or staging_root is not None)
    ):
        raise WorkerError("native Worker mode is ambiguous", code="native-worker-input-invalid")
    # Unlike the legacy credential reader, the new executable command requires
    # private bounded no-follow single-link bytes anchored to their parent.
    with _directory(credential_path.absolute().parent, create=False) as root:
        info = os.fstat(root)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkerError("native credential parent is not private", code="credential-invalid")
        credential = credential_from_document(
            _read(root, credential_path.name), path=credential_path
        )
    client = WorkerClient(
        credential.control_plane_url,
        credential.worker_id,
        credential.session,
        credential.grant_token,
        ca_path=credential.tls_ca_path,
        tls_fingerprint=credential.tls_fingerprint,
    )
    artifacts = LocalArtifactStore(artifacts_root)
    if request_path is None:
        if workspace is None or staging_root is None:
            raise WorkerError("native Worker paths are absent", code="native-worker-input-invalid")
        result = execute_remote_native(
            client,
            artifacts=artifacts,
            workspace=workspace,
            staging_root=staging_root,
            state_root=state_root,
        )
    else:
        request = parse_native_reviewed_request(
            load_bounded_file(request_path, limit=MAX_REVIEWED_REQUEST_BYTES)
        )
        result = reconcile_remote_native(
            client, artifacts=artifacts, state_root=state_root, request=request
        )
    if result.receipt is None:
        raise WorkerError(
            "native outcome is unknown; retained intent permits observation only",
            code="native-outcome-unrecorded",
        )
    return result.receipt
