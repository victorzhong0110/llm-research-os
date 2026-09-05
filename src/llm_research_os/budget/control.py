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
    TYPE_BUDGET_RELEASED,
    TYPE_BUDGET_RESERVED,
    BudgetConsumedPayload,
    BudgetExceededPayload,
    BudgetReleasedPayload,
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
class OpenReservation:
    budget_id: str
    call_id: str
    currency: str
    amount: Decimal
    cap: Decimal


@dataclass(frozen=True, slots=True)
class BudgetFold:
    open: tuple[OpenReservation, ...] = ()
    closed_ids: frozenset[str] = frozenset()
    consumed: Decimal = Decimal("0.00")

    @property
    def outstanding(self) -> Decimal:
        total = Decimal("0.00")
        for item in self.open:
            total += item.amount
        return total

    @property
    def open_ids(self) -> frozenset[str]:
        return frozenset(item.budget_id for item in self.open)


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
        fold = BudgetFold()
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


BUDGET_TYPES = frozenset(
    {TYPE_BUDGET_RESERVED, TYPE_BUDGET_CONSUMED, TYPE_BUDGET_EXCEEDED, TYPE_BUDGET_RELEASED}
)


def apply_budget_fold(fold: BudgetFold, event: ResearchEvent, *, project_id: str) -> BudgetFold:
    if event.data.project_id != project_id:
        return fold
    if event.type not in BUDGET_TYPES:
        return fold
    require_budget_actor(event)
    payload = parse_budget_payload(event)
    if isinstance(payload, BudgetReservedPayload):
        return _apply_reserved(fold, payload)
    if isinstance(payload, BudgetConsumedPayload):
        return _close_reservation(fold, payload, add_consumed=True)
    if isinstance(payload, BudgetReleasedPayload):
        return _close_reservation(fold, payload, add_consumed=False)
    if isinstance(payload, BudgetExceededPayload):
        return _apply_exceeded(fold, payload)
    raise BudgetCallError("budget payload type is not foldable", code="unknown-budget-type")


def _known_ids(fold: BudgetFold) -> frozenset[str]:
    return fold.open_ids | fold.closed_ids


def _apply_reserved(fold: BudgetFold, payload: BudgetReservedPayload) -> BudgetFold:
    if payload.budget_id in _known_ids(fold):
        raise BudgetCallError("budgetId is already recorded", code="duplicate-budget-id")
    amount = parse_money(payload.amount)
    cap = parse_money(payload.cap)
    reservation = OpenReservation(
        budget_id=payload.budget_id,
        call_id=payload.call_id,
        currency=payload.currency,
        amount=amount,
        cap=cap,
    )
    return BudgetFold(
        open=(*fold.open, reservation),
        closed_ids=fold.closed_ids,
        consumed=fold.consumed,
    )


def _close_reservation(
    fold: BudgetFold,
    payload: BudgetConsumedPayload | BudgetReleasedPayload,
    *,
    add_consumed: bool,
) -> BudgetFold:
    if payload.budget_id in fold.closed_ids:
        raise BudgetCallError("budgetId is already complete", code="duplicate-budget-id")
    current = next((item for item in fold.open if item.budget_id == payload.budget_id), None)
    if current is None:
        raise BudgetCallError(
            "budget consumption has no matching reserve",
            code="orphan-budget-id",
        )
    amount = parse_money(payload.amount)
    cap = parse_money(payload.cap)
    if payload.call_id != current.call_id:
        raise BudgetCallError(
            "budget callId does not match the reservation",
            code="reservation-mismatch",
        )
    if payload.currency != current.currency:
        raise BudgetCallError(
            "budget currency does not match the reservation",
            code="reservation-mismatch",
        )
    if cap != current.cap:
        raise BudgetCallError(
            "budget cap does not match the reservation",
            code="reservation-mismatch",
        )
    if add_consumed:
        if amount > current.amount:
            raise BudgetCallError(
                "budget consume amount exceeds the reservation",
                code="consume-exceeds-reserve",
            )
        consumed = fold.consumed + amount
    else:
        if amount != current.amount:
            raise BudgetCallError(
                "budget release amount must equal the reservation",
                code="reservation-mismatch",
            )
        consumed = fold.consumed
    remaining = tuple(item for item in fold.open if item.budget_id != payload.budget_id)
    return BudgetFold(
        open=remaining,
        closed_ids=fold.closed_ids | {payload.budget_id},
        consumed=consumed,
    )


def _apply_exceeded(fold: BudgetFold, payload: BudgetExceededPayload) -> BudgetFold:
    if payload.budget_id in _known_ids(fold):
        raise BudgetCallError("budgetId is already recorded", code="duplicate-budget-id")
    parse_money(payload.attempted)
    parse_money(payload.cap)
    return BudgetFold(
        open=fold.open,
        closed_ids=fold.closed_ids | {payload.budget_id},
        consumed=fold.consumed,
    )


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
