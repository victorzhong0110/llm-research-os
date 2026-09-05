from __future__ import annotations

from pathlib import Path

import pytest

from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.errors import BudgetCallError
from llm_research_os.budget.models import (
    TYPE_BUDGET_CONSUMED,
    TYPE_BUDGET_RELEASED,
    TYPE_BUDGET_RESERVED,
)
from llm_research_os.budget.money import CURRENCY_CNY
from llm_research_os.providers.compat_requests import validate_compat_generate_request
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
REMOTE_REQUEST = ROOT / "examples" / "openai-compat-requests" / "valid" / "remote.json"


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
        assert store.last_sequence() == 1
        consumed = budget.append(request.budget_draft(TYPE_BUDGET_CONSUMED, _terms()))
        assert consumed.event.type == TYPE_BUDGET_CONSUMED
        fold = budget.rebuild().fold
        assert fold.open == ()
        assert str(fold.consumed) == "1.00"
