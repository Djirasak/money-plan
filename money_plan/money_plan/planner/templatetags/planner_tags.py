from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django import template
from django.utils.dates import MONTHS
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

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


BUDDHIST_ERA_OFFSET = 543


def display_year(year: int) -> int:
    """Thai UI shows the Buddhist Era (B.E.); everything stored and sent stays C.E."""
    return year + BUDDHIST_ERA_OFFSET if get_language().startswith("th") else year


@register.filter
def month_label(value: str) -> str:
    """'2027-01' -> 'January 2027' (en) or 'January 2570' with the Thai month name (th)."""
    year, month = value.split("-")
    return f"{MONTHS[int(month)]} {display_year(int(year))}"


@register.filter
def tint(color: str, pct: int = 12) -> str:
    return f"color-mix(in srgb, {color} {pct}%, var(--surface))"


@register.filter
def pct(value) -> str:
    return f"{min(max(Decimal(value), 0), 100):.0f}"


ICON_DIR = Path(__file__).resolve().parents[2] / "templates" / "icons"


@lru_cache(maxsize=None)
def _icon_svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text().strip()


@register.simple_tag
def icon(name: str, css_class: str = "size-5") -> str:
    """Inline lucide icon (``pnpm run icons`` syncs the set). Decorative by default:
    the control that holds it must carry the accessible name."""
    svg = _icon_svg(name).replace(
        "<svg",
        f'<svg class="{escape(css_class)}" aria-hidden="true" focusable="false"',
        1,
    )
    return mark_safe(svg)  # noqa: S308 - files we ship, class is escaped
