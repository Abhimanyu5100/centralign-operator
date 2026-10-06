"""Rupee text <-> integer paise (risks N.47, 1.9). Exact `Decimal` arithmetic, never floats."""

import re
from decimal import Decimal

AMOUNT_HELP = "Enter the amount in rupees without commas, for example 12500.00"
_AMOUNT = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def parse_rupees(text: str) -> int:
    """'12500.50' -> 1250050. Raises ValueError (message = what to type instead) on anything else:
    commas, currency signs, exponents, signs, more than two decimals."""
    value = text.strip()
    if not _AMOUNT.match(value):
        raise ValueError(AMOUNT_HELP)
    return int(Decimal(value) * 100)


def format_inr(paise: int) -> str:
    """Indian digit grouping for display: 6240000 -> '₹62,400.00', 12345678900 -> '₹12,34,56,789.00'."""
    rupees, fraction = divmod(paise, 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join([*groups, tail]) + f".{fraction:02d}"
