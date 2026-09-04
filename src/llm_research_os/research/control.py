"""Project-scoped CAS append for research decision facts.

EventStore remains the only fact source. ResearchLedger is a rebuildable fold:
it is discarded when the caller rebuilds from the verified prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.research.errors import ResearchControlError, ResearchPayloadError
from llm_research_os.research.ledger import LedgerFold, ResearchLedgerProjection
from llm_research_os.research.models import DECISION_EVENT_TYPES, ResearchLedger
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class ResearchControlHead:
    last_sequence: int
    snapshot: ResearchLedger
    fold: LedgerFold


@dataclass(frozen=True, slots=True)
class ResearchControlResult:
    stored: StoredEvent
    snapshot: ResearchLedger


class ResearchControl:
    """Validate one research-decision draft against a frozen ledger, then CAS-append it.

    ``last_sequence`` is the global EventStore head used as the CAS token.
    Conflicts are not retried. The ledger is not persisted.
    """

    def __init__(self, store: EventStore, *, project_id: str, page_size: int = 100) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._projection = ResearchLedgerProjection(project_id=project_id)
        self._project_id = self._projection.project_id

    def rebuild(self) -> ResearchControlHead:
        """Replay the frozen global log and fold this project's research facts."""

        high_water = self._store.freeze_high_water()
        fold: LedgerFold | None = None
        for stored in replay_events(
            self._store,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            fold = self._projection.apply(fold, stored.event)
        if fold is None:
            fold = LedgerFold()
        snapshot = self._projection.snapshot(fold, high_water)
        return ResearchControlHead(last_sequence=high_water, snapshot=snapshot, fold=fold)

    def append(self, document: dict[str, Any]) -> ResearchControlResult:
        """Preflight one research-decision draft, then append it at the frozen head."""

        head = self.rebuild()
        frozen_head = head.last_sequence
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise ResearchControlError(str(exc), code="invalid-draft") from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise ResearchControlError(
                "ResearchControl does not accept store-assigned fields; "
                f"caller supplied: {supplied}",
                code="store-assigned-fields",
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise ResearchControlError(
                "global event sequence is exhausted",
                code="sequence-exhausted",
            )
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
            raise ResearchControlError(
                "event projectId does not match this ResearchControl",
                code="project-mismatch",
            )
        if preflight_event.type not in DECISION_EVENT_TYPES:
            raise ResearchControlError(
                "event type is not a research decision type",
                code="unknown-research-type",
            )
        preflight_fold = self._projection.apply(head.fold, preflight_event)
        if preflight_fold is None:
            raise ResearchControlError(
                "research preflight produced no ledger fold",
                code="empty-preflight",
            )
        stored = self._store.append(draft, expected_last_sequence=frozen_head)
        committed_fold = self._projection.apply(head.fold, stored.event)
        snapshot = self._projection.snapshot(committed_fold, stored.sequence)
        return ResearchControlResult(stored=stored, snapshot=snapshot)


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
        payload_error = ResearchPayloadError(
            "event draft failed ResearchEvent validation",
            code="invalid-event",
        )
    else:
        return validated
    raise payload_error
