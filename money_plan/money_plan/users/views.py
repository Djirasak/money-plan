from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import RedirectView
from django.views.generic import UpdateView
from django.views.generic import View

from money_plan.users.forms import AccountPasswordChangeForm
from money_plan.users.forms import EmailChangeForm
from money_plan.users.forms import NameChangeForm
from money_plan.users.forms import UsernameChangeForm
from money_plan.users.models import User

if TYPE_CHECKING:
    from django.db.models import QuerySet


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        if self.object != user:
            return ctx
        # a form posted to one of the account endpoints comes back bound, with its dialog open
        bound = kwargs.get("bound") or {}
        return ctx | {
            "username_form": bound.get("username") or UsernameChangeForm(instance=user),
            "email_form": bound.get("email")
            or EmailChangeForm(initial={"email": user.email}, user=user),
            "name_form": bound.get("name") or NameChangeForm(instance=user),
            "password_form": bound.get("password") or AccountPasswordChangeForm(user),
            "open_dialog": kwargs.get("open_dialog", ""),
        }


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet | None = None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        return reverse("users:detail", kwargs={"username": self.request.user.username})


user_redirect_view = UserRedirectView.as_view()


class AccountChangeView(LoginRequiredMixin, View):
    """Base for the account dialogs: valid -> toast + back to the page, invalid -> page with the dialog open."""

    http_method_names = ["post"]
    key = ""
    success_message = ""

    def get_form(self):
        raise NotImplementedError

    def save(self, form) -> None:
        form.save()

    def post(self, request):
        form = self.get_form()
        if form.is_valid():
            self.save(form)
            messages.success(request, self.success_message)
            # reload: a changed username changes this very URL
            return redirect(User.objects.get(pk=request.user.pk).get_absolute_url())
        detail = UserDetailView()
        detail.setup(request, username=request.user.username)
        detail.object = request.user
        ctx = detail.get_context_data(
            bound={self.key: form},
            open_dialog=f"account-{self.key}",
        )
        return detail.render_to_response(ctx)


class UsernameChangeView(AccountChangeView):
    key = "username"
    success_message = _("Username updated")

    def get_form(self):
        # a fresh copy, so a rejected value never leaks into the signed-in user shown on the page
        return UsernameChangeForm(
            self.request.POST,
            instance=User.objects.get(pk=self.request.user.pk),
        )


class EmailChangeView(AccountChangeView):
    key = "email"
    success_message = _("Email updated")

    def get_form(self):
        return EmailChangeForm(self.request.POST, user=self.request.user)


class PasswordChangeView(AccountChangeView):
    key = "password"
    success_message = _("Password changed")

    def get_form(self):
        return AccountPasswordChangeForm(self.request.user, self.request.POST)

    def save(self, form) -> None:
        user = form.save()
        update_session_auth_hash(self.request, user)  # stay signed in


class NameChangeView(AccountChangeView):
    key = "name"
    success_message = _("Name updated")

    def get_form(self):
        return NameChangeForm(
            self.request.POST,
            instance=User.objects.get(pk=self.request.user.pk),
        )
