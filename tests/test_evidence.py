from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pypdf import PdfReader

from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.evidence.errors import EvidenceExtractError, EvidenceRequestError
from llm_research_os.evidence.extract import extract_text
from llm_research_os.evidence.models import DEFAULT_LICENSE, EvidenceCitation
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
