"""Extract UTF-8 text from local Markdown or PDF bytes. No network."""

from __future__ import annotations

import os
import subprocess
import sys
from io import BytesIO
from typing import Literal

from llm_research_os.evidence.errors import EvidenceExtractError

MediaType = Literal["text/markdown", "application/pdf"]
MAX_EVIDENCE_BYTES = 8_388_608
MAX_EXTRACTED_CHARS = 400_000
MAX_PDF_PAGES = 64
MAX_PDF_EXTRACT_SECONDS = 5.0
MAX_PDF_CPU_SECONDS = 4
MAX_PDF_WORKER_MEMORY_BYTES = 256 * 1024 * 1024
MAX_PDF_STDOUT_BYTES = MAX_EXTRACTED_CHARS * 4 + 32
PDF_WORKER_MODULE = "llm_research_os.evidence.pdf_worker"
PDF_WORKER_ENV = "LROS_PDF_WORKER"
_PDF_WORKER_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
)

# Worker stderr is a single allowlisted code. Never copy stdout/stderr into errors (TM-022).
PDF_WORKER_FAIL_CODES = frozenset(
    {
        "empty-source",
        "invalid-payload",
        "pdf-empty",
        "pdf-extract",
        "pdf-page-limit",
        "source-too-large",
        "text-too-large",
    }
)
_PDF_FAIL_MESSAGES = {
    "empty-source": "import source is empty",
    "invalid-payload": "import payload must be bytes",
    "pdf-empty": "PDF contained no extractable text",
    "pdf-extract": "could not extract PDF text",
    "pdf-page-limit": "PDF exceeds page limit",
    "pdf-resource": "PDF extraction exceeded resource limit",
    "pdf-timeout": "PDF extraction exceeded time limit",
    "source-too-large": "import source exceeds size limit",
    "text-too-large": "extracted text exceeds size limit",
}


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


def apply_pdf_resource_limits() -> None:
    """Best-effort CPU and address-space caps for the PDF worker (TM-041)."""
    try:
        import resource
    except ImportError:
        return
    _set_rlimit(resource, getattr(resource, "RLIMIT_CPU", None), MAX_PDF_CPU_SECONDS)
    memory_kind = getattr(resource, "RLIMIT_AS", None)
    if memory_kind is None:
        memory_kind = getattr(resource, "RLIMIT_DATA", None)
    _set_rlimit(resource, memory_kind, MAX_PDF_WORKER_MEMORY_BYTES)


def extract_pdf_pages(payload: bytes) -> str:
    """Parse PDF pages incrementally. Used in-process by the isolated worker."""
    if type(payload) is not bytes:
        raise EvidenceExtractError("import payload must be bytes", code="invalid-payload")
    if len(payload) == 0:
        raise EvidenceExtractError("import source is empty", code="empty-source")
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise EvidenceExtractError("import source exceeds size limit", code="source-too-large")
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        page_count = len(reader.pages)
    except (PyPdfError, OSError, ValueError, TypeError, RecursionError):
        raise EvidenceExtractError("could not extract PDF text", code="pdf-extract") from None
    if page_count > MAX_PDF_PAGES:
        raise EvidenceExtractError("PDF exceeds page limit", code="pdf-page-limit")
    parts: list[str] = []
    total = 0
    try:
        for page in reader.pages:
            piece = page.extract_text() or ""
            extra = 1 if parts else 0
            if total + extra + len(piece) > MAX_EXTRACTED_CHARS:
                raise EvidenceExtractError(
                    "extracted text exceeds size limit",
                    code="text-too-large",
                )
            total += extra + len(piece)
            parts.append(piece)
    except EvidenceExtractError:
        raise
    except (PyPdfError, OSError, ValueError, TypeError, RecursionError, MemoryError):
        raise EvidenceExtractError("could not extract PDF text", code="pdf-extract") from None
    text = "\n".join(parts).strip()
    if not text:
        raise EvidenceExtractError("PDF contained no extractable text", code="pdf-empty")
    return text


def pdf_worker_env() -> dict[str, str]:
    """Minimal environment for the parser subprocess. Do not inherit secrets (TM-041)."""

    env: dict[str, str] = {}
    for key in _PDF_WORKER_ENV_PASSTHROUGH:
        value = os.environ.get(key)
        if type(value) is str and value != "":
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env[PDF_WORKER_ENV] = "1"
    return env


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
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-B", "-m", PDF_WORKER_MODULE],
            input=payload,
            capture_output=True,
            timeout=MAX_PDF_EXTRACT_SECONDS,
            env=pdf_worker_env(),
            check=False,
            close_fds=True,
        )
    except subprocess.TimeoutExpired:
        raise EvidenceExtractError(
            _PDF_FAIL_MESSAGES["pdf-timeout"],
            code="pdf-timeout",
        ) from None
    except OSError:
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES["pdf-extract"], code="pdf-extract") from None
    return _pdf_worker_result(completed)


def _pdf_worker_result(completed: subprocess.CompletedProcess[bytes]) -> str:
    if completed.returncode < 0 or completed.returncode in {137, 152}:
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES["pdf-resource"], code="pdf-resource")
    if completed.returncode != 0:
        code = _code_from_worker_stderr(completed.stderr)
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES[code], code=code)
    if len(completed.stdout) > MAX_PDF_STDOUT_BYTES:
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES["text-too-large"], code="text-too-large")
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES["pdf-extract"], code="pdf-extract") from None
    if not text:
        raise EvidenceExtractError(_PDF_FAIL_MESSAGES["pdf-empty"], code="pdf-empty")
    return text


def _code_from_worker_stderr(stderr: bytes) -> str:
    line = stderr.decode("ascii", errors="ignore").strip().split("\n", 1)[0]
    if line in PDF_WORKER_FAIL_CODES:
        return line
    return "pdf-extract"


def _set_rlimit(resource_mod: object, kind: int | None, limit: int) -> None:
    if kind is None:
        return
    setrlimit = getattr(resource_mod, "setrlimit", None)
    if not callable(setrlimit):
        return
    try:
        setrlimit(kind, (limit, limit))
    except (ValueError, OSError):
        return
