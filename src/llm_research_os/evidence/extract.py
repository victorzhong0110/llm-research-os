"""Extract UTF-8 text from local Markdown or PDF bytes. No network."""

from __future__ import annotations

from io import BytesIO
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from llm_research_os.evidence.errors import EvidenceExtractError

MediaType = Literal["text/markdown", "application/pdf"]
MAX_EVIDENCE_BYTES = 8_388_608
MAX_EXTRACTED_CHARS = 400_000


def media_type_for_suffix(suffix: str) -> MediaType:
    lowered = suffix.casefold()
    if lowered in {".md", ".markdown"}:
        return "text/markdown"
    if lowered == ".pdf":
        return "application/pdf"
    raise EvidenceExtractError(
        "import source media type is not supported",
        code="unsupported-media",
    )


def extract_text(payload: bytes, media_type: MediaType) -> str:
    if type(payload) is not bytes:
        raise EvidenceExtractError("import payload must be bytes", code="invalid-payload")
    if len(payload) == 0:
        raise EvidenceExtractError("import source is empty", code="empty-source")
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise EvidenceExtractError("import source exceeds size limit", code="source-too-large")
    text = _decode_markdown(payload) if media_type == "text/markdown" else _extract_pdf(payload)
    if len(text) > MAX_EXTRACTED_CHARS:
        raise EvidenceExtractError("extracted text exceeds size limit", code="text-too-large")
    return text


def _decode_markdown(payload: bytes) -> str:
    if b"\x00" in payload:
        raise EvidenceExtractError("markdown source contains NUL bytes", code="invalid-markdown")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceExtractError(
            "markdown source is not UTF-8",
            code="invalid-markdown",
        ) from None


def _extract_pdf(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        pages = [(page.extract_text() or "") for page in reader.pages]
    except (PyPdfError, OSError, ValueError, TypeError):
        raise EvidenceExtractError("could not extract PDF text", code="pdf-extract") from None
    text = "\n".join(pages).strip()
    if not text:
        raise EvidenceExtractError("PDF contained no extractable text", code="pdf-empty")
    return text
