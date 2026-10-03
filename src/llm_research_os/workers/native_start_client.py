"""Pinned TLS start-record publication; retries only the same immutable record."""

from __future__ import annotations

import json
from http.client import HTTPException
from typing import TYPE_CHECKING

from pydantic import ValidationError

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.workers.client import _connection
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_start_documents import NativeStartReceipt, NativeStartRequest
from llm_research_os.workers.native_transfer import _origin

if TYPE_CHECKING:
    from llm_research_os.workers.client import WorkerClient


def publish_native_start(client: WorkerClient, document: NativeStartRequest) -> NativeStartReceipt:
    parsed = _origin(client)
    body = document.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload = canonical_json(body).encode()
    if len(payload) > 16384:
        raise WorkerError("native start exceeds its bound", code="http-too-large")
    binding = {
        "workerId": client.worker_id,
        "grantId": document.preparation.grant_id,
        "start": body,
    }
    digest = content_digest(binding)
    expected_event = (
        f"evt.native.remote.{document.preparation.run_id}."
        f"{document.preparation.attempt_id}.attempt.started"
    )
    attempts = min(3, max(1, client.retries))
    for attempt in range(attempts):
        connection = _connection(parsed, client.ca_path, client.tls_fingerprint)
        try:
            connection.timeout = 10
            connection.request(
                "POST",
                "/v0alpha1/native/start",
                payload,
                {
                    "Authorization": "Bearer " + client.session,
                    "X-ResearchOS-Grant": client.grant_token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise WorkerError("native start refused", code="native-start-refused")
            size = response.getheader("Content-Length")
            if (
                size is None
                or not size.isdecimal()
                or not 0 < int(size) <= 4096
                or response.getheader("Content-Type") != "application/json"
                or response.getheader("Content-Encoding")
                or response.getheader("Transfer-Encoding")
            ):
                raise WorkerError("native start receipt is invalid", code="native-start-receipt")
            raw = response.read(int(size) + 1)
            if len(raw) < int(size):
                raise OSError("native start receipt interrupted")
            if len(raw) != int(size):
                raise WorkerError("native start receipt size differs", code="native-start-receipt")
            try:
                receipt = NativeStartReceipt.model_validate(json.loads(raw))
            except (ValueError, ValidationError, RecursionError):
                raise WorkerError(
                    "native start receipt is invalid", code="native-start-receipt"
                ) from None
            if (
                receipt.lease_id != document.lease_id
                or receipt.binding_digest != digest
                or receipt.event_id != expected_event
            ):
                raise WorkerError(
                    "native start receipt binding differs", code="native-start-receipt"
                )
            return receipt
        except (OSError, HTTPException):
            if attempt == attempts - 1:
                raise WorkerError(
                    "native start response interrupted", code="http-disconnect"
                ) from None
        finally:
            connection.close()
    raise WorkerError("native start response interrupted", code="http-disconnect")
