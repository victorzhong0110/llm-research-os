from __future__ import annotations

from pathlib import Path

import pytest

from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.errors import BudgetCallError, BudgetExceededError, BudgetPayloadError
from llm_research_os.budget.models import (
    TYPE_BUDGET_CONSUMED,
    TYPE_BUDGET_EXCEEDED,
    TYPE_BUDGET_LIMIT_RECORDED,
    TYPE_BUDGET_RELEASED,
    TYPE_BUDGET_RESERVED,
)
from llm_research_os.budget.money import CURRENCY_CNY
from llm_research_os.budget.requests import budget_limit_draft
from llm_research_os.providers.compat_requests import (
    OpenAICompatGenerateRequestDocument,
    validate_compat_generate_request,
)
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
REMOTE_REQUEST = ROOT / "examples" / "openai-compat-requests" / "valid" / "remote.json"


def _approve(
    store: EventStore, project_id: str, cap: str, event_id: str = "evt.budget.limit.1"
) -> None:
    BudgetControl(store, project_id=project_id).append(
        budget_limit_draft(project_id=project_id, cap=cap, event_id=event_id)
    )


def _terms(**overrides: str) -> dict[str, str]:
    payload = {
        "budgetId": "budget.compat-remote.1",
        "callId": "call.compat-remote.1",
        "currency": CURRENCY_CNY,
        "amount": "1.00",
        "cap": "30.00",
    }
    payload.update(overrides)
    return payload


def test_consume_and_release_must_match_reservation(tmp_path: Path) -> None:
    request = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=request.project_id)
        _approve(store, request.project_id, "30.00")
        budget.append(request.budget_draft(TYPE_BUDGET_RESERVED, _terms()))
        mismatches = (
            (_terms(callId="call.compat-remote.other"), "reservation-mismatch"),
            (_terms(cap="29.00"), "reservation-mismatch"),
            (_terms(amount="1.01"), "consume-exceeds-reserve"),
        )
        for payload, code in mismatches:
            with pytest.raises(BudgetCallError) as captured:
                budget.append(request.budget_draft(TYPE_BUDGET_CONSUMED, payload))
            assert captured.value.code == code
        with pytest.raises(BudgetCallError) as captured:
            budget.append(
                request.budget_draft(
                    TYPE_BUDGET_RELEASED,
                    {**_terms(amount="0.50"), "reasonCode": "transport"},
                )
            )
        assert captured.value.code == "reservation-mismatch"
        assert store.last_sequence() == 2
        consumed = budget.append(request.budget_draft(TYPE_BUDGET_CONSUMED, _terms()))
        assert consumed.event.type == TYPE_BUDGET_CONSUMED
        fold = budget.rebuild().fold
        assert fold.open == ()
        assert str(fold.consumed) == "1.00"


def test_append_reserved_after_peer_reservation_is_rejected_by_fold(tmp_path: Path) -> None:
    first = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    second_document = load_document(REMOTE_REQUEST)
    second_document["callId"] = "call.compat-remote.2"
    second_document["budgetId"] = "budget.compat-remote.2"
    events = second_document["events"]
    assert isinstance(events, dict)
    for _key, identity in events.items():
        assert isinstance(identity, dict)
        event_id = identity["id"]
        assert isinstance(event_id, str)
        identity["id"] = f"{event_id.rsplit('.', 1)[0]}.2"
    second = validate_compat_generate_request(second_document)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=first.project_id)
        _approve(store, first.project_id, "30.00")
        budget.append(
            first.budget_draft(
                TYPE_BUDGET_RESERVED,
                {
                    "budgetId": first.budget_id,
                    "callId": first.call_id,
                    "currency": CURRENCY_CNY,
                    "amount": "20.00",
                    "cap": "30.00",
                },
            )
        )
        with pytest.raises(BudgetCallError) as captured:
            budget.append(
                second.budget_draft(
                    TYPE_BUDGET_RESERVED,
                    {
                        "budgetId": second.budget_id,
                        "callId": second.call_id,
                        "currency": CURRENCY_CNY,
                        "amount": "20.00",
                        "cap": "30.00",
                    },
                )
            )
        assert captured.value.code == "reservation-exceeds-cap"
        assert store.last_sequence() == 2
        fold = budget.rebuild().fold
        assert str(fold.outstanding) == "20.00"


def _reserve_terms(
    request: OpenAICompatGenerateRequestDocument, *, amount: str, cap: str
) -> dict[str, str]:
    return {
        "budgetId": request.budget_id,
        "callId": request.call_id,
        "currency": CURRENCY_CNY,
        "amount": amount,
        "cap": cap,
    }


def test_reserve_or_exceed_records_exceeded_after_peer_reservation(tmp_path: Path) -> None:
    first = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    second_document = load_document(REMOTE_REQUEST)
    second_document["callId"] = "call.compat-remote.2"
    second_document["budgetId"] = "budget.compat-remote.2"
    events = second_document["events"]
    assert isinstance(events, dict)
    for _key, identity in events.items():
        assert isinstance(identity, dict)
        event_id = identity["id"]
        assert isinstance(event_id, str)
        identity["id"] = f"{event_id.rsplit('.', 1)[0]}.2"
    second = validate_compat_generate_request(second_document)
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=first.project_id)
        _approve(store, first.project_id, "30.00")
        reserved = budget.reserve_or_exceed(
            first.budget_draft(
                TYPE_BUDGET_RESERVED,
                _reserve_terms(first, amount="20.00", cap="30.00"),
            ),
            first.budget_draft(
                TYPE_BUDGET_EXCEEDED,
                {
                    "budgetId": first.budget_id,
                    "callId": first.call_id,
                    "currency": CURRENCY_CNY,
                    "attempted": "20.00",
                    "cap": "30.00",
                },
            ),
        )
        assert reserved.event.type == TYPE_BUDGET_RESERVED
        with pytest.raises(BudgetExceededError):
            budget.reserve_or_exceed(
                second.budget_draft(
                    TYPE_BUDGET_RESERVED,
                    _reserve_terms(second, amount="20.00", cap="30.00"),
                ),
                second.budget_draft(
                    TYPE_BUDGET_EXCEEDED,
                    {
                        "budgetId": second.budget_id,
                        "callId": second.call_id,
                        "currency": CURRENCY_CNY,
                        "attempted": "20.00",
                        "cap": "30.00",
                    },
                ),
            )
        types = [item.event.type for item in store.read_events(limit=10)]
        assert types == [TYPE_BUDGET_LIMIT_RECORDED, TYPE_BUDGET_RESERVED, TYPE_BUDGET_EXCEEDED]
        fold = budget.rebuild().fold
        assert str(fold.outstanding) == "20.00"


def test_positive_reservation_requires_recorded_limit(tmp_path: Path) -> None:
    request = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=request.project_id)
        with pytest.raises(BudgetCallError) as captured:
            budget.append(request.budget_draft(TYPE_BUDGET_RESERVED, _terms()))
        assert captured.value.code == "budget-limit-missing"
        assert store.last_sequence() == 0


def test_request_cannot_raise_cap_without_a_new_limit(tmp_path: Path) -> None:
    request = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=request.project_id)
        _approve(store, request.project_id, "1.00")
        with pytest.raises(BudgetCallError) as captured:
            budget.reserve_or_exceed(
                request.budget_draft(
                    TYPE_BUDGET_RESERVED,
                    _reserve_terms(request, amount="1.00", cap="100.00"),
                ),
                request.budget_draft(
                    TYPE_BUDGET_EXCEEDED,
                    {
                        "budgetId": request.budget_id,
                        "callId": request.call_id,
                        "currency": CURRENCY_CNY,
                        "attempted": "1.00",
                        "cap": "100.00",
                    },
                ),
            )
        assert captured.value.code == "budget-limit-mismatch"
        assert store.last_sequence() == 1
        _approve(store, request.project_id, "100.00", event_id="evt.budget.limit.2")
        raised = budget.append(
            request.budget_draft(
                TYPE_BUDGET_RESERVED,
                _reserve_terms(request, amount="1.00", cap="100.00"),
            )
        )
        assert raised.event.type == TYPE_BUDGET_RESERVED
        fold = budget.rebuild().fold
        assert str(fold.approved_cap) == "100.00"


def test_zero_reservation_does_not_require_a_recorded_limit(tmp_path: Path) -> None:
    request = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=request.project_id)
        reserved = budget.append(
            request.budget_draft(
                TYPE_BUDGET_RESERVED,
                _reserve_terms(request, amount="0.00", cap="0.00"),
            )
        )
        assert reserved.event.type == TYPE_BUDGET_RESERVED
        fold = budget.rebuild().fold
        assert fold.approved_cap is None
        assert str(fold.outstanding) == "0.00"


def test_limit_fact_requires_a_human_actor(tmp_path: Path) -> None:
    request = validate_compat_generate_request(load_document(REMOTE_REQUEST))
    database = tmp_path / "research.db"
    draft = budget_limit_draft(project_id=request.project_id, cap="1.00")
    draft["data"]["actor"]["kind"] = "system"
    with EventStore(database) as store:
        budget = BudgetControl(store, project_id=request.project_id)
        with pytest.raises(BudgetPayloadError) as captured:
            budget.append(draft)
        assert captured.value.code == "actor-kind-forbidden"
        assert store.last_sequence() == 0
