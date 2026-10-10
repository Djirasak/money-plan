from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from money_plan.users.forms import UserAdminChangeForm
from money_plan.users.tests.factories import UserFactory
from money_plan.users.views import UserRedirectView
from money_plan.users.views import UserUpdateView
from money_plan.users.views import user_detail_view

if TYPE_CHECKING:
    from django.test import RequestFactory

    from money_plan.users.models import User

pytestmark = pytest.mark.django_db


class TestUserUpdateView:
    """
    TODO:
        extracting view initialization code as class-scoped fixture
        would be great if only pytest-django supported non-function-scoped
        fixture db access -- this is a work-in-progress for now:
        https://github.com/pytest-dev/pytest-django/pull/258
    """

    def dummy_get_response(self, request: HttpRequest):
        return None

    def test_get_success_url(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request
        assert view.get_success_url() == f"/users/{user.username}/"

    def test_get_object(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user

    def test_form_valid(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")

        # Add the session/message middleware to the request
        SessionMiddleware(self.dummy_get_response).process_request(request)
        MessageMiddleware(self.dummy_get_response).process_request(request)
        request.user = user

        view.request = request

        # Initialize the form
        form = UserAdminChangeForm()
        form.cleaned_data = {}
        form.instance = user
        view.form_valid(form)

        messages_sent = [m.message for m in messages.get_messages(request)]
        assert messages_sent == [_("Information successfully updated")]


class TestUserRedirectView:
    def test_get_redirect_url(self, user: User, rf: RequestFactory):
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user

        view.request = request
        assert view.get_redirect_url() == f"/users/{user.username}/"


class TestUserDetailView:
    def test_authenticated(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = UserFactory.create()
        response = user_detail_view(request, username=user.username)

        assert response.status_code == HTTPStatus.OK

    def test_not_authenticated(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = AnonymousUser()
        response = user_detail_view(request, username=user.username)
        login_url = reverse(settings.LOGIN_URL)

        assert isinstance(response, HttpResponseRedirect)
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{login_url}?next=/fake-url/"


class TestAccountChanges:
    def test_page_has_edit_dialogs_and_logout(self, client, user: User):
        client.force_login(user)
        html = client.get(user.get_absolute_url()).content.decode()
        for dialog in ("account-username", "account-email", "account-password", "logout-modal"):
            assert f'id="{dialog}"' in html
        assert "disabled" in html  # profile photo button is not available yet

    def test_change_username(self, client, user: User):
        client.force_login(user)
        resp = client.post(reverse("users:change_username"), {"username": "brand_new"})
        assert resp.status_code == HTTPStatus.FOUND
        user.refresh_from_db()
        assert user.username == "brand_new"
        assert resp.url == "/users/brand_new/"

    def test_username_taken_ignoring_case_reopens_dialog(self, client, user: User):
        other = UserFactory(username="Taken_Name")
        client.force_login(user)
        old = user.username
        resp = client.post(reverse("users:change_username"), {"username": other.username.lower()})
        assert resp.status_code == HTTPStatus.OK
        html = resp.content.decode()
        assert "data-auto-open" in html
        assert "ถูกใช้แล้ว" in html or "already been taken" in html
        user.refresh_from_db()
        assert user.username == old

    def test_change_email_syncs_allauth_address(self, client, user: User):
        from allauth.account.models import EmailAddress

        client.force_login(user)
        resp = client.post(reverse("users:change_email"), {"email": "new@example.com"})
        assert resp.status_code == HTTPStatus.FOUND
        user.refresh_from_db()
        assert user.email == "new@example.com"
        addr = EmailAddress.objects.get(user=user)
        assert addr.email == "new@example.com"
        assert addr.primary

    def test_email_taken_is_rejected(self, client, user: User):
        other = UserFactory(email="used@example.com")
        client.force_login(user)
        resp = client.post(reverse("users:change_email"), {"email": "USED@example.com"})
        assert resp.status_code == HTTPStatus.OK
        assert "data-auto-open" in resp.content.decode()
        user.refresh_from_db()
        assert user.email != other.email

    def test_change_password_keeps_session(self, client, user: User):
        user.set_password("old-pass-123!")
        user.save()
        client.force_login(user)
        resp = client.post(
            reverse("users:change_password"),
            {"old_password": "old-pass-123!", "new_password1": "Brand-new-pass-77", "new_password2": "Brand-new-pass-77"},
        )
        assert resp.status_code == HTTPStatus.FOUND
        user.refresh_from_db()
        assert user.check_password("Brand-new-pass-77")
        assert client.get(user.get_absolute_url()).status_code == HTTPStatus.OK  # still signed in

    def test_wrong_current_password_rejected(self, client, user: User):
        user.set_password("old-pass-123!")
        user.save()
        client.force_login(user)
        resp = client.post(
            reverse("users:change_password"),
            {"old_password": "nope", "new_password1": "Brand-new-pass-77", "new_password2": "Brand-new-pass-77"},
        )
        assert resp.status_code == HTTPStatus.OK
        user.refresh_from_db()
        assert user.check_password("old-pass-123!")

    def test_anonymous_cannot_change(self, client):
        resp = client.post(reverse("users:change_email"), {"email": "x@example.com"})
        assert resp.status_code == HTTPStatus.FOUND
        assert "login" in resp.url

    def test_change_name_stores_first_and_last(self, client, user: User):
        client.force_login(user)
        resp = client.post(reverse("users:change_name"), {"first_name": " สมชาย ", "last_name": "ใจดี"})
        assert resp.status_code == HTTPStatus.FOUND
        user.refresh_from_db()
        assert (user.first_name, user.last_name, user.name) == ("สมชาย", "ใจดี", "สมชาย ใจดี")
        html = client.get(user.get_absolute_url()).content.decode()
        assert 'id="account-name"' in html
