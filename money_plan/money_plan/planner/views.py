from decimal import Decimal
from decimal import InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.http import JsonResponse
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
from .forms import PlanConditionForm
from .forms import PlanPeriodForm
from .forms import SalaryForm
from .mixins import ActionPostMixin
from .mixins import PlannerMixin
from .mixins import month_from_post
from .models import LogEntry
from .models import Pile
from .models import PlanItem
from .models import PlannerSettings
from .models import PlanPeriod
from .models import Salary
from .templatetags.planner_tags import target_label


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
                target = pm.target  # this month's goal (follows the salary if so set)
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
            "plan_name": dict(
                user.plan_periods.values_list("pk", "name"),
            ).get(int(current.plan_key) if current.plan_key else None, ""),
        }
        return ctx


# --- log -------------------------------------------------------------------


class LogView(PlannerMixin, TemplateView):
    """Add an entry, or edit one when ``pk`` is in the URL."""

    template_name = "planner/log.html"
    active = "log"
    show_month = True
    FIRST_PAGE = 25
    NEXT_PAGE = 10

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and "offset" in self.request.GET:
            return ["planner/_log_items.html"]
        return [self.template_name]

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
        try:
            offset = max(int(self.request.GET.get("offset", 0)), 0)
        except ValueError:
            offset = 0
        size = self.FIRST_PAGE if offset == 0 else self.NEXT_PAGE
        page = list(entries[offset : offset + size + 1])
        more = len(page) > size
        return ctx | {
            "form": kwargs.get("form") or self.get_form(),
            "entries": page[:size],
            "next_offset": offset + size if more else None,
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


CLEAR_PHRASE = _("DELETE")  # typed to confirm; translated so a Thai keyboard can do it


class SettingsGeneralView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/settings_general.html"
    active = "settings"
    sub = "general"
    success_url_name = "planner:settings"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        return ctx | {
            "cfg": self.cfg,
            "salary_percent": (self.cfg.salary_multiplier * 100).normalize(),
            "salaries": Salary.objects.filter(user=self.request.user),
            "default_month": services.current_month(),
            "clear_phrase": str(CLEAR_PHRASE),
            "salary_dialogs": self._salary_dialogs(),
        }

    bound_salary: tuple | None = (
        None  # (salary or None, posted data, form) after a failed save
    )

    def _salary_dialogs(self) -> list[dict]:
        """One entry per dialog (each salary, plus "new") with its field values/errors."""
        rows = [*Salary.objects.filter(user=self.request.user), None]
        dialogs = []
        for salary in rows:
            failed = self.bound_salary is not None and self.bound_salary[0] == salary
            if failed:
                _, data, form = self.bound_salary
                month = data.get("effective_month") or services.current_month()
                amount = data.get("amount", "")
                errors = [e for errs in form.errors.values() for e in errs]
            else:
                month = salary.effective_month if salary else services.current_month()
                amount = f"{salary.amount:f}".rstrip("0").rstrip(".") if salary else ""
                errors = []
            dialogs.append(
                {
                    "salary": salary,
                    "month": month,
                    "amount": amount,
                    "errors": errors,
                    "auto_open": failed,
                },
            )
        return dialogs

    def _salary(self, request) -> Salary | None:
        pk = request.POST.get("id")
        return get_object_or_404(Salary, pk=pk, user=request.user) if pk else None

    def do_salary_save(self, request):
        """Add a salary, or change an existing one (``id`` in the POST)."""
        salary = self._salary(request)
        data = request.POST.copy()
        data["effective_month"] = month_from_post(request.POST, "effective_month")
        form = SalaryForm(data, user=request.user, instance=salary)
        if not form.is_valid():
            _errors(request, form)
            self.bound_salary = (salary, data, form)
            return self.render_to_response(self.get_context_data())
        month, amount = (
            form.cleaned_data["effective_month"],
            form.cleaned_data["amount"],
        )
        if salary is None:
            Salary.objects.update_or_create(
                user=request.user,
                effective_month=month,
                defaults={"amount": amount},
            )
        else:
            salary.effective_month, salary.amount = month, amount
            salary.save()
        messages.success(request, _("Salary saved"))
        return None

    def do_salary_delete(self, request):
        Salary.objects.filter(user=request.user, pk=request.POST.get("id")).delete()

    def do_clear_all(self, request):
        """Wipe this user's planner data (the account itself stays), after a typed confirmation."""
        phrase = str(CLEAR_PHRASE)
        if request.POST.get("confirm", "").strip().casefold() != phrase.casefold():
            messages.error(request, _("Type the word to confirm, nothing was deleted"))
            return
        user = request.user
        with transaction.atomic():
            # entries first: they protect the piles they point at
            LogEntry.objects.filter(user=user).delete()
            PlanPeriod.objects.filter(
                user=user,
            ).delete()  # takes its plan items with it
            Pile.objects.filter(user=user).delete()
            Salary.objects.filter(user=user).delete()
            PlannerSettings.objects.filter(user=user).delete()
        messages.success(request, _("All your data was cleared"))
        return

    def do_general(self, request):
        cfg = self.cfg
        try:
            # the form asks for a percentage (100 = whole salary); we store a multiplier
            percent = Decimal(request.POST.get("salary_percent", "100"))
            multiplier = percent / 100
            if not 0 < multiplier <= 1:
                raise InvalidOperation  # noqa: TRY301
            cfg.start_month = month_from_post(request.POST, "start_month")
            cfg.salary_multiplier = multiplier
            cfg.full_clean()
            cfg.save()
        except InvalidOperation, ValidationError:
            messages.error(request, _("Invalid value"))
        else:
            messages.success(request, _("Settings saved"))


class SettingsPilesView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/settings_piles.html"
    active = "settings"
    sub = "piles"
    success_url_name = "planner:piles"

    bound_form: PileForm | None = None  # the form that failed validation, if any
    bound_pile: Pile | None = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        def form_for(pile):
            if self.bound_form is not None and self.bound_pile == pile:
                return self.bound_form
            prefix = f"p{pile.pk}" if pile else "new"
            return PileForm(instance=pile, user=user, prefix=prefix)

        return ctx | {
            "forms": [(p, form_for(p)) for p in user.piles.all()],
            "new_form": form_for(None),
            # re-open the dialog whose form had errors
            "open_dialog": (
                None
                if self.bound_form is None
                else f"pile-edit-{self.bound_pile.pk}"
                if self.bound_pile
                else "pile-new"
            ),
        }

    def _pile(self, request) -> Pile | None:
        pk = request.POST.get("id")
        return get_object_or_404(Pile, pk=pk, user=request.user) if pk else None

    def do_save(self, request):
        pile = self._pile(request)
        # same prefixes as the rendered forms: "p<pk>" for a pile, "new" for the add form
        prefix = f"p{pile.pk}" if pile else "new"
        form = PileForm(request.POST, instance=pile, user=request.user, prefix=prefix)
        if form.is_valid():
            form.save()
            messages.success(request, _("Pile saved"))
            return None
        _errors(request, form)
        self.bound_form, self.bound_pile = form, pile
        return self.render_to_response(self.get_context_data())

    def do_delete(self, request):
        pile = self._pile(request)
        if pile is None:
            return
        try:
            pile.delete()
        except ProtectedError:
            messages.error(
                request,
                _(
                    "Cannot delete: this pile is used by log entries or a plan condition",
                ),
            )
        else:
            messages.success(request, _("Pile deleted"))


class PileReorderView(LoginRequiredMixin, View):
    """Save a new pile order: POST ids=<pk>&ids=<pk>... in the order they should appear."""

    http_method_names = ["post"]

    @transaction.atomic
    def post(self, request):
        wanted = [int(pk) for pk in request.POST.getlist("ids") if pk.isdigit()]
        mine = set(request.user.piles.values_list("pk", flat=True))
        ids = [
            pk for pk in dict.fromkeys(wanted) if pk in mine
        ]  # unique, own piles only
        # the piles that were not listed keep their relative order, after the listed ones
        rest = [
            pk
            for pk in request.user.piles.values_list("pk", flat=True)
            if pk not in ids
        ]
        for position, pk in enumerate([*ids, *rest]):
            Pile.objects.filter(pk=pk, user=request.user).update(order=position)
        return JsonResponse({"order": [*ids, *rest]})


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
        return ctx | {
            "periods": periods,
            "piles": piles,
            "pile_targets": {p.pk: target_label(p) for p in piles if p.has_target},
            # options shared by every condition form on the page
            "mode_options": [
                ("", _("Always, from the start month")),
                ("on", _("Only while a pile's balance matches")),
            ],
            "pile_options": [(p.pk, p.name) for p in piles],
            "op_options": PlanPeriod.OP_CHOICES,
            "default_month": services.current_month(),
        }

    def _period(self, request) -> PlanPeriod:
        return get_object_or_404(
            PlanPeriod,
            pk=request.POST.get("id"),
            user=request.user,
        )

    def do_add(self, request):
        data = request.POST.copy()
        data["effective_month"] = month_from_post(request.POST, "effective_month")
        form = PlanPeriodForm(data)
        condition = PlanConditionForm(request.POST, user=request.user)
        if not (form.is_valid() and condition.is_valid()):
            _errors(request, form)
            _errors(request, condition)
            return
        month = form.cleaned_data["effective_month"]
        # new plans start from a copy of the newest plan that has started by then
        previous = (
            request.user.plan_periods.filter(effective_month__lte=month)
            .order_by("-effective_month", "-id")
            .first()
        )
        period = PlanPeriod.objects.create(
            user=request.user,
            effective_month=month,
            name=form.cleaned_data["name"],
            **condition.cleaned_data,
        )
        old = {i.pile_id: i for i in previous.items.all()} if previous else {}
        for pile in request.user.piles.all():
            src = old.get(pile.pk)
            PlanItem.objects.create(
                period=period,
                pile=pile,
                percent=src.percent if src else 0,
            )
        messages.success(request, _("Plan added"))

    def do_save(self, request):
        period = self._period(request)
        condition = PlanConditionForm(request.POST, user=request.user)
        if not condition.is_valid():
            _errors(request, condition)
            return
        period.name = request.POST.get("name", "")[:60]
        for field, value in condition.cleaned_data.items():
            setattr(period, field, value)
        period.save()
        for pile in request.user.piles.all():
            PlanItem.objects.update_or_create(
                period=period,
                pile=pile,
                defaults={
                    "percent": _dec(request.POST.get(f"percent_{pile.pk}")),
                },
            )
        messages.success(request, _("Plan saved"))

    def do_delete(self, request):
        self._period(request).delete()
        messages.success(request, _("Plan deleted"))
