"""CNY amounts as I-JSON decimal strings with two fraction digits."""

from __future__ import annotations

import re
from decimal import Decimal
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
    if type(value) is not str or re.fullmatch(MONEY_PATTERN, value) is None:
        raise BudgetError("money amount must be a two-decimal CNY string", code="invalid-money")
    return Decimal(value)


def format_money(value: Decimal) -> str:
    if not value.is_finite() or value < 0 or value > Decimal("9999999.99"):
        raise BudgetError("money amount is outside the supported range", code="invalid-money")
    quantized = value.quantize(Decimal("0.01"))
    rendered = f"{quantized:.2f}"
    parse_money(rendered)
    return rendered
