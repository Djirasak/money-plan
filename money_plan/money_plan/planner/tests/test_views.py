from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from money_plan.planner import services
from money_plan.planner.models import LogEntry
from money_plan.planner.models import Pile
from money_plan.planner.models import PlanPeriod
from money_plan.planner.models import Salary

pytestmark = pytest.mark.django_db


def test_anonymous_redirected_to_login(client):
    resp = client.get(reverse("planner:summary"))
    assert resp.status_code == 302
    assert "login" in resp.url


def test_summary_shows_seeded_piles(client_in):
    resp = client_in.get(reverse("planner:summary"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "฿48,000" in html
    assert "฿26,400" in html  # 55% of salary
    assert "ค่าใช้จ่าย" in html
    assert "เงินสำรอง" in html


def test_add_log_entry_and_it_reduces_balance(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    month = user.planner_settings.start_month
    resp = client_in.post(
        reverse("planner:log"),
        {
            "date": f"{month}-05",
            "type": "spend",
            "from_pile": spend.pk,
            "amount": "1000",
            "note": "ข้าว",
            "m": month,
        },
    )
    assert resp.status_code == 302
    assert LogEntry.objects.filter(user=user, amount=1000).exists()
    html = client_in.get(reverse("planner:summary"), {"m": month}).content.decode()
    assert "฿25,400" in html


def test_log_validation_rejects_spend_without_pile(client_in, user):
    resp = client_in.post(
        reverse("planner:log"),
        {"date": "2027-01-05", "type": "spend", "amount": "10"},
    )
    assert resp.status_code == 200
    assert not LogEntry.objects.filter(user=user).exists()


def test_cannot_touch_other_users_entries(client_in, django_user_model):
    other = django_user_model.objects.create_user("other", password="x")  # noqa: S106
    pile = Pile.objects.create(user=other, name="x")
    entry = LogEntry.objects.create(
        user=other, date=date(2027, 1, 1), type="spend", from_pile=pile, amount=5,
    )
    assert client_in.post(reverse("planner:log_delete", args=[entry.pk])).status_code == 404
    assert LogEntry.objects.filter(pk=entry.pk).exists()


def test_add_pile_and_plan_period_copies_previous(client_in, user):
    client_in.post(
        reverse("planner:piles"),
        {"action": "save", "name": "ท่องเที่ยว", "color": "#ff0000", "kind": "fund",
         "mode": "rollover", "order": 9},
    )
    assert Pile.objects.filter(user=user, name="ท่องเที่ยว").exists()
    client_in.post(
        reverse("planner:plan"),
        {"action": "add", "effective_month": "2027-06", "name": "แผนใหม่"},
    )
    period = PlanPeriod.objects.get(user=user, effective_month="2027-06")
    assert period.items.count() == user.piles.count()
    assert sum(i.percent for i in period.items.all()) == 100


def test_save_plan_changes_allocation_from_that_month(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    data = {"action": "save", "id": period.pk, "name": period.name}
    for pile in user.piles.all():
        data[f"percent_{pile.pk}"] = "50" if pile == spend else "0"
        data[f"fixed_{pile.pk}"] = "1000" if pile == spend else "0"
    client_in.post(reverse("planner:plan"), data)
    month = user.planner_settings.start_month
    html = client_in.get(reverse("planner:summary"), {"m": month}).content.decode()
    assert "฿25,000" in html  # 48,000 * 50% + 1,000


def test_delete_pile_in_use_is_blocked(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    LogEntry.objects.create(
        user=user, date=date(2027, 1, 1), type="spend", from_pile=spend, amount=5,
    )
    client_in.post(reverse("planner:piles"), {"action": "delete", "id": spend.pk})
    assert Pile.objects.filter(pk=spend.pk).exists()


def test_logout_modal_posts_to_logout(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert 'id="logout-modal"' in html
    assert 'action="/accounts/logout/"' in html


def test_logout_via_post_signs_out(client_in):
    assert client_in.post("/accounts/logout/").status_code == 302
    assert client_in.get(reverse("planner:summary")).status_code == 302


@pytest.mark.parametrize(
    "name",
    ["planner:summary", "planner:log", "planner:settings", "planner:piles", "planner:plan"],
)
def test_every_page_renders(client_in, name):
    assert client_in.get(reverse(name)).status_code == 200


@pytest.mark.parametrize("name", ["planner:piles", "planner:plan"])
def test_action_bar_has_add_left_and_save_right(client_in, name):
    html = client_in.get(reverse(name)).content.decode()
    assert html.index('aria-label="เพิ่มใหม่"') < html.index('aria-label="บันทึก')


def test_edit_page_renders_with_add_link(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    entry = LogEntry.objects.create(
        user=user, date=date(2027, 1, 1), type="spend", from_pile=spend, amount=5,
    )
    resp = client_in.get(reverse("planner:log_edit", args=[entry.pk]))
    assert resp.status_code == 200
    assert b'aria-label="\xe0\xb9\x80\xe0\xb8\x9e\xe0\xb8\xb4\xe0\xb9\x88\xe0\xb8\xa1\xe0\xb9\x83\xe0\xb8\xab\xe0\xb8\xa1\xe0\xb9\x88"' in resp.content


def test_salary_form_has_add_toggle_left_and_save_right(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    start = html.index('value="salary_add"')
    section = html[start:]
    assert section.index("@click=") < section.index('type="submit"')
    assert 'x-data="{ open: false }"' in html  # salary exists -> collapsed


def test_month_bar_navigation(client_in, user):
    start = user.planner_settings.start_month
    html = client_in.get(reverse("planner:summary"), {"m": start}).content.decode()
    assert "month-bar" in html
    assert "Previous month" not in html and "เดือนก่อนหน้า" not in html  # first month
    assert "เดือนถัดไป" in html
    html = client_in.get(reverse("planner:summary"), {"m": "2099-01"}).content.decode()
    assert 'aria-label="เดือนก่อนหน้า"' not in html  # unknown month -> first month
