"""Module for all Form Tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.utils.translation import gettext_lazy as _

from money_plan.users.forms import UserAdminCreationForm

if TYPE_CHECKING:
    from money_plan.users.models import User


class TestUserAdminCreationForm:
    """
    Test class for all tests related to the UserAdminCreationForm
    """

    def test_username_validation_error_msg(self, user: User):
        """
        Tests UserAdminCreation Form's unique validator functions correctly by testing:
            1) A new user with an existing username cannot be added.
            2) Only 1 error is raised by the UserCreation Form
            3) The desired error message is raised
        """

        # The user already exists,
        # hence cannot be created.
        form = UserAdminCreationForm(
            {
                "username": user.username,
                "password1": user.password,
                "password2": user.password,
            },
        )

        assert not form.is_valid()
        assert len(form.errors) == 1
        assert "username" in form.errors
        assert form.errors["username"][0] == _("This username has already been taken.")


def test_only_a_minimum_length_is_enforced(settings):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    assert len(settings.AUTH_PASSWORD_VALIDATORS) == 1
    validate_password("12345678")  # all digits, and very common: fine, by design
    with pytest.raises(ValidationError):
        validate_password("1234567")


def test_the_rule_is_shown_in_thai():
    from django.contrib.auth.password_validation import password_validators_help_texts
    from django.utils import translation

    with translation.override("th"):
        (text,) = password_validators_help_texts()
    assert "8" in text
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in text)


@pytest.mark.django_db
def test_checklist_is_on_the_change_password_dialog(client):
    from django.urls import reverse

    from money_plan.users.tests.factories import UserFactory

    user = UserFactory()
    client.force_login(user)
    html = client.get(reverse("users:detail", kwargs={"pk": user.pk})).content.decode()
    assert html.count("data-password-rules") == 1
    assert 'data-rule="length" data-min="8"' in html


@pytest.mark.django_db
def test_reset_page_shows_the_checklist(client):
    from allauth.account.forms import default_token_generator
    from allauth.account.utils import user_pk_to_url_str
    from django.urls import reverse

    from money_plan.users.tests.factories import UserFactory

    user = UserFactory()
    url = reverse(
        "account_reset_password_from_key",
        kwargs={
            "uidb36": user_pk_to_url_str(user),
            "key": default_token_generator.make_token(user),
        },
    )
    html = client.get(url, follow=True).content.decode()
    assert "data-password-rules" in html
