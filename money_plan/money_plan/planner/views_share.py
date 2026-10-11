"""Share a plan by link, export it as a file, and import a shared plan."""

from __future__ import annotations

import json
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView

from . import services
from . import sharing
from .mixins import ActionPostMixin
from .mixins import PlannerMixin
from .mixins import month_from_post
from .models import SharedTemplate
from .templatetags.planner_tags import target_label

SESSION_KEY = "template_import"


class SettingsShareView(ActionPostMixin, PlannerMixin, TemplateView):
    template_name = "planner/share.html"
    active = "settings"
    success_url_name = "planner:share"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        links = [
            {
                "obj": link,
                "url": self.request.build_absolute_uri(
                    reverse("planner:template", kwargs={"token": link.token}),
                ),
            }
            for link in self.request.user.shared_templates.all()
        ]
        return ctx | {
            "links": links,
            "pile_count": self.request.user.piles.count(),
            "plan_count": min(
                self.request.user.plan_periods.count(),
                sharing.MAX_PLANS,
            ),
            "max_title": sharing.MAX_TITLE,
            "max_description": sharing.MAX_DESCRIPTION,
            "max_links": sharing.MAX_LINKS_PER_USER,
            "not_shared_note": sharing.AMOUNTS_NOT_SHARED,
        }

    def do_create(self, request):
        user = request.user
        if user.shared_templates.count() >= sharing.MAX_LINKS_PER_USER:
            messages.error(request, _("You have too many links. Delete one first."))
            return
        try:
            title, description = sharing.validate_meta(
                request.POST.get("title"),
                request.POST.get("description"),
            )
            payload = sharing.validate_payload(sharing.build_payload(user))
        except sharing.TemplateError as exc:
            messages.error(request, str(exc))
            return
        if not payload["plans"]:
            messages.error(
                request,
                _("Add a plan first: a template without a plan is not useful."),
            )
            return
        SharedTemplate.objects.create(
            owner=user,
            title=title,
            description=description,
            payload=payload,
            schema_version=sharing.SCHEMA_VERSION,
        )
        messages.success(
            request,
            _("Link created. Anyone signed in who has it can add your plan."),
        )

    def do_delete(self, request):
        deleted, _unused = request.user.shared_templates.filter(
            pk=request.POST.get("id"),
        ).delete()
        if deleted:
            messages.success(request, _("The link no longer works"))

    def do_upload(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, _("Choose a template file first"))
            return None
        if upload.size > sharing.MAX_FILE_BYTES:
            messages.error(request, _("The file is too big to be a template"))
            return None
        try:
            payload = sharing.validate_payload(
                json.loads(upload.read().decode("utf-8")),
            )
        except UnicodeDecodeError, json.JSONDecodeError:
            messages.error(request, _("This is not a Money Plan template."))
            return None
        except sharing.TemplateError as exc:
            messages.error(request, str(exc))
            return None
        request.session[SESSION_KEY] = payload
        return redirect("planner:import_file")


class ExportView(PlannerMixin, View):
    """Download the signed-in user's piles and plans as a template file."""

    def get(self, request):
        payload = sharing.build_payload(request.user)
        response = HttpResponse(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="money-plan-template.json"'
        )
        return response


class TemplateImportView(PlannerMixin, TemplateView):
    """Preview a shared template (from a link or an uploaded file) and add it to the account."""

    template_name = "planner/template_preview.html"
    active = "settings"

    def dispatch(self, request, *args, **kwargs):
        self.share = None
        if "token" in kwargs:
            if request.user.is_authenticated:
                self.share = get_object_or_404(SharedTemplate, token=kwargs["token"])
        return super().dispatch(request, *args, **kwargs)

    @property
    def payload(self) -> dict | None:
        if self.share:
            try:
                return sharing.validate_payload(self.share.payload)
            except sharing.TemplateError:
                return None
        return self.request.session.get(SESSION_KEY)

    def get(self, request, *args, **kwargs):
        if self.payload is None:
            messages.error(
                request,
                _("There is no template to show. Open a link or choose a file."),
            )
            return redirect("planner:share")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, form=None, **kwargs):
        ctx = super().get_context_data(**kwargs)
        payload = self.payload
        by_key = {p["key"]: p for p in payload["piles"]}
        piles = [
            {
                **pile,
                "goal": self._goal(pile),
                "overflow_name": by_key[pile["overflow_to"]]["name"]
                if pile["overflow_to"]
                else "",
            }
            for pile in payload["piles"]
        ]
        plans = []
        for plan in payload["plans"]:
            cond = plan["condition"]
            plans.append(
                {
                    **plan,
                    "rows": [
                        {"pile": by_key[item["pile"]], "percent": item["percent"]}
                        for item in plan["items"]
                    ],
                    "cond_pile": by_key[cond["pile"]]["name"] if cond else "",
                    "cond_op": dict(sharing.PlanPeriod.OP_CHOICES)[cond["op"]]
                    if cond
                    else "",
                    "cond_target": bool(cond and cond["use_target"]),
                },
            )
        form = form or sharing.ImportForm(
            payload,
            initial={"month": services.current_month()},
        )
        return ctx | {
            "share": self.share,
            "piles": piles,
            "plans": plans,
            "form": form,
            "default_month": services.current_month(),
            "not_shared_note": sharing.AMOUNTS_NOT_SHARED,
        }

    @staticmethod
    def _goal(pile: dict) -> str:
        target = pile["target"]
        if target["type"] == "salary":
            return target_label(_FakePile(target))
        return ""

    def post(self, request, *args, **kwargs):
        payload = self.payload
        if payload is None:
            return redirect("planner:share")
        data = request.POST.copy()
        data["month"] = month_from_post(request.POST, "month")
        form = sharing.ImportForm(payload, data)
        try:
            month_ok = form.is_valid()
        except ValidationError:
            month_ok = False
        if not month_ok:
            ctx = self.get_context_data(form=form, **kwargs)
            return self.render_to_response(ctx)
        try:
            result = sharing.import_template(
                request.user,
                payload,
                month=form.cleaned_data["month"],
                amounts=form.cleaned_data,
            )
        except sharing.TemplateError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data(form=form, **kwargs))
        request.session.pop(SESSION_KEY, None)
        messages.success(
            request,
            _("Added %(piles)s piles and %(plans)s plans to your account.")
            % {"piles": result.piles, "plans": result.plans},
        )
        return redirect("planner:plan")


class _FakePile:
    """Just enough of a Pile for ``target_label`` when previewing a salary goal."""

    def __init__(self, target: dict):
        self.target_percent = Decimal(target["percent"])
        self.target_months = target["months"]
        self.has_salary_target = True
