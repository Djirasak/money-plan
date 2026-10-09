from decimal import Decimal
from decimal import InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from . import services
from .forms import LogEntryForm
from .forms import PileForm
from .forms import PlanPeriodForm
from .forms import SalaryForm
from .models import LogEntry
from .models import PlanItem
from .models import PlanPeriod
from .models import Pile
from .models import Salary


def _selected_month(request, cfg) -> str:
    month = request.GET.get("m") or request.POST.get("m") or services.current_month()
    months = services.month_range(cfg.start_month)
    return month if month in months else months[0]


NAV = [
    ("summary", _("Summary"), "/", "▦"),
    ("log", _("Log"), "/log/", "✎"),
    ("settings", _("Settings"), "/settings/", "⚙"),
]


def _month_ctx(request, cfg, active: str) -> dict:
    month = _selected_month(request, cfg)
    return {
        "nav": NAV,
        "active": active,
        "month": month,
        "months": services.month_range(cfg.start_month),
    }


def _errors(request, form) -> None:
    for errs in form.errors.values():
        for err in errs:
            messages.error(request, err)


@login_required
def summary(request):
    cfg = services.ensure_defaults(request.user)
    ctx = _month_ctx(request, cfg, "summary")
    rows = services.compute_months(request.user, ctx["month"])
    current = next(r for r in rows if r.month == ctx["month"])
    piles = {p.name: p for p in request.user.piles.select_related("overflow_to")}
    cards = []
    for name, pm in current.piles.items():
        pile = piles[name]
        card = {"pile": pile, "pm": pm}
        if pile.kind == Pile.FUND:
            target = pile.target
            card["progress"] = (
                pm.before / target * 100 if target and target > 0 else Decimal(0)
            )
            card["remaining"] = (target - pm.before) if target else None
            card["incoming"] = pm.allocation + pm.net
        cards.append(card)
    ctx |= {
        "current": current,
        "cards": cards,
        "allocated": sum(pm.allocation for pm in current.piles.values()),
        "plan_name": next(
            (
                p.name
                for p in request.user.plan_periods.all()  # newest first
                if p.effective_month <= ctx["month"]
            ),
            "",
        ),
    }
    return render(request, "planner/summary.html", ctx)


@login_required
def log(request, pk: int | None = None):
    cfg = services.ensure_defaults(request.user)
    ctx = _month_ctx(request, cfg, "log")
    instance = get_object_or_404(LogEntry, pk=pk, user=request.user) if pk else None
    form = LogEntryForm(request.POST or None, instance=instance, user=request.user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, _("Entry saved"))
            return redirect(f"{request.path_info.split('/edit')[0]}?m={ctx['month']}")
        _errors(request, form)
    year, mon = ctx["month"].split("-")
    entries = LogEntry.objects.filter(
        user=request.user,
        date__year=year,
        date__month=int(mon),
    ).select_related("from_pile", "to_pile")
    return render(
        request,
        "planner/log.html",
        ctx | {"form": form, "entries": entries, "editing": instance},
    )


@login_required
@require_POST
def log_delete(request, pk: int):
    entry = get_object_or_404(LogEntry, pk=pk, user=request.user)
    entry.delete()
    messages.success(request, _("Entry deleted"))
    return redirect(f"/log/?m={request.POST.get('m', entry.month)}")


@login_required
def settings_general(request):
    cfg = services.ensure_defaults(request.user)
    ctx = {"nav": NAV, "active": "settings", "sub": "general"}
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "salary_add":
            form = SalaryForm(request.POST, user=request.user)
            if form.is_valid():
                Salary.objects.update_or_create(
                    user=request.user,
                    effective_month=form.cleaned_data["effective_month"],
                    defaults={"amount": form.cleaned_data["amount"]},
                )
                messages.success(request, _("Salary saved"))
            else:
                _errors(request, form)
        elif action == "salary_delete":
            Salary.objects.filter(user=request.user, pk=request.POST.get("id")).delete()
        elif action == "general":
            month = request.POST.get("start_month", "")
            try:
                mult = Decimal(request.POST.get("salary_multiplier", "1"))
                if mult <= 0 or len(month) != 7:
                    raise InvalidOperation  # noqa: TRY301
                cfg.start_month, cfg.salary_multiplier = month, mult
                cfg.full_clean()
                cfg.save()
                messages.success(request, _("Settings saved"))
            except (InvalidOperation, ValueError, Exception):  # noqa: BLE001
                messages.error(request, _("Invalid value"))
        return redirect("planner:settings")
    ctx |= {
        "cfg": cfg,
        "salaries": Salary.objects.filter(user=request.user),
        "salary_months": services.month_range(services.current_month(), 12 * 5),
        "default_month": services.current_month(),
    }
    return render(request, "planner/settings_general.html", ctx)


@login_required
def settings_piles(request):
    services.ensure_defaults(request.user)
    ctx = {"nav": NAV, "active": "settings", "sub": "piles"}
    if request.method == "POST":
        action = request.POST.get("action")
        pile = None
        if request.POST.get("id"):
            pile = get_object_or_404(Pile, pk=request.POST["id"], user=request.user)
        if action == "delete" and pile:
            try:
                pile.delete()
                messages.success(request, _("Pile deleted"))
            except ProtectedError:
                messages.error(request, _("Cannot delete: this pile is used by log entries"))
        else:
            form = PileForm(request.POST, instance=pile, user=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, _("Pile saved"))
            else:
                _errors(request, form)
        return redirect("planner:piles")
    forms_ = [
        (p, PileForm(instance=p, user=request.user, prefix=f"p{p.pk}"))
        for p in request.user.piles.all()
    ]
    new_form = PileForm(user=request.user, prefix="new")
    return render(
        request,
        "planner/settings_piles.html",
        ctx | {"forms": forms_, "new_form": new_form},
    )


def _dec(raw: str | None) -> Decimal:
    try:
        value = Decimal((raw or "0").strip() or "0")
    except InvalidOperation:
        return Decimal(0)
    return max(value, Decimal(0))


@login_required
def settings_plan(request):
    services.ensure_defaults(request.user)
    piles = list(request.user.piles.all())
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            form = PlanPeriodForm(request.POST, user=request.user)
            if form.is_valid():
                month = form.cleaned_data["effective_month"]
                previous = (
                    request.user.plan_periods.filter(effective_month__lt=month)
                    .order_by("-effective_month")
                    .first()
                )
                period = PlanPeriod.objects.create(
                    user=request.user,
                    effective_month=month,
                    name=form.cleaned_data["name"],
                )
                old = (
                    {i.pile_id: i for i in previous.items.all()} if previous else {}
                )
                for pile in piles:
                    src = old.get(pile.pk)
                    PlanItem.objects.create(
                        period=period,
                        pile=pile,
                        percent=src.percent if src else 0,
                        fixed=src.fixed if src else 0,
                    )
                messages.success(request, _("Plan added"))
            else:
                _errors(request, form)
        else:
            period = get_object_or_404(
                PlanPeriod,
                pk=request.POST.get("id"),
                user=request.user,
            )
            if action == "delete":
                period.delete()
                messages.success(request, _("Plan deleted"))
            elif action == "save":
                period.name = request.POST.get("name", "")[:60]
                period.save(update_fields=["name"])
                for pile in piles:
                    PlanItem.objects.update_or_create(
                        period=period,
                        pile=pile,
                        defaults={
                            "percent": _dec(request.POST.get(f"percent_{pile.pk}")),
                            "fixed": _dec(request.POST.get(f"fixed_{pile.pk}")),
                        },
                    )
                messages.success(request, _("Plan saved"))
        return redirect("planner:plan")
    periods = []
    for period in request.user.plan_periods.prefetch_related("items"):
        items = {i.pile_id: i for i in period.items.all()}
        rows = [(p, items.get(p.pk)) for p in piles]
        total = sum((i.percent for i in items.values()), Decimal(0))
        periods.append({"period": period, "rows": rows, "total": total})
    return render(
        request,
        "planner/settings_plan.html",
        {
            "nav": NAV,
            "active": "settings",
            "sub": "plan",
            "periods": periods,
            "default_month": services.current_month(),
        },
    )
