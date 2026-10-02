"""Grant-scoped native inputs and durable output receipts. Transfer never launches work."""

from __future__ import annotations

import hashlib
import json
from http.client import HTTPException
from typing import TYPE_CHECKING, cast
from urllib.parse import ParseResult, urlparse

from pydantic import ValidationError

from llm_research_os.artifacts.store import DIGEST_PATTERN, MAX_WORKER_PUT_BYTES
from llm_research_os.canonical import content_digest
from llm_research_os.workers.client import _connection
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_output_documents import NativeOutputReceipt

if TYPE_CHECKING:
    from llm_research_os.workers.client import WorkerClient


def _origin(client: WorkerClient) -> ParseResult:
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
    return parsed


def fetch_native_input(client: WorkerClient, *, digest: str, size_bytes: int) -> bytes:
    """Read at most the declared size plus one byte; retry disconnects at most three times."""

    parsed = _origin(client)
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


def upload_native_output(
    client: WorkerClient, *, lease_id: str, payload: bytes
) -> dict[str, object]:
    """Upload a scoped result, replaying the same completion after response loss."""

    parsed = _origin(client)
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_WORKER_PUT_BYTES:
        raise WorkerError("invalid output size", code="http-too-large")
    if (
        type(lease_id) is not str
        or not 0 < len(lease_id) <= 512
        or not lease_id.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 for char in lease_id)
    ):
        raise WorkerError("invalid output lease", code="http-invalid")
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    try:
        result_digest = content_digest(json.loads(payload))
    except (ValueError, RecursionError):
        raise WorkerError("invalid output JSON", code="transfer-output-invalid") from None
    headers = {
        "Authorization": f"Bearer {client.session}",
        "X-ResearchOS-Grant": client.grant_token,
        "X-ResearchOS-Lease": lease_id,
        "X-ResearchOS-Artifact": digest,
        "Content-Type": "application/json",
    }
    attempts = min(3, max(1, client.retries))
    for attempt in range(attempts):
        connection = _connection(parsed, client.ca_path, client.tls_fingerprint)
        try:
            connection.request("POST", "/v0alpha1/native/outputs", payload, headers)
            response = connection.getresponse()
            if response.status != 200:
                raise WorkerError("native output request refused", code="transfer-refused")
            try:
                size = int(response.getheader("Content-Length", ""))
            except ValueError:
                raise WorkerError(
                    "invalid output receipt", code="transfer-receipt-invalid"
                ) from None
            if not 0 < size <= 4096:
                raise WorkerError("invalid output receipt size", code="transfer-receipt-invalid")
            body = response.read(size + 1)
            if len(body) < size:
                raise OSError("native output receipt interrupted")
            if len(body) != size:
                raise WorkerError("invalid output receipt size", code="transfer-receipt-invalid")
            try:
                receipt = json.loads(body)
            except (ValueError, RecursionError):
                raise WorkerError(
                    "invalid output receipt", code="transfer-receipt-invalid"
                ) from None
            try:
                parsed_receipt = NativeOutputReceipt.model_validate(receipt)
            except ValidationError:
                raise WorkerError(
                    "invalid output receipt", code="transfer-receipt-invalid"
                ) from None
            if (
                parsed_receipt.digest != digest
                or parsed_receipt.size_bytes != len(payload)
                or parsed_receipt.result_digest != result_digest
                or parsed_receipt.lease_id != lease_id
                or parsed_receipt.event_id != f"evt.work.completed.{lease_id}"
            ):
                raise WorkerError("output receipt does not match", code="transfer-receipt-invalid")
            return cast(dict[str, object], receipt)
        except (OSError, HTTPException) as exc:
            if attempt == attempts - 1:
                raise WorkerError("native output interrupted", code="http-disconnect") from exc
        finally:
            connection.close()
    raise WorkerError("native output interrupted", code="http-disconnect")
