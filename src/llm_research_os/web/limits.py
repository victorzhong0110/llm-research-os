"""Bounded request handling: body bytes, concurrency, and parse resource limits.

TM-079/TM-080. A local browser is still an untrusted client, and a stalled or
hostile socket must not become an unbounded read of the operator's process.
Source-byte limits alone do not bound parser work, so JSON/YAML/PDF bodies are
re-decoded through the existing bounded loaders and every limit is checked
before the work is started, not after.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from types import TracebackType
from typing import Any, BinaryIO

from llm_research_os.evidence.extract import (
    MAX_EVIDENCE_BYTES,
    MAX_EXTRACTED_CHARS,
    MAX_PDF_PAGES,
    extract_pdf_pages,
)
from llm_research_os.spec.io import MAX_DECODED_DEPTH, MAX_DECODED_NODES, SpecLoadError
from llm_research_os.spec.io import decode_document_text as _decode_spec_document
from llm_research_os.web.errors import LocalApiError, bad_request

MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_CONCURRENT_REQUESTS = 8
_BODY_CHUNK_BYTES = 65_536
_SUPPORTED_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".pdf": "pdf"}


@dataclass(frozen=True)
class RequestLimits:
    """One immutable limit set, reported to the browser in the capabilities view."""

    max_body_bytes: int = MAX_REQUEST_BODY_BYTES
    max_concurrent_requests: int = MAX_CONCURRENT_REQUESTS
    max_decoded_depth: int = MAX_DECODED_DEPTH
    max_decoded_nodes: int = MAX_DECODED_NODES
    max_evidence_bytes: int = MAX_EVIDENCE_BYTES
    max_extracted_chars: int = MAX_EXTRACTED_CHARS
    max_pdf_pages: int = MAX_PDF_PAGES
    read_timeout_seconds: float = 10.0

    def document(self) -> dict[str, Any]:
        return {
            "maxBodyBytes": self.max_body_bytes,
            "maxConcurrentRequests": self.max_concurrent_requests,
            "maxDecodedDepth": self.max_decoded_depth,
            "maxDecodedNodes": self.max_decoded_nodes,
            "maxEvidenceBytes": self.max_evidence_bytes,
            "maxExtractedChars": self.max_extracted_chars,
            "maxPdfPages": self.max_pdf_pages,
            "readTimeoutSeconds": self.read_timeout_seconds,
        }


class ConcurrencyGate:
    """Bounded in-flight request count. Refusal is explicit, never a queueing wait."""

    def __init__(self, maximum: int) -> None:
        if maximum < 1:
            raise ValueError("maximum must be positive")
        self._maximum = maximum
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def __enter__(self) -> ConcurrencyGate:
        with self._lock:
            if self._active >= self._maximum:
                raise LocalApiError(
                    "concurrency-exhausted",
                    "Too many in-flight local API requests; retry shortly.",
                    status=503,
                )
            self._active += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            self._active -= 1


def read_bounded_body(
    stream: BinaryIO,
    *,
    content_length: str | None,
    limits: RequestLimits,
) -> bytes:
    """Read the declared request body, bounded, without blocking a keep-alive socket.

    Two separate traps, both found against a real socket rather than an
    in-memory stream:

    * ``wsgi.input`` is a ``BufferedReader``, whose ``read(n)`` blocks until it
      holds exactly *n* bytes. A 7-byte body against a 64 KiB chunk would hang
      forever, so ``read1`` is required and ``read`` is only a last resort.
    * The declared ``Content-Length`` is the body's end, not a hint. On a
      keep-alive connection there is no EOF, so a second read after the declared
      bytes blocks until the socket timeout. The loop therefore stops at the
      declared length and never reads past it.

    A declared length above the cap is refused without reading, an understated
    length is cut off at the cap rather than trusted, and an absent or
    unparsable length means there is no body to read.
    """

    raw = (content_length or "").strip()
    if raw == "":
        return b""
    if not raw.isdigit():
        raise bad_request("parameter-invalid", "Content-Length must be a non-negative integer.")
    declared = int(raw)
    if declared > limits.max_body_bytes:
        raise bad_request("body-too-large", "Request body exceeds the local API limit.")
    if declared == 0:
        return b""

    reader = getattr(stream, "read1", None)
    read = reader if callable(reader) else stream.read
    chunks: list[bytes] = []
    remaining = declared
    while remaining > 0:
        chunk = read(min(_BODY_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining > 0:
        raise bad_request("document-invalid", "The request body ended before Content-Length.")
    return b"".join(chunks)


def document_kind(content_type: str | None, declared_name: str | None) -> str:
    """Resolve a bounded document kind from the request, or refuse it."""

    declared = (content_type or "").split(";", 1)[0].strip().lower()
    suffix = ""
    if declared_name:
        name = declared_name.strip().lower()
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise bad_request("parameter-invalid", "documentName must be a bare file name.")
        if "." in name:
            suffix = name[name.rindex(".") :]
    kind = _SUPPORTED_SUFFIXES.get(suffix)
    if kind is None:
        kind = _SUPPORTED_SUFFIXES.get(
            {
                "application/json": ".json",
                "application/x-yaml": ".yaml",
                "text/yaml": ".yaml",
                "application/pdf": ".pdf",
            }.get(declared, "")
        )
    if kind is None:
        raise bad_request(
            "content-type-unsupported",
            "Send a .json, .yaml, or .pdf document with its declared type.",
        )
    return kind


def decode_bounded_json(payload: bytes, *, limits: RequestLimits) -> dict[str, Any]:
    """Decode one JSON body through the shared duplicate-key and node guards."""

    if len(payload) > limits.max_body_bytes:
        raise bad_request("body-too-large", "Request body exceeds the local API limit.")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise bad_request("document-invalid", "Request body must be UTF-8.") from exc
    try:
        return _decode_spec_document(text, suffix=".json", source="request body")
    except SpecLoadError as exc:
        raise bad_request(
            "document-hostile", "Request body was refused by the document limits."
        ) from exc


def decode_bounded_yaml(payload: bytes, *, limits: RequestLimits) -> dict[str, Any]:
    """Decode one YAML body. Aliases, duplicate keys and node/depth blowups refuse."""

    if len(payload) > limits.max_body_bytes:
        raise bad_request("body-too-large", "Request body exceeds the local API limit.")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise bad_request("document-invalid", "Request body must be UTF-8.") from exc
    try:
        return _decode_spec_document(text, suffix=".yaml", source="request body")
    except SpecLoadError as exc:
        raise bad_request(
            "document-hostile", "Request body was refused by the document limits."
        ) from exc


def extract_bounded_pdf(payload: bytes, *, limits: RequestLimits) -> dict[str, Any]:
    """Extract PDF text through the existing page/char/second bounded worker path."""

    if len(payload) > limits.max_evidence_bytes:
        raise bad_request("body-too-large", "PDF exceeds the bounded evidence size.")
    try:
        text = extract_pdf_pages(payload)
    except Exception as exc:
        raise bad_request(
            "document-hostile", "The PDF was refused by the bounded extractor."
        ) from exc
    return {
        "characters": len(text),
        "truncated": len(text) >= limits.max_extracted_chars,
        "text": text[: limits.max_extracted_chars],
    }


def bounded_document(
    payload: bytes,
    *,
    kind: str,
    limits: RequestLimits,
) -> dict[str, Any]:
    """Route one uploaded document to its bounded decoder."""

    if kind == "json":
        return decode_bounded_json(payload, limits=limits)
    if kind == "yaml":
        return decode_bounded_yaml(payload, limits=limits)
    if kind == "pdf":
        return extract_bounded_pdf(payload, limits=limits)
    raise bad_request("content-type-unsupported", "Unsupported document kind.")


def json_bytes(document: Any) -> bytes:
    """Canonical single-line JSON for a response body."""

    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
