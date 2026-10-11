from decimal import Decimal
from functools import cache
from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils import timezone
from django.utils.dates import MONTHS
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from money_plan.planner.pile_icons import DEFAULT_ICONS
from money_plan.planner.pile_icons import PILE_ICON_KEYS

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
    return f"color-mix(in srgb, {color} {pct}%, var(--card))"


@register.filter
def pct(value) -> str:
    return f"{min(max(Decimal(value), 0), 100):.0f}"


ICON_DIR = Path(__file__).resolve().parents[2] / "templates" / "icons"


@cache
def _icon_svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text().strip()


# (key, OKLCH hue, label) - keep in step with [data-color] in tailwind.css; indigo is the default
COLOR_THEMES = [
    ("indigo", 277, gettext_noop("Indigo")),
    ("violet", 300, gettext_noop("Violet")),
    ("pink", 350, gettext_noop("Pink")),
    ("rose", 15, gettext_noop("Rose")),
    ("red", 27, gettext_noop("Red")),
    ("orange", 50, gettext_noop("Orange")),
    ("amber", 75, gettext_noop("Amber")),
    ("green", 145, gettext_noop("Green")),
    ("emerald", 165, gettext_noop("Emerald")),
    ("teal", 190, gettext_noop("Teal")),
    ("sky", 235, gettext_noop("Sky")),
    ("blue", 255, gettext_noop("Blue")),
]


@register.simple_tag
def color_themes() -> list[dict]:
    return [
        {"key": key, "hue": hue, "label": _(label)} for key, hue, label in COLOR_THEMES
    ]


@register.simple_tag
def static_v(path: str) -> str:
    """``{% static %}`` plus ``?v=<file modified time>`` while DEBUG is on, so an edited
    CSS/JS file is fetched again at once instead of coming from the browser/CDN cache."""
    url = static(path)
    if not settings.DEBUG:
        return url
    found = finders.find(path)
    return (
        f"{url}?v={int(Path(found).stat().st_mtime)}" if isinstance(found, str) else url
    )


@register.filter
def initial(user) -> str:
    """The letter on a user's avatar: first letter of their name, else of their email."""
    text = (
        getattr(user, "name", "")
        or getattr(user, "first_name", "")
        or getattr(user, "email", "")
        or getattr(user, "username", "")
        or "?"
    ).strip()
    return text[:1].upper() if text else "?"


@register.simple_tag
def pile_icon(pile, size: str = "md") -> str:
    """A pile's icon on a soft tile in the pile's colour (``pile`` is a Pile or the
    dict of a shared template). ``size``: md (cards) or sm (rows)."""
    get = (
        pile.get
        if isinstance(pile, dict)
        else lambda name, default="": getattr(pile, name, default)
    )
    color = get("color", "#5b5bf0")
    name = get("icon") or DEFAULT_ICONS.get(get("kind", "budget"), "wallet")
    if name not in PILE_ICON_KEYS:
        name = "wallet"
    tile = "pile-icon pile-icon-sm" if size == "sm" else "pile-icon"
    svg = icon(name, "size-3.5" if size == "sm" else "size-4")
    return mark_safe(  # noqa: S308 - color matches ^#rrggbb$, the icon is one of our files
        f'<span class="{tile}" style="--pc:{escape(color)}" aria-hidden="true">{svg}</span>',
    )


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


@register.inclusion_tag("users/_password_rules.html")
def password_rules() -> dict:
    """The password rules from AUTH_PASSWORD_VALIDATORS as a checklist that turns
    green or red while typing (project.js); the server still has the last word."""
    return {
        "rules": [
            {"text": validator.get_help_text(), "min": validator.min_length}
            for validator in password_validation.get_default_password_validators()
            if hasattr(validator, "min_length")
        ],
    }


@register.inclusion_tag("planner/_month_picker.html")
def month_picker(name: str, value: str, field_id: str, label: str) -> dict:
    """Month + year dropdowns that post ``<name>_month`` / ``<name>_year`` (C.E. values).

    The Thai UI shows years as B.E., but the submitted value is always C.E.
    """
    today = timezone.localdate().year
    year, month = (int(part) for part in (value or f"{today}-01").split("-"))
    years = range(min(today - 5, year), max(today + 5, year) + 1)
    return {
        "name": name,
        "field_id": field_id,
        "label": label,
        "months": [(n, MONTHS[n]) for n in range(1, 13)],
        "years": [(y, display_year(y)) for y in years],
        "sel_month": month,
        "sel_year": year,
    }


@register.filter
def target_label(pile) -> str:
    """Human description of a pile's goal, e.g. '฿150,000' or '60% of salary x 6 months'."""
    if pile.has_salary_target:
        return _("%(percent)s%% of salary x %(months)s months") % {
            "percent": f"{pile.target_percent.normalize():f}",
            "months": pile.target_months,
        }
    return baht(pile.target) if pile.target is not None else ""
