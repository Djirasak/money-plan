from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from . import services

NAV = [
    ("summary", _("Summary"), "/", "▦"),
    ("log", _("Log"), "/log/", "✎"),
    ("settings", _("Settings"), "/settings/", "⚙"),
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
        return services.month_range(self.cfg.start_month)

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
                "prev_month": self.months[i - 1] if i > 0 else None,
                "next_month": self.months[i + 1] if i < len(self.months) - 1 else None,
            }
        return ctx


class ActionPostMixin:
    """POST dispatches on the ``action`` field to a ``do_<action>`` method."""

    success_url_name = ""

    def post(self, request, *args, **kwargs):
        handler = getattr(self, f"do_{request.POST.get('action', '')}", None)
        if handler:
            handler(request)
        return redirect(self.success_url_name)
