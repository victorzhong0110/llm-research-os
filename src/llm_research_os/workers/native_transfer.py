"""Grant-scoped native input transport. Downloads never claim or launch work."""

from __future__ import annotations

import hashlib
import json
from http.client import HTTPException
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from llm_research_os.artifacts.store import DIGEST_PATTERN, MAX_WORKER_PUT_BYTES
from llm_research_os.workers.client import _connection
from llm_research_os.workers.errors import WorkerError

if TYPE_CHECKING:
    from llm_research_os.workers.client import WorkerClient


def fetch_native_input(client: WorkerClient, *, digest: str, size_bytes: int) -> bytes:
    """Read at most the declared size plus one byte; retry disconnects at most three times."""

    parsed = urlparse(client.base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise WorkerError("native transfer requires a TLS origin", code="tls-required")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise WorkerError("invalid input digest", code="http-invalid")
    if type(size_bytes) is not int or not 0 <= size_bytes <= MAX_WORKER_PUT_BYTES:
        raise WorkerError("invalid transfer size", code="http-too-large")
    payload = json.dumps({"digest": digest, "sizeBytes": size_bytes}).encode("ascii")
    headers = {
        "Authorization": f"Bearer {client.session}",
        "X-ResearchOS-Grant": client.grant_token,
        "Content-Type": "application/json",
    }
    for attempt in range(min(3, max(1, client.retries))):
        connection = _connection(parsed, client.ca_path, client.tls_fingerprint)
        try:
            connection.request("POST", "/v0alpha1/native/inputs", payload, headers)
            response = connection.getresponse()
            if response.status != 200:
                # Do not allocate error responses or retry authorization failures.
                raise WorkerError("native input request refused", code="transfer-refused")
            if response.getheader("Content-Length") != str(size_bytes):
                raise WorkerError("input size does not match", code="transfer-size-mismatch")
            body = response.read(size_bytes + 1)
            if len(body) < size_bytes:
                raise OSError("native input response interrupted")
            if len(body) != size_bytes:
                raise WorkerError("input size does not match", code="transfer-size-mismatch")
            if f"sha256:{hashlib.sha256(body).hexdigest()}" != digest:
                raise WorkerError("input digest does not match", code="transfer-digest-mismatch")
            return body
        except (OSError, HTTPException) as exc:
            if attempt == min(3, max(1, client.retries)) - 1:
                raise WorkerError("native transfer interrupted", code="http-disconnect") from exc
        finally:
            connection.close()
    raise WorkerError("native transfer interrupted", code="http-disconnect")
