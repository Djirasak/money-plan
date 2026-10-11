"""Share a plan: turn piles + plans into a template and back.

A template carries structure and percentages only: pile names, colours, kinds, modes,
how piles overflow into each other, salary-based goals, and plans with their percentage
splits and conditions. It never carries money (salary, balances, caps, target amounts,
condition amounts) nor entries: the person who imports fills those in themselves.

Whatever comes in (a link or an uploaded file) is untrusted, so ``validate_payload``
rebuilds a clean copy from known fields only, with strict types and limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import engine
from .models import Pile
from .models import PlanItem
from .models import PlanPeriod
from .models import color_validator
from .models import month_validator
from .models import validate_pile_name

SCHEMA_VERSION = 1
MAX_PILES = 30
MAX_PLANS = 12
MAX_PILES_PER_USER = 60
MAX_LINKS_PER_USER = 20
MAX_FILE_BYTES = 50_000
MAX_TITLE = 80
MAX_DESCRIPTION = 500
MAX_PLAN_OFFSET = 600  # months between the first and last plan

KEY_RE = re.compile(r"^[a-z0-9_]{1,20}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
KINDS = {Pile.BUDGET, Pile.FUND}
MODES = {Pile.SWEEP, Pile.ROLLOVER}
OPS = {PlanPeriod.GTE, PlanPeriod.LT}
TARGET_TYPES = {"none", "fixed", "salary"}


class TemplateError(ValueError):
    """The template is not usable; the message says why (shown to the user)."""


# ---- building ----------------------------------------------------------------------


def _month_index(month: str) -> int:
    year, mon = map(int, month.split("-"))
    return year * 12 + mon - 1


def _percent(value: Decimal) -> str:
    return f"{value.normalize():f}"


def build_payload(user) -> dict:
    """The user's piles and plans as a shareable template (structure and % only)."""
    piles = list(user.piles.select_related("overflow_to"))
    keys = {pile.pk: f"p{i + 1}" for i, pile in enumerate(piles)}
    out_piles = []
    for pile in piles:
        if pile.has_salary_target:
            target = {
                "type": "salary",
                "percent": _percent(pile.target_percent),
                "months": pile.target_months,
            }
        elif pile.target is not None:
            target = {"type": "fixed"}  # the amount stays private
        else:
            target = {"type": "none"}
        out_piles.append(
            {
                "key": keys[pile.pk],
                "name": pile.name,
                "color": pile.color,
                "kind": pile.kind,
                "mode": pile.mode,
                "has_cap": pile.cap is not None,  # the amount stays private
                "overflow_to": keys.get(pile.overflow_to_id),
                "target": target,
            },
        )

    periods = list(
        user.plan_periods.select_related("cond_pile")
        .prefetch_related("items")
        .order_by("-effective_month", "-id")[:MAX_PLANS],
    )
    periods.reverse()  # oldest first
    first = _month_index(periods[0].effective_month) if periods else 0
    out_plans = []
    for period in periods:
        condition = None
        if period.cond_pile_id in keys and period.cond_op:
            condition = {
                "pile": keys[period.cond_pile_id],
                "op": period.cond_op,
                "use_target": bool(
                    period.cond_use_target and period.cond_pile.has_target,
                ),
            }
        out_plans.append(
            {
                "name": period.name,
                "offset": _month_index(period.effective_month) - first,
                "condition": condition,
                "items": [
                    {"pile": keys[item.pile_id], "percent": _percent(item.percent)}
                    for item in period.items.all()
                    if item.pile_id in keys
                ],
            },
        )
    return {"schema": SCHEMA_VERSION, "piles": out_piles, "plans": out_plans}


# ---- validating --------------------------------------------------------------------


def _text(value, field: str, *, max_len: int, required: bool = False) -> str:
    if not isinstance(value, str):
        msg = _("The template is damaged: %(field)s must be text.") % {"field": field}
        raise TemplateError(msg)
    value = value.strip()
    if CONTROL_RE.search(value) or len(value) > max_len or (required and not value):
        msg = _("The template is damaged: %(field)s is not valid.") % {"field": field}
        raise TemplateError(msg)
    return value


def _decimal(value, field: str, *, low: Decimal, high: Decimal) -> Decimal:
    try:
        number = Decimal(str(value)) if not isinstance(value, bool) else None
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite() or not low <= number <= high:
        msg = _("The template is damaged: %(field)s is out of range.") % {
            "field": field,
        }
        raise TemplateError(msg)
    return number.quantize(Decimal("0.01"))


def _clean_target(raw, name: str) -> dict:
    raw = raw or {"type": "none"}
    if not isinstance(raw, dict) or raw.get("type") not in TARGET_TYPES:
        msg = _("The template is damaged: pile “%(name)s” has an unknown goal.") % {
            "name": name,
        }
        raise TemplateError(msg)
    target = {"type": raw["type"]}
    if target["type"] == "salary":
        target["percent"] = _percent(
            _decimal(
                raw.get("percent"),
                _("goal percentage"),
                low=Decimal("0.01"),
                high=Decimal(9999),
            ),
        )
        months = raw.get("months")
        if (
            not isinstance(months, int)
            or isinstance(months, bool)
            or not 1 <= months <= 120  # noqa: PLR2004
        ):
            raise TemplateError(
                _("The template is damaged: a goal has invalid months."),
            )
        target["months"] = months
    return target


def _clean_pile(raw, seen_keys: set[str], seen_names: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise TemplateError(_("The template is damaged: a pile is not an object."))
    key = raw.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key) or key in seen_keys:
        raise TemplateError(_("The template is damaged: a pile key is not valid."))
    name = _text(raw.get("name"), _("pile name"), max_len=24, required=True)
    try:
        validate_pile_name(name)
        color = raw.get("color")
        if not isinstance(color, str):
            raise ValidationError("color")  # noqa: EM101, TRY301
        color_validator(color)
    except ValidationError as exc:
        msg = _("The template is damaged: pile “%(name)s” is not valid.") % {
            "name": name,
        }
        raise TemplateError(msg) from exc
    if name in seen_names:
        raise TemplateError(_("The template is damaged: two piles share a name."))
    if raw.get("kind") not in KINDS or raw.get("mode") not in MODES:
        msg = _("The template is damaged: pile “%(name)s” has an unknown type.") % {
            "name": name,
        }
        raise TemplateError(msg)
    target = _clean_target(raw.get("target"), name)
    overflow = raw.get("overflow_to")
    if overflow is not None and (not isinstance(overflow, str) or overflow == key):
        raise TemplateError(_("The template is damaged: a pile overflows to itself."))
    seen_keys.add(key)
    seen_names.add(name)
    return {
        "key": key,
        "name": name,
        "color": color,
        "kind": raw["kind"],
        "mode": raw["mode"],
        "has_cap": bool(raw.get("has_cap")),
        "overflow_to": overflow,
        "target": target,
    }


def _clean_plan(raw, piles: dict[str, dict]) -> dict:
    if not isinstance(raw, dict):
        raise TemplateError(_("The template is damaged: a plan is not an object."))
    name = _text(raw.get("name", ""), _("plan name"), max_len=60)
    offset = raw.get("offset", 0)
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= MAX_PLAN_OFFSET
    ):
        raise TemplateError(_("The template is damaged: a plan has an invalid start."))
    condition = raw.get("condition")
    if condition is not None:
        if (
            not isinstance(condition, dict)
            or condition.get("pile") not in piles
            or condition.get("op") not in OPS
        ):
            raise TemplateError(
                _("The template is damaged: a plan condition is not valid."),
            )
        use_target = bool(condition.get("use_target"))
        if use_target and piles[condition["pile"]]["target"]["type"] == "none":
            raise TemplateError(
                _(
                    "The template is damaged: a condition uses a goal that does not exist.",
                ),
            )
        condition = {
            "pile": condition["pile"],
            "op": condition["op"],
            "use_target": use_target,
        }
    items_raw = raw.get("items", [])
    if not isinstance(items_raw, list) or len(items_raw) > len(piles):
        raise TemplateError(_("The template is damaged: a plan has too many rows."))
    items, used = [], set()
    for item in items_raw:
        if (
            not isinstance(item, dict)
            or item.get("pile") not in piles
            or item["pile"] in used
        ):
            raise TemplateError(_("The template is damaged: a plan row is not valid."))
        used.add(item["pile"])
        percent = _decimal(
            item.get("percent"),
            _("plan percentage"),
            low=Decimal(0),
            high=Decimal(100),
        )
        items.append({"pile": item["pile"], "percent": _percent(percent)})
    return {"name": name, "offset": offset, "condition": condition, "items": items}


def _check_no_overflow_cycle(piles: dict[str, dict]) -> None:
    for start in piles:
        seen, key = set(), start
        while key is not None:
            if key in seen:
                raise TemplateError(
                    _("The template is damaged: piles overflow in a circle."),
                )
            seen.add(key)
            key = piles[key]["overflow_to"]


def validate_payload(data) -> dict:
    """A clean copy of ``data`` built from known fields only; raises ``TemplateError``."""
    if not isinstance(data, dict):
        raise TemplateError(_("This is not a Money Plan template."))
    if data.get("schema") != SCHEMA_VERSION:
        raise TemplateError(_("This template was made by a version we cannot read."))
    raw_piles, raw_plans = data.get("piles"), data.get("plans")
    if not isinstance(raw_piles, list) or not isinstance(raw_plans, list):
        raise TemplateError(_("This is not a Money Plan template."))
    if not raw_piles or len(raw_piles) > MAX_PILES or len(raw_plans) > MAX_PLANS:
        raise TemplateError(_("The template has too few or too many piles or plans."))
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    piles = [_clean_pile(raw, seen_keys, seen_names) for raw in raw_piles]
    by_key = {p["key"]: p for p in piles}
    for pile in piles:
        if pile["overflow_to"] is not None and pile["overflow_to"] not in by_key:
            raise TemplateError(
                _(
                    "The template is damaged: a pile overflows to a pile that is missing.",
                ),
            )
    _check_no_overflow_cycle(by_key)
    plans = [_clean_plan(raw, by_key) for raw in raw_plans]
    return {"schema": SCHEMA_VERSION, "piles": piles, "plans": plans}


def validate_meta(title, description) -> tuple[str, str]:
    title = _text(title or "", _("title"), max_len=MAX_TITLE, required=True)
    description = (description or "").strip()
    if len(description) > MAX_DESCRIPTION or re.search(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
        description,
    ):
        raise TemplateError(_("The description is too long."))
    return title, description


# ---- importing ---------------------------------------------------------------------


class ImportForm(forms.Form):
    """Month + the amounts a template leaves out. Fields depend on the template."""

    month = forms.CharField(validators=[month_validator])

    def __init__(self, payload: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = payload
        decimal = {"min_value": 0, "max_digits": 14, "decimal_places": 2}
        widget = forms.NumberInput(
            attrs={"class": "input", "inputmode": "decimal", "step": "0.01"},
        )
        by_key = {p["key"]: p for p in payload["piles"]}
        for pile in payload["piles"]:
            if pile["has_cap"]:
                self.fields[f"cap_{pile['key']}"] = forms.DecimalField(
                    required=False,
                    widget=widget,
                    label=_("Rollover cap for %(pile)s (empty = unlimited)")
                    % {"pile": pile["name"]},
                    **decimal,
                )
            if pile["target"]["type"] == "fixed":
                self.fields[f"target_{pile['key']}"] = forms.DecimalField(
                    widget=widget,
                    label=_("Target amount for %(pile)s (THB)")
                    % {"pile": pile["name"]},
                    **decimal,
                )
        for i, plan in enumerate(payload["plans"]):
            cond = plan["condition"]
            if cond and not cond["use_target"]:
                op = dict(PlanPeriod.OP_CHOICES)[cond["op"]]
                self.fields[f"cond_{i}"] = forms.DecimalField(
                    widget=widget,
                    label=_("Amount for the plan “%(plan)s”: %(pile)s %(op)s (THB)")
                    % {
                        "plan": plan["name"] or _("Plan"),
                        "pile": by_key[cond["pile"]]["name"],
                        "op": op,
                    },
                    **decimal,
                )

    @property
    def amount_fields(self):
        return [self[name] for name in self.fields if name != "month"]


@dataclass
class ImportResult:
    piles: int
    plans: int


def _free_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    n = 2
    while True:
        suffix = f" {n}"
        candidate = f"{name[: 24 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        n += 1


@transaction.atomic
def import_template(user, payload: dict, *, month: str, amounts: dict) -> ImportResult:
    """Add the template's piles and plans to ``user``; nothing existing is touched.

    ``payload`` must come from ``validate_payload`` and ``amounts`` from a valid
    ``ImportForm`` (cleaned_data). New plans start in ``month`` (+ their offset).
    """
    existing = set(user.piles.values_list("name", flat=True))
    if len(existing) + len(payload["piles"]) > MAX_PILES_PER_USER:
        raise TemplateError(_("This would give you too many piles. Delete some first."))
    last = user.piles.aggregate(Max("order"))["order__max"]
    base_order = 0 if last is None else last + 1

    created: dict[str, Pile] = {}
    for i, raw in enumerate(payload["piles"]):
        name = _free_name(raw["name"], existing)
        existing.add(name)
        target = raw["target"]
        created[raw["key"]] = Pile.objects.create(
            user=user,
            name=name,
            color=raw["color"],
            kind=raw["kind"],
            mode=raw["mode"],
            cap=amounts.get(f"cap_{raw['key']}") if raw["has_cap"] else None,
            target=amounts.get(f"target_{raw['key']}")
            if target["type"] == "fixed"
            else None,
            target_percent=Decimal(target["percent"])
            if target["type"] == "salary"
            else None,
            target_months=target["months"] if target["type"] == "salary" else None,
            order=base_order + i,
        )
    for raw in payload["piles"]:
        if raw["overflow_to"]:
            pile = created[raw["key"]]
            pile.overflow_to = created[raw["overflow_to"]]
            pile.save(update_fields=["overflow_to"])

    all_piles = list(user.piles.all())
    for i, raw in enumerate(payload["plans"]):
        cond = raw["condition"]
        fields = {
            "cond_pile": None,
            "cond_op": "",
            "cond_amount": None,
            "cond_use_target": False,
        }
        if cond:
            pile = created[cond["pile"]]
            fields = {
                "cond_pile": pile,
                "cond_op": cond["op"],
                "cond_use_target": cond["use_target"],
                "cond_amount": pile.target
                if cond["use_target"]
                else amounts.get(f"cond_{i}"),
            }
        period = PlanPeriod.objects.create(
            user=user,
            effective_month=engine.add_months(month, raw["offset"]),
            name=raw["name"],
            **fields,
        )
        percents = {
            created[item["pile"]].pk: Decimal(item["percent"]) for item in raw["items"]
        }
        PlanItem.objects.bulk_create(
            PlanItem(
                period=period,
                pile=pile,
                percent=percents.get(pile.pk, Decimal(0)),
            )
            for pile in all_piles
        )
    return ImportResult(piles=len(created), plans=len(payload["plans"]))


# keep a lazy label for templates that want the same wording
AMOUNTS_NOT_SHARED = gettext_lazy(
    "Only names, colours, percentages and rules are shared. Your salary, balances, "
    "amounts and entries are never included.",
)
