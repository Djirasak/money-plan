from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from . import services
from .templatetags.planner_tags import month_label

NAV = [
    ("summary", _("Summary"), "/", "layout-dashboard"),
    ("log", _("Log"), "/log/", "square-pen"),
    ("settings", _("Settings"), "/settings/", "settings"),
]


class PlannerMixin(LoginRequiredMixin):
    """Login + the context every planner page needs (nav, optional month bar)."""

    active = ""
    sub = ""
    show_month = False

    @cached_property
    def cfg(self):
        return services.ensure_defaults(self.request.user)

    @cached_property
    def months(self) -> list[str]:
        return services.month_window(self.cfg.start_month)

    @cached_property
    def month(self) -> str:
        wanted = (
            self.request.GET.get("m")
            or self.request.POST.get("m")
            or services.current_month()
        )
        return wanted if wanted in self.months else self.months[0]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx |= {"nav": NAV, "active": self.active, "sub": self.sub}
        if self.show_month:
            i = self.months.index(self.month)
            ctx |= {
                "month": self.month,
                "months": self.months,
                "month_options": [(m, month_label(m)) for m in self.months],
                "prev_month": self.months[i - 1] if i > 0 else None,
                "next_month": self.months[i + 1] if i < len(self.months) - 1 else None,
            }
        return ctx


def month_from_post(data, name: str) -> str:
    """'YYYY-MM' from ``name`` or, for the month picker, ``name_year`` + ``name_month``."""
    if data.get(name):
        return data[name]
    year, month = data.get(f"{name}_year", ""), data.get(f"{name}_month", "")
    if year.isdigit() and month.isdigit():
        return f"{int(year):04d}-{int(month):02d}"
    return ""


class ActionPostMixin:
    """POST dispatches on the ``action`` field to a ``do_<action>`` method."""

    success_url_name = ""

    def post(self, request, *args, **kwargs):
        handler = getattr(self, f"do_{request.POST.get('action', '')}", None)
        if handler:
            response = handler(request)
            if response is not None:  # e.g. re-render a form that has errors
                return response
        return redirect(self.success_url_name)
