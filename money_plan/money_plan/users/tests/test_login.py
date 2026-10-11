from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.urls import reverse

from money_plan.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-1"


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def member():
    user = UserFactory(username="somchai", email="Somchai@Example.com")
    user.set_password(PASSWORD)
    user.save()
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=True,
    )
    return user


def log_in(client, login, password=PASSWORD):
    return client.post(reverse("account_login"), {"login": login, "password": password})


def test_you_log_in_with_your_email(client, member):
    resp = log_in(client, "somchai@example.com")  # typed in lower case
    assert resp.status_code == 302
    assert client.session["_auth_user_id"] == str(member.pk)


def test_the_username_no_longer_works_as_a_login(client, member):
    resp = log_in(client, "somchai")
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session


def test_a_wrong_password_is_refused(client, member):
    resp = log_in(client, member.email, "nope-nope-nope")
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session


def test_the_login_page_asks_for_an_email(client):
    html = client.get(reverse("account_login")).content.decode()
    assert 'name="login"' in html
    assert 'type="email"' in html
    assert 'autocomplete="email"' in html


def test_an_account_whose_email_is_only_on_the_user_row_can_still_log_in(client):
    """e.g. the first user made by initial_user_data: no allauth address row yet."""
    user = UserFactory(username="first", email="first@example.com")
    user.set_password(PASSWORD)
    user.save()
    assert not EmailAddress.objects.filter(user=user).exists()
    assert log_in(client, "first@example.com").status_code == 302


def test_emails_are_stored_in_lower_case_so_a_login_in_any_case_works(client):
    user = UserFactory(email="MiXed@Example.COM")
    user.set_password(PASSWORD)
    user.save()
    user.refresh_from_db()
    assert user.email == "mixed@example.com"
    assert log_in(client, "MIXED@example.com").status_code == 302


def test_changing_the_email_in_account_keeps_it_lower_case(client, member):
    from django.urls import reverse as r

    client.force_login(member)
    client.post(
        r("users:change_email", kwargs={"pk": member.pk}),
        {"email": "New.Name@Example.com"},
    )
    member.refresh_from_db()
    assert member.email == "new.name@example.com"
    assert EmailAddress.objects.get(user=member).email == "new.name@example.com"


def test_signup_asks_for_no_username_and_still_creates_the_account(client):
    page = client.get(reverse("account_signup")).content.decode()
    assert 'name="username"' not in page
    resp = client.post(
        reverse("account_signup"),
        {"email": "Newbie@Example.com", "password1": PASSWORD, "password2": PASSWORD},
    )
    assert resp.status_code == 302
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email="newbie@example.com")
    assert user.username  # generated behind the scenes: the column is still required


def test_the_account_page_has_no_username(client, member):
    client.force_login(member)
    html = client.get(member.get_absolute_url()).content.decode()
    assert "account-username" not in html
    assert "ชื่อผู้ใช้" not in html


def test_the_avatar_letter_comes_from_the_name_then_the_email():
    from money_plan.planner.templatetags.planner_tags import initial

    assert initial(UserFactory.build(name="สมชาย ใจดี", email="a@b.c")) == "ส"
    assert initial(UserFactory.build(name="", first_name="", email="zed@b.c")) == "Z"


def test_the_lowercase_migration_fixes_old_rows_and_skips_collisions(db):
    import importlib

    from allauth.account.models import EmailAddress as Address
    from django.apps import apps
    from django.contrib.auth import get_user_model

    migration = importlib.import_module(
        "money_plan.users.migrations.0004_lowercase_emails",
    )
    users = get_user_model()
    one = UserFactory()
    users.objects.filter(pk=one.pk).update(
        email="Old.Mixed@Example.com",
    )  # bypass save()
    clash_a = UserFactory(email="clash@example.com")
    clash_b = UserFactory()
    users.objects.filter(pk=clash_b.pk).update(email="CLASH@example.com")
    Address.objects.create(user=one, email="Old.Mixed@Example.com", primary=True)
    migration.lowercase_emails(apps, None)
    one.refresh_from_db()
    clash_b.refresh_from_db()
    assert one.email == "old.mixed@example.com"
    assert Address.objects.get(user=one).email == "old.mixed@example.com"
    assert clash_b.email == "CLASH@example.com"  # would have collided: left as it was
    assert clash_a.email == "clash@example.com"


class TestThaiFirst:
    def test_a_browser_set_to_english_still_gets_thai(self, client):
        html = client.get(
            reverse("account_login"),
            headers={"accept-language": "en-US,en;q=0.9"},
        ).content.decode()
        assert '<html lang="th">' in html

    def test_the_language_button_switches_and_remembers_it(self, client):
        page = client.get(reverse("account_login")).content.decode()
        assert 'name="language" value="en"' in page  # offers the other language, small
        resp = client.post(
            reverse("set_language"),
            {"language": "en", "next": reverse("account_login")},
        )
        assert resp.status_code == 302
        english = client.get(
            reverse("account_login"),
            headers={"accept-language": "th"},
        ).content.decode()
        assert '<html lang="en">' in english
        assert 'name="language" value="th"' in english  # and offers Thai back

    def test_a_cookie_with_an_unknown_language_falls_back_to_thai(self, client):
        client.cookies["django_language"] = "xx"
        assert (
            '<html lang="th">' in client.get(reverse("account_login")).content.decode()
        )

    def test_the_shared_link_page_has_the_switch_too(self, client):
        from money_plan.planner.models import SharedTemplate

        owner = UserFactory()
        share = SharedTemplate.objects.create(
            owner=owner,
            title="T",
            payload={
                "schema": 1,
                "piles": [
                    {
                        "key": "p1",
                        "name": "A",
                        "color": "#112233",
                        "kind": "budget",
                        "mode": "rollover",
                        "icon": "",
                        "has_cap": False,
                        "overflow_to": None,
                        "target": {"type": "none"},
                    },
                ],
                "plans": [],
            },
        )
        html = client.get(
            reverse("planner:template", kwargs={"token": share.token}),
        ).content.decode()
        assert 'name="language" value="en"' in html
        assert "แผนที่แชร์" in html  # Thai by default
