from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import resolve
from django.urls import reverse

if TYPE_CHECKING:
    from money_plan.users.models import User


def test_detail(user: User):
    assert reverse("users:detail", kwargs={"pk": user.pk}) == f"/users/{user.pk}/"
    assert resolve(f"/users/{user.pk}/").view_name == "users:detail"


def test_update():
    assert reverse("users:update") == "/users/me/update/"
    assert resolve("/users/me/update/").view_name == "users:update"


def test_redirect():
    assert reverse("users:redirect") == "/users/me/"
    assert resolve("/users/me/").view_name == "users:redirect"
