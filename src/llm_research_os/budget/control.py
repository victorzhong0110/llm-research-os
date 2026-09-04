"""Project-scoped CAS append for ``budget.*`` facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from llm_research_os.budget.errors import BudgetCallError, BudgetPayloadError
from llm_research_os.budget.models import (
    TYPE_BUDGET_CONSUMED,
    TYPE_BUDGET_EXCEEDED,
    TYPE_BUDGET_RESERVED,
    BudgetConsumedPayload,
    BudgetExceededPayload,
    BudgetReservedPayload,
    parse_budget_payload,
    require_budget_actor,
)
from llm_research_os.budget.money import parse_money
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class BudgetFold:
    open_ids: frozenset[str]
    closed_ids: frozenset[str]
    consumed: Decimal


@dataclass(frozen=True, slots=True)
class BudgetHead:
    last_sequence: int
    fold: BudgetFold


class BudgetControl:
    """CAS-append one budget fact against a frozen consumed total."""

    def __init__(self, store: EventStore, *, project_id: str, page_size: int = 100) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._project_id = project_id

    def rebuild(self) -> BudgetHead:
        high_water = self._store.freeze_high_water()
        fold = BudgetFold(
            open_ids=frozenset(),
            closed_ids=frozenset(),
            consumed=Decimal("0.00"),
        )
        for stored in replay_events(
            self._store,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            fold = apply_budget_fold(fold, stored.event, project_id=self._project_id)
        return BudgetHead(last_sequence=high_water, fold=fold)

    def append(self, document: dict[str, Any]) -> StoredEvent:
        head = self.rebuild()
        frozen_head = head.last_sequence
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise BudgetCallError(str(exc), code="invalid-draft") from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise BudgetCallError(
                f"BudgetControl does not accept store-assigned fields; caller supplied: {supplied}",
                code="store-assigned-fields",
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise BudgetCallError("global event sequence is exhausted", code="sequence-exhausted")
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
            raise BudgetCallError(
                "event projectId does not match this BudgetControl",
                code="project-mismatch",
            )
        apply_budget_fold(head.fold, preflight_event, project_id=self._project_id)
        return self._store.append(draft, expected_last_sequence=frozen_head)


def apply_budget_fold(fold: BudgetFold, event: ResearchEvent, *, project_id: str) -> BudgetFold:
    if event.data.project_id != project_id:
        return fold
    if event.type not in {TYPE_BUDGET_RESERVED, TYPE_BUDGET_CONSUMED, TYPE_BUDGET_EXCEEDED}:
        return fold
    require_budget_actor(event)
    payload = parse_budget_payload(event)
    if isinstance(payload, BudgetReservedPayload):
        if payload.budget_id in fold.open_ids or payload.budget_id in fold.closed_ids:
            raise BudgetCallError("budgetId is already recorded", code="duplicate-budget-id")
        parse_money(payload.amount)
        parse_money(payload.cap)
        return BudgetFold(
            open_ids=fold.open_ids | {payload.budget_id},
            closed_ids=fold.closed_ids,
            consumed=fold.consumed,
        )
    if isinstance(payload, BudgetConsumedPayload):
        if payload.budget_id in fold.closed_ids:
            raise BudgetCallError("budgetId is already complete", code="duplicate-budget-id")
        if payload.budget_id not in fold.open_ids:
            raise BudgetCallError(
                "budget consumption has no matching reserve",
                code="orphan-budget-id",
            )
        return BudgetFold(
            open_ids=fold.open_ids - {payload.budget_id},
            closed_ids=fold.closed_ids | {payload.budget_id},
            consumed=fold.consumed + parse_money(payload.amount),
        )
    if isinstance(payload, BudgetExceededPayload):
        if payload.budget_id in fold.open_ids or payload.budget_id in fold.closed_ids:
            raise BudgetCallError("budgetId is already recorded", code="duplicate-budget-id")
        parse_money(payload.attempted)
        parse_money(payload.cap)
        return BudgetFold(
            open_ids=fold.open_ids,
            closed_ids=fold.closed_ids | {payload.budget_id},
            consumed=fold.consumed,
        )
    raise BudgetCallError("budget payload type is not foldable", code="unknown-budget-type")


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
        payload_error = BudgetPayloadError(
            "event draft failed ResearchEvent validation",
            code="invalid-event",
        )
    else:
        return validated
    raise payload_error
