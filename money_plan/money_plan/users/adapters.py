from __future__ import annotations

import typing

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.utils.translation import get_language
from django.utils.translation import gettext as _

from money_plan.mailer.api import queue_email

if typing.TYPE_CHECKING:
    from allauth.socialaccount.models import SocialLogin
    from django.http import HttpRequest

    from money_plan.users.models import User


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def send_mail(self, template_prefix: str, email: str, context: dict) -> None:
        """Every allauth mail goes through the mailer, i.e. out of the request, by the worker."""
        name = template_prefix.rsplit("/", 1)[-1]
        user = context.get("user")
        person = (
            (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""
        )
        language = get_language()
        if name in ("email_confirmation", "email_confirmation_signup"):
            queue_email(
                to=email,
                subject=_("Confirm your email"),
                template="verify_email",
                context={"name": person, "url": context["activate_url"]},
                language=language,
                user=user if getattr(user, "pk", None) else None,
                tags=["verify_email"],
                sender="account",
            )
        elif name == "password_reset_key":
            queue_email(
                to=email,
                subject=_("Reset your password"),
                template="password_reset",
                context={"name": person, "url": context["password_reset_url"]},
                language=language,
                user=user if getattr(user, "pk", None) else None,
                tags=["password_reset"],
                sender="account",
            )
        else:
            # any other allauth notice: keep its own wording, still sent by the worker
            message = self.render_mail(
                template_prefix,
                email,
                {"request": None, **context},
            )
            queue_email(
                to=email,
                subject=message.subject,
                template="plain",
                context={"body": message.body},
                language=language,
                tags=[name],
                sender="account",
            )


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def populate_user(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
        data: dict[str, typing.Any],
    ) -> User:
        """
        Populates user information from social provider info.

        See: https://docs.allauth.org/en/latest/socialaccount/advanced.html#creating-and-populating-user-instances
        """
        user = super().populate_user(request, sociallogin, data)
        if not user.name:
            if name := data.get("name"):
                user.name = name
            elif first_name := data.get("first_name"):
                user.name = first_name
                if last_name := data.get("last_name"):
                    user.name += f" {last_name}"
        return user
