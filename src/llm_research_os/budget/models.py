"""Closed v0alpha1 payloads for ``budget.reserved`` / ``consumed`` / ``exceeded``."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from llm_research_os.budget.errors import BudgetPayloadError
from llm_research_os.budget.money import MoneyAmount
from llm_research_os.events.models import (
    ActorKind,
    EventDocumentModel,
    EventIdentifier,
    ResearchEvent,
)

TYPE_BUDGET_RESERVED = "budget.reserved"
TYPE_BUDGET_CONSUMED = "budget.consumed"
TYPE_BUDGET_EXCEEDED = "budget.exceeded"
BUDGET_EVENT_TYPES = frozenset({TYPE_BUDGET_RESERVED, TYPE_BUDGET_CONSUMED, TYPE_BUDGET_EXCEEDED})


class BudgetDocumentModel(EventDocumentModel):
    """Frozen budget documents: aliases only, strict, no trimming."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


class BudgetReservedPayload(BudgetDocumentModel):
    budget_id: EventIdentifier = Field(alias="budgetId")
    call_id: EventIdentifier = Field(alias="callId")
    currency: Literal["CNY"] = "CNY"
    amount: MoneyAmount
    cap: MoneyAmount


class BudgetConsumedPayload(BudgetDocumentModel):
    budget_id: EventIdentifier = Field(alias="budgetId")
    call_id: EventIdentifier = Field(alias="callId")
    currency: Literal["CNY"] = "CNY"
    amount: MoneyAmount
    cap: MoneyAmount


class BudgetExceededPayload(BudgetDocumentModel):
    budget_id: EventIdentifier = Field(alias="budgetId")
    call_id: EventIdentifier = Field(alias="callId")
    currency: Literal["CNY"] = "CNY"
    attempted: MoneyAmount
    cap: MoneyAmount


PAYLOAD_MODELS: dict[str, type[EventDocumentModel]] = {
    TYPE_BUDGET_RESERVED: BudgetReservedPayload,
    TYPE_BUDGET_CONSUMED: BudgetConsumedPayload,
    TYPE_BUDGET_EXCEEDED: BudgetExceededPayload,
}

if set(PAYLOAD_MODELS) != BUDGET_EVENT_TYPES:
    raise RuntimeError("PAYLOAD_MODELS must cover exactly the budget event catalog")


def parse_budget_payload(event: ResearchEvent) -> EventDocumentModel:
    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        raise BudgetPayloadError(
            f"event type is not a budget type (event id {event.id})",
            code="unknown-budget-type",
        )
    try:
        validated = model.model_validate(event.data.payload)
    except ValidationError:
        payload_error = BudgetPayloadError(
            f"invalid payload for budget type {event.type} "
            f"(event id {event.id}, sequence {event.sequence})",
            code="invalid-payload",
        )
    else:
        return validated
    raise payload_error


def require_budget_actor(event: ResearchEvent) -> None:
    kind = event.data.actor.kind
    if kind is None:
        raise BudgetPayloadError(
            f"actor kind is required for {event.type} (event id {event.id})",
            code="actor-kind-required",
        )
    if kind is not ActorKind.SYSTEM:
        raise BudgetPayloadError(
            f"actor kind is not allowed for {event.type} (event id {event.id})",
            code="actor-kind-forbidden",
        )
