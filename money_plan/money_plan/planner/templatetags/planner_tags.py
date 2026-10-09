from decimal import Decimal

from django import template
from django.utils.dates import MONTHS_3

register = template.Library()


@register.filter
def baht(value) -> str:
    if value is None or value == "":
        return "฿0"
    value = Decimal(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    text = f"{value:,.0f}" if value == value.to_integral() else f"{value:,.2f}"
    return f"{sign}฿{text}"


@register.filter
def month_label(value: str) -> str:
    """'2027-01' -> 'Jan 2027'; the month name follows the active language."""
    year, month = value.split("-")
    return f"{str(MONTHS_3[int(month)]).capitalize()} {year}"


@register.filter
def tint(color: str, pct: int = 12) -> str:
    return f"color-mix(in srgb, {color} {pct}%, white)"


@register.filter
def pct(value) -> str:
    return f"{min(max(Decimal(value), 0), 100):.0f}"
