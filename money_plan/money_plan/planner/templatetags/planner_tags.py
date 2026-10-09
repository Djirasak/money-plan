from decimal import Decimal

from django import template

register = template.Library()

THAI_MONTHS = [
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
]  # fmt: skip


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
def thai_month(value: str) -> str:
    year, month = value.split("-")
    return f"{THAI_MONTHS[int(month) - 1]} {year}"


@register.filter
def tint(color: str, pct: int = 12) -> str:
    return f"color-mix(in srgb, {color} {pct}%, white)"


@register.filter
def pct(value) -> str:
    return f"{min(max(Decimal(value), 0), 100):.0f}"
