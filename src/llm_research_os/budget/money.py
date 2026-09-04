"""CNY amounts as I-JSON decimal strings with two fraction digits."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import StringConstraints

from llm_research_os.budget.errors import BudgetError

CURRENCY_CNY = "CNY"
ZERO_MONEY = "0.00"
MONEY_PATTERN = r"^(?:0|[1-9][0-9]{0,6})\.[0-9]{2}$"
MoneyAmount = Annotated[
    str,
    StringConstraints(
        min_length=4,
        max_length=11,
        strip_whitespace=False,
        pattern=MONEY_PATTERN,
    ),
]


def parse_money(value: str) -> Decimal:
    if type(value) is not str:
        raise BudgetError("money amount must be a decimal string", code="invalid-money")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise BudgetError("money amount must be a decimal string", code="invalid-money") from None
    quantized = amount.quantize(Decimal("0.01"))
    if quantized != amount or amount < 0:
        raise BudgetError("money amount must be a two-decimal CNY string", code="invalid-money")
    return amount


def format_money(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    rendered = f"{quantized:.2f}"
    parse_money(rendered)
    return rendered
