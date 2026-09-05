from __future__ import annotations

import json
import subprocess
import sys
import time
import types
import zlib
from io import BytesIO
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pypdf import PdfReader, PdfWriter

from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.evidence import extract as extract_mod
from llm_research_os.evidence import pdf_worker as pdf_worker_mod
from llm_research_os.evidence.errors import EvidenceExtractError, EvidenceRequestError
from llm_research_os.evidence.extract import (
    MAX_EVIDENCE_BYTES,
    MAX_EXTRACTED_CHARS,
    MAX_PDF_EXTRACT_SECONDS,
    MAX_PDF_PAGES,
    MAX_PDF_STDOUT_BYTES,
    apply_pdf_resource_limits,
    extract_pdf_pages,
    extract_text,
    media_type_for_suffix,
)
from llm_research_os.evidence.models import DEFAULT_LICENSE, EvidenceCitation
from llm_research_os.evidence.pdf_worker import main as pdf_worker_main
from llm_research_os.evidence.pdf_worker import run_worker
from llm_research_os.evidence.requests import (
    load_evidence_import_request,
    validate_evidence_citation,
    validate_evidence_import_request,
)
from llm_research_os.evidence.schema import (
    evidence_citation_schema_matches,
    evidence_import_request_schema_matches,
)
from llm_research_os.providers.capabilities import ModelCapability
from llm_research_os.providers.errors import ModelCapabilityError
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.provider import GenerateRequest
from llm_research_os.providers.requests import load_model_fixture
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "evidence"
SOURCES = EXAMPLES / "sources"
IMPORT_SCHEMA = ROOT / "schemas" / "evidence-import-request" / "v0alpha1.schema.json"
CITATION_SCHEMA = ROOT / "schemas" / "evidence-citation" / "v0alpha1.schema.json"
VALID_IMPORT = EXAMPLES / "valid" / "import-markdown.json"
ADVERSARIAL_IMPORT = EXAMPLES / "valid" / "import-adversarial.json"
MARKDOWN = SOURCES / "eval-split.md"
ADVERSARIAL = SOURCES / "adversarial-inject.md"
FIXTURE = ROOT / "examples" / "model-fixtures" / "valid" / "generate-json.json"
INJECT = "INJECT_TOOLS_NOW"


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _init_store(path: Path) -> None:
    with EventStore(path) as store:
        assert store.last_sequence() == 0


def _pdf_bytes(text: str) -> bytes:
    content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET\n".encode("latin-1")
    objs = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        ),
        b"4 0 obj<< /Length %d >>stream\n" % len(content) + content + b"endstream\nendobj\n",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    body = bytearray(b"%PDF-1.1\n")
    offsets = []
    for obj in objs:
        offsets.append(len(body))
        body.extend(obj)
    xref_pos = len(body)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for off in offsets:
        xref.append(f"{off:010d} 00000 n \n".encode())
    body.extend(b"".join(xref))
    body.extend(f"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    return bytes(body)


def _pdf_objects(content: bytes) -> list[bytes]:
    stream = zlib.compress(content, 9)
    stream_obj = (
        b"4 0 obj<< /Length %d /Filter /FlateDecode >>stream\n" % len(stream)
        + stream
        + b"\nendstream\nendobj\n"
    )
    return [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        ),
        stream_obj,
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]


def _build_pdf(objs: list[bytes]) -> bytes:
    body = bytearray(b"%PDF-1.1\n")
    offsets = []
    for obj in objs:
        offsets.append(len(body))
        body.extend(obj)
    xref_pos = len(body)
    size = len(objs) + 1
    xref = [f"xref\n0 {size}\n0000000000 65535 f \n".encode()]
    for off in offsets:
        xref.append(f"{off:010d} 00000 n \n".encode())
    body.extend(b"".join(xref))
    body.extend(f"trailer<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    return bytes(body)


def _flate_text_pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET\n".encode("latin-1")
    return _build_pdf(_pdf_objects(content))


def _blank_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_committed_evidence_schemas_are_current() -> None:
    assert evidence_import_request_schema_matches(IMPORT_SCHEMA)
    assert evidence_citation_schema_matches(CITATION_SCHEMA)
    for path in (IMPORT_SCHEMA, CITATION_SCHEMA):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "valid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_evidence_examples(path: Path) -> None:
    document = load_document(path)
    if document["kind"] == "EvidenceImportRequest":
        _validator(IMPORT_SCHEMA).validate(document)
        load_evidence_import_request(path)
    else:
        _validator(CITATION_SCHEMA).validate(document)
        validate_evidence_citation(document)


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_evidence_examples(path: Path) -> None:
    document = load_document(path)
    schema_path = IMPORT_SCHEMA if document["kind"] == "EvidenceImportRequest" else CITATION_SCHEMA
    schema_error = False
    try:
        _validator(schema_path).validate(document)
    except JsonSchemaValidationError:
        schema_error = True
    model_error = False
    try:
        if document["kind"] == "EvidenceImportRequest":
            load_evidence_import_request(path)
        else:
            validate_evidence_citation(document)
    except EvidenceRequestError:
        model_error = True
    assert schema_error or model_error


def test_markdown_import_stores_digests_not_path_or_body(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    assert (
        main(
            [
                "evidence",
                "import",
                str(VALID_IMPORT),
                str(database),
                "--source",
                str(MARKDOWN),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    text = MARKDOWN.read_text(encoding="utf-8")
    with EventStore(database, require_existing=True) as store:
        stored = store.read_events(limit=10)
        assert len(stored) == 1
        event = stored[0].event
        assert event.type == "evidence.imported"
        encoded = json.dumps(event.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        assert str(MARKDOWN) not in encoded
        assert "Held-out documents" not in encoded
        payload = event.data.payload
        assert payload["license"] == DEFAULT_LICENSE
        assert payload["rights"] == "unknown"
        assert payload["allowedUses"] == ["research-read"]
        assert payload["textDigest"] == content_digest({"text": text})
        LocalArtifactStore(artifacts).verify(payload["snapshotDigest"])
        LocalArtifactStore(artifacts).verify(payload["textArtifact"])


def test_adversarial_evidence_cannot_enable_tools(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    assert (
        main(
            [
                "evidence",
                "import",
                str(ADVERSARIAL_IMPORT),
                str(database),
                "--source",
                str(ADVERSARIAL),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    with EventStore(database, require_existing=True) as store:
        encoded = json.dumps(
            [
                item.event.model_dump(mode="json", by_alias=True)
                for item in store.read_events(limit=10)
            ],
            ensure_ascii=False,
        )
        assert INJECT not in encoded
        assert "exfiltrate" not in encoded
    fixture = load_model_fixture(FIXTURE)
    provider = DeterministicMockProvider({fixture.id: fixture})
    with pytest.raises(ModelCapabilityError, match="not allowed"):
        provider.generate(
            GenerateRequest(
                fixture_id=fixture.id,
                requested=frozenset({ModelCapability.GENERATE, ModelCapability.TOOLS}),
            )
        )


def test_pdf_import_extracts_text_without_inlining_it(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    pdf_path = tmp_path / "note.pdf"
    pdf_path.write_bytes(_pdf_bytes("Held-out split note"))
    assert extract_text(pdf_path.read_bytes(), "application/pdf") == "Held-out split note"
    extracted = PdfReader(BytesIO(pdf_path.read_bytes())).pages[0].extract_text()
    assert extracted == "Held-out split note"
    request = load_document(VALID_IMPORT)
    request["evidenceId"] = "evidence.pdf-note"
    request["mediaType"] = "application/pdf"
    request["sourceUri"] = "researchos://local/notes/note.pdf"
    request["sourceType"] = "paper"
    request_path = tmp_path / "import-pdf.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    assert (
        main(
            [
                "evidence",
                "import",
                str(request_path),
                str(database),
                "--source",
                str(pdf_path),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    with EventStore(database, require_existing=True) as store:
        event = store.read_events(limit=1)[0].event
        encoded = json.dumps(event.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        assert "Held-out split note" not in encoded
        assert event.data.payload["mediaType"] == "application/pdf"


def test_duplicate_evidence_id_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    argv = [
        "evidence",
        "import",
        str(VALID_IMPORT),
        str(database),
        "--source",
        str(MARKDOWN),
        "--artifacts",
        str(artifacts),
    ]
    assert main(argv) == 0
    assert main(argv) == 1


def test_citation_binds_evidence_id_digest_and_span() -> None:
    citation = EvidenceCitation.model_validate(load_document(EXAMPLES / "valid" / "citation.json"))
    assert citation.evidence_id == "evidence.eval-split"
    assert citation.span.start == 0
    assert citation.span.end == 12


def test_media_type_mismatch_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    _init_store(database)
    pdf_path = tmp_path / "note.pdf"
    pdf_path.write_bytes(_pdf_bytes("Held-out split note"))
    assert (
        main(
            [
                "evidence",
                "import",
                str(VALID_IMPORT),
                str(database),
                "--source",
                str(pdf_path),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    problem = json.loads(err)
    assert problem["errors"][0]["type"] == "media-type-mismatch"
    assert str(pdf_path) not in err
    assert "Held-out split note" not in err


def test_extract_refusals_do_not_echo_source_text() -> None:
    with pytest.raises(EvidenceExtractError, match="could not extract PDF text") as refused:
        extract_text(b"%PDF-1.1 not a real document", "application/pdf")
    assert "not a real document" not in str(refused.value)
    with pytest.raises(EvidenceExtractError, match="markdown source contains NUL"):
        extract_text(b"hello\x00world", "text/markdown")


def test_omitted_allowed_uses_defaults_to_research_read() -> None:
    document = load_document(VALID_IMPORT)
    del document["allowedUses"]
    parsed = validate_evidence_import_request(document)
    assert [item.value for item in parsed.allowed_uses] == ["research-read"]


def test_compressed_pdf_text_bomb_fails_within_work_bounds() -> None:
    marker = "A" * (MAX_EXTRACTED_CHARS + 1)
    payload = _flate_text_pdf(marker)
    assert len(payload) < 8_192
    started = time.monotonic()
    with pytest.raises(EvidenceExtractError) as refused:
        extract_text(payload, "application/pdf")
    elapsed = time.monotonic() - started
    assert refused.value.code == "text-too-large"
    assert elapsed < MAX_PDF_EXTRACT_SECONDS + 3.0
    assert marker[:32] not in str(refused.value)


def test_pdf_page_limit_is_enforced_before_text_accumulation() -> None:
    payload = _blank_pdf(MAX_PDF_PAGES + 1)
    assert len(PdfReader(BytesIO(payload)).pages) == MAX_PDF_PAGES + 1
    with pytest.raises(EvidenceExtractError, match="page limit") as refused:
        extract_text(payload, "application/pdf")
    assert refused.value.code == "pdf-page-limit"
    with pytest.raises(EvidenceExtractError, match="page limit"):
        extract_pdf_pages(payload)


def test_pdf_worker_timeout_does_not_echo_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=MAX_PDF_EXTRACT_SECONDS)

    monkeypatch.setattr(extract_mod.subprocess, "run", timeout)
    with pytest.raises(EvidenceExtractError, match="time limit") as refused:
        extract_text(_pdf_bytes("SECRET_PAYLOAD"), "application/pdf")
    assert refused.value.code == "pdf-timeout"
    assert "SECRET_PAYLOAD" not in str(refused.value)


def test_pdf_worker_signal_is_resource_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def killed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=-9,
            stdout=b"SECRET_PAYLOAD",
            stderr=b"SECRET_PAYLOAD",
        )

    monkeypatch.setattr(extract_mod.subprocess, "run", killed)
    with pytest.raises(EvidenceExtractError, match="resource limit") as refused:
        extract_text(_pdf_bytes("SECRET_PAYLOAD"), "application/pdf")
    assert refused.value.code == "pdf-resource"
    assert "SECRET_PAYLOAD" not in str(refused.value)


def test_pdf_worker_unknown_stderr_is_pdf_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    def crashed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout=b"SECRET_PAYLOAD",
            stderr=b"Traceback: SECRET_PAYLOAD\n",
        )

    monkeypatch.setattr(extract_mod.subprocess, "run", crashed)
    with pytest.raises(EvidenceExtractError, match="could not extract PDF text") as refused:
        extract_text(_pdf_bytes("SECRET_PAYLOAD"), "application/pdf")
    assert refused.value.code == "pdf-extract"
    assert "SECRET_PAYLOAD" not in str(refused.value)


def test_pdf_worker_run_does_not_echo_invalid_source() -> None:
    code, stdout, stderr = run_worker(b"%PDF-1.1 SECRET_PAYLOAD")
    assert code == 1
    assert stdout == b""
    assert stderr == b"pdf-extract\n"
    assert b"SECRET_PAYLOAD" not in stderr


def test_apply_pdf_resource_limits_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = pytest.importorskip("resource")
    recorded: list[tuple[int, tuple[int, int]]] = []

    def fake_setrlimit(kind: int, spec: tuple[int, int]) -> None:
        recorded.append((kind, spec))

    monkeypatch.setattr(resource, "setrlimit", fake_setrlimit)
    apply_pdf_resource_limits()
    assert recorded

    def denied(_kind: int, _spec: tuple[int, int]) -> None:
        raise OSError("resource limit denied")

    monkeypatch.setattr(resource, "setrlimit", denied)
    apply_pdf_resource_limits()


def test_extract_pdf_pages_stops_when_text_would_exceed_cap() -> None:
    assert extract_pdf_pages(_pdf_bytes("Held-out split note")) == "Held-out split note"
    with pytest.raises(EvidenceExtractError, match="extracted text exceeds") as refused:
        extract_pdf_pages(_flate_text_pdf("A" * (MAX_EXTRACTED_CHARS + 1)))
    assert refused.value.code == "text-too-large"
    with pytest.raises(EvidenceExtractError, match="no extractable text") as empty:
        extract_pdf_pages(_blank_pdf(1))
    assert empty.value.code == "pdf-empty"


def test_extract_guards_payload_size_and_media_suffix() -> None:
    assert media_type_for_suffix(".MD") == "text/markdown"
    assert media_type_for_suffix(".pdf") == "application/pdf"
    with pytest.raises(EvidenceExtractError, match="not supported") as media:
        media_type_for_suffix(".txt")
    assert media.value.code == "unsupported-media"
    with pytest.raises(EvidenceExtractError, match="must be bytes"):
        extract_text("note", "text/markdown")  # type: ignore[arg-type]
    with pytest.raises(EvidenceExtractError, match="empty") as empty:
        extract_text(b"", "text/markdown")
    assert empty.value.code == "empty-source"
    with pytest.raises(EvidenceExtractError, match="size limit") as oversized:
        extract_text(b"a" * (MAX_EVIDENCE_BYTES + 1), "text/markdown")
    assert oversized.value.code == "source-too-large"
    with pytest.raises(EvidenceExtractError, match="extracted text exceeds"):
        extract_text(("a" * (MAX_EXTRACTED_CHARS + 1)).encode("utf-8"), "text/markdown")
    with pytest.raises(EvidenceExtractError, match="not UTF-8"):
        extract_text(b"\xff", "text/markdown")
    with pytest.raises(EvidenceExtractError, match="must be bytes"):
        extract_pdf_pages("note")  # type: ignore[arg-type]
    with pytest.raises(EvidenceExtractError, match="empty"):
        extract_pdf_pages(b"")
    with pytest.raises(EvidenceExtractError, match="size limit"):
        extract_pdf_pages(b"a" * (MAX_EVIDENCE_BYTES + 1))


def test_pdf_worker_result_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    def spawn(returncode: int, stdout: bytes, stderr: bytes = b"") -> None:
        def impl(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=["python"],
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

        monkeypatch.setattr(extract_mod.subprocess, "run", impl)

    spawn(0, b"x" * (MAX_PDF_STDOUT_BYTES + 1))
    with pytest.raises(EvidenceExtractError) as huge:
        extract_text(_pdf_bytes("n"), "application/pdf")
    assert huge.value.code == "text-too-large"

    spawn(0, b"\xff")
    with pytest.raises(EvidenceExtractError) as binary:
        extract_text(_pdf_bytes("n"), "application/pdf")
    assert binary.value.code == "pdf-extract"

    spawn(0, b"")
    with pytest.raises(EvidenceExtractError) as empty:
        extract_text(_pdf_bytes("n"), "application/pdf")
    assert empty.value.code == "pdf-empty"

    spawn(1, b"SECRET", b"pdf-empty\n")
    with pytest.raises(EvidenceExtractError) as coded:
        extract_text(_pdf_bytes("SECRET"), "application/pdf")
    assert coded.value.code == "pdf-empty"
    assert "SECRET" not in str(coded.value)

    spawn(137, b"SECRET", b"SECRET")
    with pytest.raises(EvidenceExtractError) as oom:
        extract_text(_pdf_bytes("SECRET"), "application/pdf")
    assert oom.value.code == "pdf-resource"
    assert "SECRET" not in str(oom.value)

    def missing(*_args: object, **_kwargs: object) -> object:
        raise OSError("worker missing")

    monkeypatch.setattr(extract_mod.subprocess, "run", missing)
    with pytest.raises(EvidenceExtractError) as spawn_err:
        extract_text(_pdf_bytes("n"), "application/pdf")
    assert spawn_err.value.code == "pdf-extract"


def test_pdf_worker_success_and_main_without_rlimit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, stdout, stderr = run_worker(_pdf_bytes("Held-out split note"))
    assert code == 0
    assert stdout == b"Held-out split note"
    assert stderr == b""

    stdin = types.SimpleNamespace(buffer=BytesIO(_pdf_bytes("Held-out split note")))
    stdout_buf = BytesIO()
    stderr_buf = BytesIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(buffer=stdout_buf))
    monkeypatch.setattr(sys, "stderr", types.SimpleNamespace(buffer=stderr_buf))
    monkeypatch.delenv("LROS_PDF_WORKER", raising=False)
    assert pdf_worker_main() == 0
    assert stdout_buf.getvalue() == b"Held-out split note"
    assert stderr_buf.getvalue() == b""


def test_pdf_page_extract_errors_are_pdf_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoomPage:
        def extract_text(self) -> str:
            raise ValueError("parser exploded")

    class BoomReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.pages = [BoomPage()]

    monkeypatch.setattr("pypdf.PdfReader", BoomReader)
    with pytest.raises(EvidenceExtractError, match="could not extract PDF text") as refused:
        extract_pdf_pages(_pdf_bytes("SECRET_PAYLOAD"))
    assert refused.value.code == "pdf-extract"
    assert "SECRET_PAYLOAD" not in str(refused.value)
    assert "parser exploded" not in str(refused.value)


def test_pdf_worker_maps_unexpected_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_worker_mod,
        "extract_pdf_pages",
        lambda _payload: (_ for _ in ()).throw(EvidenceExtractError("x", code="not-listed")),
    )
    code, stdout, stderr = run_worker(b"SECRET_PAYLOAD")
    assert code == 1
    assert stdout == b""
    assert stderr == b"pdf-extract\n"

    monkeypatch.setattr(
        pdf_worker_mod,
        "extract_pdf_pages",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("SECRET_PAYLOAD")),
    )
    code, stdout, stderr = run_worker(b"x")
    assert stderr == b"pdf-extract\n"
    assert b"SECRET_PAYLOAD" not in stderr

    monkeypatch.setattr(pdf_worker_mod, "extract_pdf_pages", lambda _payload: "\ud800")
    code, stdout, stderr = run_worker(b"x")
    assert code == 1
    assert stdout == b""
    assert stderr == b"pdf-extract\n"


def test_pdf_worker_main_applies_limits_and_writes_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied: list[int] = []
    monkeypatch.setattr(pdf_worker_mod, "apply_pdf_resource_limits", lambda: applied.append(1))
    monkeypatch.setenv("LROS_PDF_WORKER", "1")
    stdin = types.SimpleNamespace(buffer=BytesIO(b"%PDF-1.1 SECRET_PAYLOAD"))
    stdout_buf = BytesIO()
    stderr_buf = BytesIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(buffer=stdout_buf))
    monkeypatch.setattr(sys, "stderr", types.SimpleNamespace(buffer=stderr_buf))
    assert pdf_worker_main() == 1
    assert applied == [1]
    assert stdout_buf.getvalue() == b""
    assert stderr_buf.getvalue() == b"pdf-extract\n"
    assert b"SECRET_PAYLOAD" not in stderr_buf.getvalue()
