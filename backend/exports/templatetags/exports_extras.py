from decimal import Decimal

from django import template

register = template.Library()
NBSP = " "


@register.filter
def uah(value: Decimal | float | int) -> str:
    """12345.5 -> '12 345,50' (non-breaking space as thousands separator)."""
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, frac = f"{d:.2f}".split(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    groups: list[str] = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return f"{sign}{NBSP.join(groups)},{frac}"
