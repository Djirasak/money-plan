from __future__ import annotations

from http import HTTPStatus
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.urls import reverse

from money_plan.mailer.models import EmailLog
from money_plan.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def queued():
    """The Celery task replaced by a recorder, and on-commit hooks run at once
    (tests are wrapped in a transaction that never commits)."""
    with (
        mock.patch("money_plan.mailer.api.send_email") as task,
        mock.patch(
            "money_plan.mailer.api.transaction.on_commit",
            side_effect=lambda fn: fn(),
        ),
    ):
        yield task


def verify_kwargs(task):
    (call,) = task.delay.call_args_list
    return call.kwargs


def test_changing_email_resets_verification_and_queues_the_mail(client, queued):
    user = UserFactory(email="old@example.com")
    EmailAddress.objects.create(
        user=user,
        email="old@example.com",
        primary=True,
        verified=True,
    )
    client.force_login(user)
    resp = client.post(
        reverse("users:change_email", kwargs={"pk": user.pk}),
        {"email": "new@example.com"},
    )
    assert resp.status_code == HTTPStatus.FOUND
    address = EmailAddress.objects.get(user=user)
    assert (address.email, address.verified, address.primary) == (
        "new@example.com",
        False,
        True,
    )
    kwargs = verify_kwargs(queued)
    assert kwargs["to"] == ["new@example.com"]
    assert kwargs["template"] == "verify_email"
    assert kwargs["sender"] == "account"
    assert "/accounts/confirm-email/" in kwargs["context"]["url"]
    assert EmailLog.objects.get().user == user


def test_the_link_in_the_mail_verifies_the_address(client, queued):
    user = UserFactory(email="me@example.com")
    EmailAddress.objects.create(user=user, email="me@example.com", primary=True)
    client.force_login(user)
    client.post(reverse("users:resend_verification", kwargs={"pk": user.pk}))
    url = verify_kwargs(queued)["context"]["url"]
    path = "/" + url.split("/", 3)[3]
    assert client.get(path).status_code == HTTPStatus.OK  # the confirmation page
    client.post(path)
    assert EmailAddress.objects.get(user=user).verified


def test_account_page_shows_the_state_and_only_offers_resend_when_unverified(client):
    user = UserFactory(email="me@example.com")
    client.force_login(user)
    page = reverse("users:detail", kwargs={"pk": user.pk})
    html = client.get(page).content.decode()
    assert "ยังไม่ได้ยืนยัน" in html
    assert reverse("users:resend_verification", kwargs={"pk": user.pk}) in html
    EmailAddress.objects.create(
        user=user,
        email="me@example.com",
        primary=True,
        verified=True,
    )
    html = client.get(page).content.decode()
    assert "ยืนยันแล้ว" in html
    assert reverse("users:resend_verification", kwargs={"pk": user.pk}) not in html


def test_resend_is_rate_limited(client, queued):
    user = UserFactory(email="me@example.com")
    client.force_login(user)
    url = reverse("users:resend_verification", kwargs={"pk": user.pk})
    client.post(url)
    client.post(url)
    assert queued.delay.call_count == 1


def test_resend_when_already_verified_sends_nothing(client, queued):
    user = UserFactory(email="me@example.com")
    EmailAddress.objects.create(
        user=user,
        email="me@example.com",
        primary=True,
        verified=True,
    )
    client.force_login(user)
    client.post(reverse("users:resend_verification", kwargs={"pk": user.pk}))
    assert not queued.delay.called


def test_cannot_resend_for_someone_else(client):
    other = UserFactory()
    client.force_login(UserFactory())
    resp = client.post(reverse("users:resend_verification", kwargs={"pk": other.pk}))
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_other_allauth_mail_goes_through_the_worker_too(client, queued):
    """Password reset (a mapped notice) is queued, not sent in the request."""
    user = UserFactory(email="me@example.com")
    EmailAddress.objects.create(
        user=user,
        email="me@example.com",
        primary=True,
        verified=True,
    )
    client.post(reverse("account_reset_password"), {"email": "me@example.com"})
    kwargs = verify_kwargs(queued)
    assert kwargs["template"] == "password_reset"
    assert "/accounts/password/reset/key/" in kwargs["context"]["url"]


def test_verification_mail_renders_in_thai_and_english():
    from money_plan.mailer import services

    ctx = {"name": "Som", "url": "https://x.test/confirm?a=1&b=2"}
    th_html, _th_text = services.render("verify_email", ctx, "th")
    en_html, en_text = services.render("verify_email", ctx, "en")
    assert "ยืนยันอีเมล" in th_html
    assert "Confirm email" in en_html
    assert "a=1&b=2" in en_text  # not HTML-escaped in the plain-text part
    assert "Som" in th_html
