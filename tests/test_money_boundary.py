from decimal import Decimal

import pytest

from llm_research_os.budget.errors import BudgetError
from llm_research_os.budget.money import format_money, parse_money


@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "1e2",
        "1",
        "1.0",
        "-0.00",
        " 1.00",
        "01.00",
        "10000000.00",
        "0.001",
    ],
)
def test_noncanonical_money_is_domain_error(value: str) -> None:
    with pytest.raises(BudgetError, match="two-decimal"):
        parse_money(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "10000000"])
def test_format_money_rejects_unbounded_values(value: str) -> None:
    with pytest.raises(BudgetError, match="supported range"):
        format_money(Decimal(value))


def test_money_edges_roundtrip() -> None:
    for value in ["0.00", "0.01", "9999999.99"]:
        assert format_money(parse_money(value)) == value
