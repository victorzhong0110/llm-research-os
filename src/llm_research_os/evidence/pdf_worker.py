"""Isolated PDF text extraction. Invoked as ``python -m ...pdf_worker`` (TM-041)."""

from __future__ import annotations

import os
import sys

from llm_research_os.evidence.errors import EvidenceExtractError
from llm_research_os.evidence.extract import (
    MAX_EVIDENCE_BYTES,
    PDF_WORKER_ENV,
    PDF_WORKER_FAIL_CODES,
    apply_pdf_resource_limits,
    extract_pdf_pages,
)


def run_worker(payload: bytes) -> tuple[int, bytes, bytes]:
    """Return ``(exit_code, stdout, stderr)``. Stderr is an allowlisted code or empty."""
    try:
        text = extract_pdf_pages(payload)
    except EvidenceExtractError as rec:
        code = rec.code if rec.code in PDF_WORKER_FAIL_CODES else "pdf-extract"
        return 1, b"", f"{code}\n".encode("ascii")
    except Exception:
        return 1, b"", b"pdf-extract\n"
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return 1, b"", b"pdf-extract\n"
    return 0, encoded, b""


def main() -> int:
    if os.environ.get(PDF_WORKER_ENV) == "1":
        apply_pdf_resource_limits()
    payload = sys.stdin.buffer.read(MAX_EVIDENCE_BYTES + 1)
    code, stdout, stderr = run_worker(payload)
    if stdout:
        sys.stdout.buffer.write(stdout)
    if stderr:
        sys.stderr.buffer.write(stderr)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
