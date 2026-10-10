from decimal import Decimal
from decimal import InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView

from . import services
from .forms import LogEntryForm
from .forms import PileForm
from .forms import PlanPeriodForm
from .forms import SalaryForm
from .mixins import ActionPostMixin
from .mixins import PlannerMixin
from .models import LogEntry
from .models import PlanItem
from .models import PlanPeriod
from .models import Pile
from .models import Salary

def _errors(request, form) -> None:
    for errs in form.errors.values():
        for err in errs:
            messages.error(request, err)


def _dec(raw: str | None) -> Decimal:
    try:
        value = Decimal((raw or "0").strip() or "0")
    except InvalidOperation:
        return Decimal(0)
    return max(value, Decimal(0))


# --- summary ---------------------------------------------------------------


class SummaryView(PlannerMixin, TemplateView):
    """Page shell; the (slow) calculation is lazy-loaded by htmx."""

    template_name = "planner/summary.html"
    active = "summary"
    show_month = True


class SummaryContentView(PlannerMixin, TemplateView):
    """Hero + pile cards. Runs the engine, so it is fetched with htmx."""

    template_name = "planner/_summary_content.html"
    active = "summary"
    show_month = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        rows = services.compute_months(user, self.month)
        current = next(r for r in rows if r.month == self.month)
        piles = {p.name: p for p in user.piles.select_related("overflow_to")}
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
                    for p in user.plan_periods.all()  # newest first
                    if p.effective_month <= self.month
                ),
                "",
            ),
        }
        return ctx


# --- log -------------------------------------------------------------------


class LogView(PlannerMixin, TemplateView):
    """Add an entry, or edit one when ``pk`` is in the URL."""

    template_name = "planner/log.html"
    active = "log"
    show_month = True

    @cached_property
    def entry(self) -> LogEntry | None:
        pk = self.kwargs.get("pk")
        if pk is None:
            return None
        return get_object_or_404(LogEntry, pk=pk, user=self.request.user)

    def get_form(self, data=None) -> LogEntryForm:
        return LogEntryForm(data, instance=self.entry, user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        year, mon = self.month.split("-")
        entries = LogEntry.objects.filter(
            user=self.request.user,
            date__year=year,
            date__month=int(mon),
        ).select_related("from_pile", "to_pile")
        return ctx | {
            "form": kwargs.get("form") or self.get_form(),
            "entries": entries,
            "editing": self.entry,
        }

    def post(self, request, *args, **kwargs):
        form = self.get_form(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Entry saved"))
            return redirect(f"{reverse('planner:log')}?m={self.month}")
        _errors(request, form)
        return self.render_to_response(self.get_context_data(form=form))


class LogDeleteView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk: int):
        entry = get_object_or_404(LogEntry, pk=pk, user=request.user)
        month = request.POST.get("m", entry.month)
        entry.delete()
        messages.success(request, _("Entry deleted"))
        return redirect(f"{reverse('planner:log')}?m={month}")


# --- settings --------------------------------------------------------------


class SettingsGeneralView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/settings_general.html"
    active = "settings"
    sub = "general"
    success_url_name = "planner:settings"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        return ctx | {
            "cfg": self.cfg,
            "salaries": Salary.objects.filter(user=self.request.user),
            "salary_months": services.month_range(services.current_month(), 12 * 5),
            "default_month": services.current_month(),
        }

    def do_salary_add(self, request):
        form = SalaryForm(request.POST, user=request.user)
        if not form.is_valid():
            _errors(request, form)
            return
        Salary.objects.update_or_create(
            user=request.user,
            effective_month=form.cleaned_data["effective_month"],
            defaults={"amount": form.cleaned_data["amount"]},
        )
        messages.success(request, _("Salary saved"))

    def do_salary_delete(self, request):
        Salary.objects.filter(user=request.user, pk=request.POST.get("id")).delete()

    def do_general(self, request):
        cfg = self.cfg
        try:
            multiplier = Decimal(request.POST.get("salary_multiplier", "1"))
            if multiplier <= 0:
                raise InvalidOperation  # noqa: TRY301
            cfg.start_month = request.POST.get("start_month", "")
            cfg.salary_multiplier = multiplier
            cfg.full_clean()
            cfg.save()
        except (InvalidOperation, ValidationError):
            messages.error(request, _("Invalid value"))
        else:
            messages.success(request, _("Settings saved"))


class SettingsPilesView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/settings_piles.html"
    active = "settings"
    sub = "piles"
    success_url_name = "planner:piles"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        return ctx | {
            "forms": [
                (p, PileForm(instance=p, user=user, prefix=f"p{p.pk}"))
                for p in user.piles.all()
            ],
            "new_form": PileForm(user=user, prefix="new"),
        }

    def _pile(self, request) -> Pile | None:
        pk = request.POST.get("id")
        return get_object_or_404(Pile, pk=pk, user=request.user) if pk else None

    def do_save(self, request):
        form = PileForm(request.POST, instance=self._pile(request), user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Pile saved"))
        else:
            _errors(request, form)

    def do_delete(self, request):
        pile = self._pile(request)
        if pile is None:
            return
        try:
            pile.delete()
        except ProtectedError:
            messages.error(request, _("Cannot delete: this pile is used by log entries"))
        else:
            messages.success(request, _("Pile deleted"))


class SettingsPlanView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/settings_plan.html"
    active = "settings"
    sub = "plan"
    success_url_name = "planner:plan"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        piles = list(self.request.user.piles.all())
        periods = []
        for period in self.request.user.plan_periods.prefetch_related("items"):
            items = {i.pile_id: i for i in period.items.all()}
            periods.append(
                {
                    "period": period,
                    "rows": [(p, items.get(p.pk)) for p in piles],
                    "total": sum((i.percent for i in items.values()), Decimal(0)),
                },
            )
        return ctx | {"periods": periods, "default_month": services.current_month()}

    def _period(self, request) -> PlanPeriod:
        return get_object_or_404(PlanPeriod, pk=request.POST.get("id"), user=request.user)

    def do_add(self, request):
        form = PlanPeriodForm(request.POST, user=request.user)
        if not form.is_valid():
            _errors(request, form)
            return
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
        old = {i.pile_id: i for i in previous.items.all()} if previous else {}
        for pile in request.user.piles.all():
            src = old.get(pile.pk)
            PlanItem.objects.create(
                period=period,
                pile=pile,
                percent=src.percent if src else 0,
                fixed=src.fixed if src else 0,
            )
        messages.success(request, _("Plan added"))

    def do_save(self, request):
        period = self._period(request)
        period.name = request.POST.get("name", "")[:60]
        period.save(update_fields=["name"])
        for pile in request.user.piles.all():
            PlanItem.objects.update_or_create(
                period=period,
                pile=pile,
                defaults={
                    "percent": _dec(request.POST.get(f"percent_{pile.pk}")),
                    "fixed": _dec(request.POST.get(f"fixed_{pile.pk}")),
                },
            )
        messages.success(request, _("Plan saved"))

    def do_delete(self, request):
        self._period(request).delete()
        messages.success(request, _("Plan deleted"))
