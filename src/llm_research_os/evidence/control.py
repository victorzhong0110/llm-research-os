"""Project-scoped CAS append for ``evidence.imported`` facts."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm_research_os.artifacts.store import MAX_PUT_BYTES, LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.evidence.errors import (
    EvidenceCallError,
    EvidenceExtractError,
    EvidencePayloadError,
)
from llm_research_os.evidence.extract import MAX_EVIDENCE_BYTES, extract_text, media_type_for_suffix
from llm_research_os.evidence.models import (
    TYPE_EVIDENCE_IMPORTED,
    EvidenceImportedPayload,
    parse_evidence_payload,
    require_evidence_actor,
)
from llm_research_os.evidence.requests import EvidenceImportRequestDocument
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class EvidenceFold:
    evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class EvidenceControlHead:
    last_sequence: int
    fold: EvidenceFold


@dataclass(frozen=True, slots=True)
class EvidenceImportResult:
    stored: StoredEvent
    snapshot_digest: str
    text_digest: str


class EvidenceControl:
    """Import one local file into CAS, then CAS-append ``evidence.imported``."""

    def __init__(self, store: EventStore, *, project_id: str, page_size: int = 100) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._project_id = project_id

    def rebuild(self) -> EvidenceControlHead:
        high_water = self._store.freeze_high_water()
        fold = EvidenceFold(evidence_ids=frozenset())
        for stored in replay_events(
            self._store,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            fold = apply_evidence_fold(fold, stored.event, project_id=self._project_id)
        return EvidenceControlHead(last_sequence=high_water, fold=fold)

    def import_source(
        self,
        request: EvidenceImportRequestDocument,
        source: Path,
        artifacts: LocalArtifactStore,
    ) -> EvidenceImportResult:
        if request.project_id != self._project_id:
            raise EvidenceCallError(
                "request projectId does not match this EvidenceControl",
                code="project-mismatch",
            )
        payload = _read_source_bytes(source)
        inferred = media_type_for_suffix(source.suffix)
        if inferred != request.media_type:
            raise EvidenceExtractError(
                "source suffix does not match request mediaType",
                code="media-type-mismatch",
            )
        text = extract_text(payload, request.media_type)
        encoded_text = text.encode("utf-8")
        if len(encoded_text) > MAX_PUT_BYTES:
            raise EvidenceExtractError("extracted text exceeds size limit", code="text-too-large")
        snapshot = artifacts.put(source)
        expected_snapshot = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if snapshot.digest != expected_snapshot:
            raise EvidenceExtractError(
                "import source changed during read",
                code="source-changed",
            )
        text_record = artifacts.put_bytes(encoded_text)
        text_digest = content_digest({"text": text})
        draft = request.event_draft(
            snapshot_digest=snapshot.digest,
            text_digest=text_digest,
            text_artifact=text_record.digest,
            byte_length=len(payload),
            text_characters=len(text),
        )
        stored = self._append_one(draft)
        return EvidenceImportResult(
            stored=stored,
            snapshot_digest=snapshot.digest,
            text_digest=text_digest,
        )

    def _append_one(self, document: dict[str, Any]) -> StoredEvent:
        head = self.rebuild()
        frozen_head = head.last_sequence
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise EvidenceCallError(str(exc), code="invalid-draft") from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise EvidenceCallError(
                "EvidenceControl does not accept store-assigned fields; "
                f"caller supplied: {supplied}",
                code="store-assigned-fields",
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise EvidenceCallError("global event sequence is exhausted", code="sequence-exhausted")
        preflight_document = dict(draft)
        preflight_document.update(
            {
                "sequence": str(frozen_head + 1),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        preflight_event = _validate_preflight_event(preflight_document)
        if preflight_event.data.project_id != self._project_id:
            raise EvidenceCallError(
                "event projectId does not match this EvidenceControl",
                code="project-mismatch",
            )
        apply_evidence_fold(head.fold, preflight_event, project_id=self._project_id)
        return self._store.append(draft, expected_last_sequence=frozen_head)


def apply_evidence_fold(
    fold: EvidenceFold, event: ResearchEvent, *, project_id: str
) -> EvidenceFold:
    if event.data.project_id != project_id:
        return fold
    if event.type != TYPE_EVIDENCE_IMPORTED:
        return fold
    require_evidence_actor(event)
    payload = parse_evidence_payload(event)
    if not isinstance(payload, EvidenceImportedPayload):
        raise EvidenceCallError(
            "evidence payload type is not foldable",
            code="unknown-evidence-type",
        )
    if payload.evidence_id in fold.evidence_ids:
        raise EvidenceCallError("evidenceId is already recorded", code="duplicate-evidence-id")
    return EvidenceFold(evidence_ids=fold.evidence_ids | {payload.evidence_id})


def _read_source_bytes(source: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError:
        raise EvidenceExtractError("could not open import source", code="source-open") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceExtractError(
                "import source is not a regular file",
                code="source-not-file",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_EVIDENCE_BYTES:
                raise EvidenceExtractError(
                    "import source exceeds size limit",
                    code="source-too-large",
                )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_page_size(page_size: int) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")
    return page_size


def _validate_preflight_event(document: dict[str, Any]) -> ResearchEvent:
    try:
        validated = validate_event_document(document)
    except ValidationError:
        payload_error = EvidencePayloadError(
            "event draft failed ResearchEvent validation",
            code="invalid-event",
        )
    else:
        return validated
    raise payload_error
