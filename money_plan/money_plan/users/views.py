from __future__ import annotations

from allauth.account.internal.flows.email_verification import (
    send_verification_email_to_address,
)
from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse
from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import View

from money_plan.users.forms import AccountPasswordChangeForm
from money_plan.users.forms import EmailChangeForm
from money_plan.users.forms import NameChangeForm
from money_plan.users.forms import PhotoChangeForm
from money_plan.users.forms import UsernameChangeForm
from money_plan.users.models import User


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User

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
            "email_verified": EmailAddress.objects.filter(
                user=user,
                email__iexact=user.email,
                verified=True,
            ).exists(),
            "photo_form": bound.get("photo") or PhotoChangeForm(user=user),
            "password_form": bound.get("password") or AccountPasswordChangeForm(user),
            "open_dialog": kwargs.get("open_dialog", ""),
        }


user_detail_view = UserDetailView.as_view()


class SelfOnlyMixin(LoginRequiredMixin):
    """The pk in the URL must be the signed-in user's own: anyone else gets a 404."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and kwargs.get("pk") != request.user.pk:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class AccountChangeView(SelfOnlyMixin, View):
    """Base for the account dialogs: valid -> toast + back to the page, invalid -> page with the dialog open."""

    http_method_names = ["post"]
    key = ""
    success_message = ""

    def get_form(self):
        raise NotImplementedError

    def save(self, form) -> None:
        form.save()

    def post(self, request, pk):
        form = self.get_form()
        if form.is_valid():
            self.save(form)
            messages.success(request, self.success_message)
            return redirect(request.user.get_absolute_url())
        detail = UserDetailView()
        detail.setup(request, pk=request.user.pk)
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

    def save(self, form) -> None:
        user = form.save()
        address = EmailAddress.objects.get(user=user, email=user.email)
        send_verification_email_to_address(self.request, address)


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


class PhotoChangeView(AccountChangeView):
    key = "photo"
    success_message = _("Profile photo updated")

    def get_form(self):
        return PhotoChangeForm(
            self.request.POST,
            self.request.FILES,
            user=User.objects.get(pk=self.request.user.pk),
        )


class PhotoRemoveView(SelfOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        user = request.user
        if user.photo:
            user.photo.delete(save=True)
            messages.success(request, _("Profile photo removed"))
        return redirect(user.get_absolute_url())


class PhotoView(SelfOnlyMixin, View):
    """Stream the signed-in user's photo from the object store."""

    http_method_names = ["get"]

    def get(self, request, pk):
        photo = request.user.photo
        if not photo:
            raise Http404
        response = FileResponse(photo.open("rb"))
        response["Cache-Control"] = "private, max-age=86400"
        return response


class ResendVerificationView(SelfOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        user = request.user
        if not user.email:
            return redirect(user.get_absolute_url())
        address, _created = EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={"primary": True},
        )
        if address.verified:
            messages.info(request, _("Your email is already verified."))
        elif send_verification_email_to_address(request, address):
            messages.success(request, _("Verification email sent. Check your inbox."))
        else:  # allauth's rate limit
            messages.warning(
                request,
                _("Please wait a few minutes before asking again."),
            )
        return redirect(user.get_absolute_url())
