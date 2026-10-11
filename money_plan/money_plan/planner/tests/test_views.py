from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

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
    resp = client_in.get(reverse("planner:summary_content"))
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
    html = client_in.get(
        reverse("planner:summary_content"),
        {"m": month},
    ).content.decode()
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
        user=other,
        date=date(2027, 1, 1),
        type="spend",
        from_pile=pile,
        amount=5,
    )
    assert (
        client_in.post(reverse("planner:log_delete", args=[entry.pk])).status_code
        == 404
    )
    assert LogEntry.objects.filter(pk=entry.pk).exists()


def test_add_pile_and_plan_period_copies_previous(client_in, user):
    client_in.post(
        reverse("planner:piles"),
        {
            "action": "save",
            "new-name": "ท่องเที่ยว",
            "new-color": "#ff0000",
            "new-kind": "fund",
            "new-mode": "rollover",
            "new-order": 9,
            "new-target_mode": "none",
        },
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
    client_in.post(reverse("planner:plan"), data)
    month = user.planner_settings.start_month
    html = client_in.get(
        reverse("planner:summary_content"),
        {"m": month},
    ).content.decode()
    assert "฿24,000" in html  # 48,000 * 50%


def test_delete_pile_in_use_is_blocked(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    LogEntry.objects.create(
        user=user,
        date=date(2027, 1, 1),
        type="spend",
        from_pile=spend,
        amount=5,
    )
    client_in.post(reverse("planner:piles"), {"action": "delete", "id": spend.pk})
    assert Pile.objects.filter(pk=spend.pk).exists()


def test_logout_modal_posts_to_logout(client_in, user):
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert 'id="logout-modal"' not in html  # moved to the account page
    # the avatar that opens the account page sits in the lazy-loaded summary
    content = client_in.get(reverse("planner:summary_content")).content.decode()
    assert 'aria-label="บัญชีของฉัน"' in content
    user_page = client_in.get(
        reverse("users:detail", kwargs={"pk": user.pk}),
    ).content.decode()
    assert 'id="logout-modal"' in user_page
    assert 'action="/accounts/logout/"' in user_page


def test_logout_via_post_signs_out(client_in):
    assert client_in.post("/accounts/logout/").status_code == 302
    assert client_in.get(reverse("planner:summary")).status_code == 302


@pytest.mark.parametrize(
    "name",
    [
        "planner:summary",
        "planner:log",
        "planner:settings",
        "planner:piles",
        "planner:plan",
    ],
)
def test_every_page_renders(client_in, name):
    assert client_in.get(reverse(name)).status_code == 200


def test_edit_page_renders_with_cancel_and_the_entry_values(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    entry = LogEntry.objects.create(
        user=user,
        date=date(2027, 1, 1),
        type="spend",
        from_pile=spend,
        amount=5,
    )
    resp = client_in.get(reverse("planner:log_edit", args=[entry.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert f'action="/log/{entry.pk}/edit/"' in html
    assert "ยกเลิก" in html  # a Cancel button replaces the old "+" link


def test_month_bar_navigation(client_in, user):
    start = user.planner_settings.start_month
    content = reverse("planner:summary_content")
    html = client_in.get(content, {"m": start}).content.decode()
    assert "month-bar" in html
    assert "Previous month" not in html and "เดือนก่อนหน้า" not in html  # first month
    assert "เดือนถัดไป" in html
    html = client_in.get(content, {"m": "2099-01"}).content.decode()
    assert 'aria-label="เดือนก่อนหน้า"' not in html  # unknown month -> first month


def test_summary_shell_lazy_loads_content_with_htmx(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert 'hx-get="/summary/content/' in html
    assert 'hx-trigger="load"' in html
    assert "฿48,000" not in html  # the calculation is not in the shell


def test_summary_content_requires_login(client):
    resp = client.get(reverse("planner:summary_content"))
    assert resp.status_code == 302
    assert "login" in resp.url


def test_general_settings_use_month_picker_and_percent(client_in, user):
    resp = client_in.post(
        reverse("planner:settings"),
        {
            "action": "general",
            "start_month_year": "2027",
            "start_month_month": "2",
            "salary_percent": "60",
        },
    )
    assert resp.status_code == 302
    cfg = user.planner_settings
    cfg.refresh_from_db()
    assert cfg.start_month == "2027-02"
    assert cfg.salary_multiplier == Decimal("0.6")


def test_general_settings_reject_percent_over_100(client_in, user):
    before = user.planner_settings.salary_multiplier
    client_in.post(
        reverse("planner:settings"),
        {
            "action": "general",
            "start_month_year": "2027",
            "start_month_month": "2",
            "salary_percent": "150",
        },
    )
    user.planner_settings.refresh_from_db()
    assert user.planner_settings.salary_multiplier == before


def test_settings_page_shows_percent_and_month_picker(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert 'name="start_month_month"' in html
    assert 'name="start_month_year"' in html
    assert 'name="salary_percent"' in html
    assert 'value="100"' in html  # multiplier 1 is shown as 100 %
    assert "salary_multiplier" not in html


def test_plan_can_be_added_from_month_picker(client_in, user):
    client_in.post(
        reverse("planner:plan"),
        {
            "action": "add",
            "effective_month_year": "2027",
            "effective_month_month": "8",
            "name": "Picker",
        },
    )
    assert PlanPeriod.objects.filter(user=user, effective_month="2027-08").exists()


def test_month_from_post_helper():
    from money_plan.planner.mixins import month_from_post

    assert month_from_post({"m": "2027-05"}, "m") == "2027-05"
    assert month_from_post({"m_year": "2027", "m_month": "5"}, "m") == "2027-05"
    assert month_from_post({"m_year": "x", "m_month": "5"}, "m") == ""
    assert month_from_post({}, "m") == ""


def _plan_post(user, period, **extra):
    data = {"action": "save", "id": period.pk, "name": period.name}
    for pile in user.piles.all():
        data[f"percent_{pile.pk}"] = "0"
    return data | extra


def test_plan_condition_can_be_saved_and_cleared(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    client_in.post(
        reverse("planner:plan"),
        _plan_post(
            user,
            period,
            condition_mode="on",
            condition_pile=reserve.pk,
            condition_op="gte",
            condition_amount="100000",
        ),
    )
    period.refresh_from_db()
    assert (period.cond_pile, period.cond_op, period.cond_amount) == (
        reserve,
        "gte",
        Decimal(100000),
    )
    client_in.post(reverse("planner:plan"), _plan_post(user, period))  # mode off
    period.refresh_from_db()
    assert (period.cond_pile, period.cond_op, period.cond_amount) == (None, "", None)


def test_incomplete_condition_is_rejected_and_nothing_changes(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    client_in.post(
        reverse("planner:plan"),
        _plan_post(
            user,
            period,
            condition_mode="on",
            condition_op="lt",
            name="renamed",
        ),
    )
    period.refresh_from_db()
    assert period.cond_op == "" and period.name != "renamed"


def test_cannot_use_another_users_pile_in_a_condition(
    client_in,
    user,
    django_user_model,
):
    other = django_user_model.objects.create_user("other2", password="x")  # noqa: S106
    foreign = Pile.objects.create(user=other, name="theirs")
    period = PlanPeriod.objects.get(user=user)
    client_in.post(
        reverse("planner:plan"),
        _plan_post(
            user,
            period,
            condition_mode="on",
            condition_pile=foreign.pk,
            condition_op="gte",
            condition_amount="1",
        ),
    )
    period.refresh_from_db()
    assert period.cond_pile is None


def test_two_plans_can_share_a_start_month(client_in, user):
    month = user.planner_settings.start_month
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    year, mon = month.split("-")
    resp = client_in.post(
        reverse("planner:plan"),
        {
            "action": "add",
            "effective_month_year": year,
            "effective_month_month": str(int(mon)),
            "name": "Rich",
            "condition_mode": "on",
            "condition_pile": reserve.pk,
            "condition_op": "gte",
            "condition_amount": "50000",
        },
    )
    assert resp.status_code == 302
    assert PlanPeriod.objects.filter(user=user, effective_month=month).count() == 2
    new = PlanPeriod.objects.get(user=user, name="Rich")
    assert new.items.count() == user.piles.count()  # copied from the plan in force


def test_summary_uses_the_plan_whose_condition_is_met(client_in, user):
    from money_plan.planner.models import PlanItem

    month = user.planner_settings.start_month
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    # a conditional plan that is met from the start (balance 0 < 1) and gives 100% to spending
    rich = PlanPeriod.objects.create(
        user=user,
        effective_month=month,
        name="Lean",
        cond_pile=spend,
        cond_op="lt",
        cond_amount=1,
    )
    for pile in user.piles.all():
        PlanItem.objects.create(
            period=rich,
            pile=pile,
            percent=100 if pile == spend else 0,
        )
    html = client_in.get(
        reverse("planner:summary_content"),
        {"m": month},
    ).content.decode()
    assert "Lean" in html  # the hero names the plan that is actually in force
    assert "฿48,000" in html  # spend gets 100% of the salary


def test_pile_used_by_a_plan_condition_cannot_be_deleted(client_in, user):
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    PlanPeriod.objects.create(
        user=user,
        effective_month="2030-01",
        cond_pile=reserve,
        cond_op="gte",
        cond_amount=1,
    )
    client_in.post(reverse("planner:piles"), {"action": "delete", "id": reserve.pk})
    assert Pile.objects.filter(pk=reserve.pk).exists()


def _condition_post(user, period, pile, **extra):
    return _plan_post(
        user,
        period,
        condition_mode="on",
        condition_pile=pile.pk,
        condition_op="gte",
        **extra,
    )


def test_condition_can_follow_the_piles_target(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    reserve.target = Decimal(250000)
    reserve.save()
    client_in.post(
        reverse("planner:plan"),
        _condition_post(user, period, reserve, condition_use_target="on"),
    )
    period.refresh_from_db()
    assert period.cond_use_target is True
    assert period.cond_amount == Decimal(250000)  # snapshot at save time
    # the condition follows the target when it is changed later
    reserve.target = Decimal(300000)
    reserve.save()
    period.refresh_from_db()
    condition = period.to_condition()
    assert condition.use_target is True  # resolved against the pile's goal each month


def test_using_the_target_needs_a_pile_with_a_target(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    assert reserve.target is None
    client_in.post(
        reverse("planner:plan"),
        _condition_post(user, period, reserve, condition_use_target="on"),
    )
    period.refresh_from_db()
    assert period.cond_op == ""  # rejected, nothing saved


def test_typed_amount_still_works_without_the_target(client_in, user):
    period = PlanPeriod.objects.get(user=user)
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    reserve.target = Decimal(250000)
    reserve.save()
    client_in.post(
        reverse("planner:plan"),
        _condition_post(user, period, reserve, condition_amount="999"),
    )
    period.refresh_from_db()
    assert period.cond_use_target is False
    assert period.to_condition().amount == Decimal(999)


def test_plan_page_exposes_pile_targets_to_the_form(client_in, user):
    reserve = Pile.objects.get(user=user, name="เงินสำรอง")
    reserve.target = Decimal(120000)
    reserve.save()
    html = client_in.get(reverse("planner:plan")).content.decode()
    assert 'id="pile-targets"' in html
    assert f'"{reserve.pk}": "\\u0e3f120,000"' in html  # json_script escapes non-ASCII
    assert 'name="condition_use_target"' in html


def _salary_dialog_post(user, **extra):
    year, month = user.planner_settings.start_month.split("-")
    return {
        "action": "salary_save",
        "effective_month_year": year,
        "effective_month_month": str(int(month)),
        "amount": "50000",
    } | extra


def test_salaries_are_cards_with_modals_and_icon_buttons(client_in, user):
    html = client_in.get(reverse("planner:settings")).content.decode()
    salary = Salary.objects.get(user=user)
    assert f'data-open-dialog="salary-edit-{salary.pk}"' in html
    assert (
        f'data-delete-id="{salary.pk}"' in html
        and 'data-open-dialog="salary-new"' in html
    )
    assert 'id="salary-new"' in html and f'id="salary-edit-{salary.pk}"' in html
    assert 'class="btn-danger"' not in html  # no more text "ลบ" button
    assert html.count('id="cond') == 0  # (plan page only) sanity


def test_editing_a_salary_changes_amount_and_month(client_in, user):
    salary = Salary.objects.get(user=user)
    year, month = user.planner_settings.start_month.split("-")
    resp = client_in.post(
        reverse("planner:settings"),
        _salary_dialog_post(
            user,
            id=salary.pk,
            amount="61000",
            effective_month_year=str(int(year) + 1),
        ),
    )
    assert resp.status_code == 302
    salary.refresh_from_db()
    assert salary.amount == Decimal(61000)
    assert salary.effective_month == f"{int(year) + 1}-{month}"


def test_adding_a_salary_via_the_modal_form(client_in, user):
    year = int(user.planner_settings.start_month[:4]) + 1
    client_in.post(
        reverse("planner:settings"),
        _salary_dialog_post(user, effective_month_year=str(year), amount="70000"),
    )
    assert Salary.objects.filter(
        user=user,
        effective_month__startswith=str(year),
        amount=70000,
    ).exists()


def test_moving_a_salary_onto_an_existing_month_is_rejected_and_the_modal_reopens(
    client_in,
    user,
):
    first = Salary.objects.get(user=user)
    year = int(user.planner_settings.start_month[:4]) + 1
    other = Salary.objects.create(user=user, effective_month=f"{year}-03", amount=1)
    resp = client_in.post(
        reverse("planner:settings"),
        {
            "action": "salary_save",
            "id": other.pk,
            "effective_month_year": first.effective_month[:4],
            "effective_month_month": str(int(first.effective_month[5:])),
            "amount": "123",
        },
    )
    assert resp.status_code == 200  # re-rendered with the error, not redirected
    html = resp.content.decode()
    assert "data-auto-open" in html and 'value="123"' in html  # modal open, input kept
    other.refresh_from_db()
    assert other.effective_month == f"{year}-03"


def test_deleting_a_salary_uses_the_confirm_dialog_post(client_in, user):
    salary = Salary.objects.get(user=user)
    client_in.post(
        reverse("planner:settings"),
        {"action": "salary_delete", "id": salary.pk},
    )
    assert not Salary.objects.filter(pk=salary.pk).exists()


def test_cannot_edit_another_users_salary(client_in, django_user_model):
    other = django_user_model.objects.create_user("other4", password="x")  # noqa: S106
    theirs = Salary.objects.create(user=other, effective_month="2030-01", amount=1)
    resp = client_in.post(
        reverse("planner:settings"),
        {"action": "salary_save", "id": theirs.pk, "amount": "9"},
    )
    assert resp.status_code == 404
    theirs.refresh_from_db()
    assert theirs.amount == 1


def test_log_entry_tone_colours(client_in, user):
    a, b = Pile.objects.filter(user=user)[:2]
    month = user.planner_settings.start_month

    def make(kind, src, dst):
        return LogEntry.objects.create(
            user=user,
            date=f"{month}-05",
            type=kind,
            from_pile=src,
            to_pile=dst,
            amount=10,
        )

    assert make("spend", a, None).tone == "out"
    assert make("adjust", None, a).tone == "adjust"  # its own colour, not income
    assert make("adjust", a, None).tone == "adjust"
    assert make("income", None, a).tone == "in"
    assert make("transfer", a, b).tone == "move"
    assert make("sweep", a, b).tone == "move"
    html = client_in.get(reverse("planner:log"), {"m": month}).content.decode()
    assert all(f"entry-{tone}" in html for tone in ("out", "in", "move", "adjust"))
    assert 'id="entry-dialog"' in html and "data-auto-open" not in html


def test_log_loads_25_then_10_at_a_time(client_in, user):
    pile = Pile.objects.filter(user=user).first()
    month = user.planner_settings.start_month
    for i in range(40):
        LogEntry.objects.create(
            user=user,
            date=f"{month}-05",
            type="spend",
            from_pile=pile,
            amount=i + 1,
        )
    url = reverse("planner:log")
    html = client_in.get(url, {"m": month}).content.decode()
    assert html.count('class="item entry') == 25 and "offset=25" in html
    resp = client_in.get(
        url,
        {"m": month, "offset": 25},
        headers={"HX-Request": "true"},
    )
    html = resp.content.decode()
    assert html.count('class="item entry') == 10 and "offset=35" in html
    html = client_in.get(
        url,
        {"m": month, "offset": 35},
        headers={"HX-Request": "true"},
    ).content.decode()
    assert html.count('class="item entry') == 5
    assert "Load more" not in html and "ไม่มีรายการเพิ่มแล้ว" in html and "<html" not in html


def test_clear_all_needs_the_typed_word(client_in, user):
    before = (
        Pile.objects.filter(user=user).count(),
        Salary.objects.filter(user=user).count(),
    )
    assert before[0] and before[1]
    client_in.post(
        reverse("planner:settings"),
        {"action": "clear_all", "confirm": "nope"},
    )
    after = (
        Pile.objects.filter(user=user).count(),
        Salary.objects.filter(user=user).count(),
    )
    assert after == before


def test_clear_all_deletes_everything_but_the_user(client_in, user):
    pile = Pile.objects.filter(user=user).first()
    LogEntry.objects.create(
        user=user,
        date=f"{user.planner_settings.start_month}-05",
        type="spend",
        from_pile=pile,
        amount=5,
    )
    resp = client_in.post(
        reverse("planner:settings"),
        {"action": "clear_all", "confirm": " ลบทั้งหมด "},
    )
    assert resp.status_code == 302
    assert not Pile.objects.filter(user=user).exists()
    assert not LogEntry.objects.filter(user=user).exists()
    assert not PlanPeriod.objects.filter(user=user).exists()
    assert not Salary.objects.filter(user=user).exists()
    assert type(user).objects.filter(pk=user.pk).exists()
    # the app still opens afterwards (starter piles are seeded again on the next visit)
    assert client_in.get(reverse("planner:summary")).status_code == 200


def test_clear_all_dialog_is_on_general_settings(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert 'id="clear-all"' in html and 'data-open-dialog="clear-all"' in html


class TestPlanCards:
    def page(self, client):
        return client.get(reverse("planner:plan")).content.decode()

    def test_each_plan_is_a_card_that_opens_its_edit_dialog(self, client_in, user):
        period = PlanPeriod.objects.get(user=user)
        html = self.page(client_in)
        assert f'data-open-dialog="plan-edit-{period.pk}"' in html
        assert f'id="plan-edit-{period.pk}"' in html
        assert 'id="plan-new"' in html
        assert 'data-open-dialog="plan-new"' in html

    def test_the_card_summarises_the_split_without_editing_fields(
        self,
        client_in,
        user,
    ):
        html = self.page(client_in)
        card = html.split('class="item plan-card"')[1].split("</li>")[0]
        assert "รวม 100%" in card  # the total badge
        assert "plan-bar" in card  # the stacked bar of the split
        assert "55%" in card  # the biggest share, in brief
        assert "<input" not in card  # editing happens in the dialog, not on the card
        assert "ใช้เสมอ" in card  # no condition

    def test_a_condition_is_spelled_out_on_the_card(self, client_in, user):
        reserve = Pile.objects.get(user=user, name="เงินสำรอง")
        PlanPeriod.objects.filter(user=user).update(
            cond_pile=reserve,
            cond_op="gte",
            cond_amount=Decimal(250000),
            cond_use_target=False,
        )
        html = self.page(client_in)
        assert "ใช้เฉพาะเมื่อ เงินสำรอง" in html
        assert "฿250,000" in html

    def test_a_total_that_is_not_100_is_flagged(self, client_in, user):
        period = PlanPeriod.objects.get(user=user)
        period.items.update(percent=10)
        html = self.page(client_in)
        assert (
            "bg-warn-soft" in html.split('class="item plan-card"')[1].split("</li>")[0]
        )

    def test_a_plan_with_nothing_allocated_says_so(self, client_in, user):
        PlanPeriod.objects.get(user=user).items.update(percent=0)
        assert "แผนนี้ยังไม่ได้จัดสรรเงินให้กองใด" in self.page(client_in)

    def test_the_dialog_posts_the_same_fields_as_before(self, client_in, user):
        period = PlanPeriod.objects.get(user=user)
        html = self.page(client_in)
        dialog = html.split(f'id="plan-edit-{period.pk}"')[1].split("</dialog>")[0]
        assert 'name="action" value="save"' in dialog
        for pile in user.piles.all():
            assert f'name="percent_{pile.pk}"' in dialog
        assert "data-percent" in dialog  # drives the live total
        assert 'name="condition_mode"' in dialog


class TestPlanLiveCheckAndLogRows:
    def test_plan_card_has_a_visible_edit_button_besides_delete(self, client_in, user):
        period = PlanPeriod.objects.get(user=user)
        card = (
            client_in.get(reverse("planner:plan"))
            .content.decode()
            .split('class="item plan-card"')[1]
            .split("</li>")[0]
        )
        aside = card.split("<aside")[1]
        assert (
            f'data-open-dialog="plan-edit-{period.pk}"' in aside
        )  # a pencil of its own
        assert "data-confirm-delete" in aside

    def test_the_dialog_checks_for_100_percent_while_typing(self, client_in, user):
        period = PlanPeriod.objects.get(user=user)
        html = client_in.get(reverse("planner:plan")).content.decode()
        dialog = html.split(f'id="plan-edit-{period.pk}"')[1].split("</dialog>")[0]
        assert '@input="sum()"' in dialog
        assert 'role="status"' in dialog  # announced politely
        assert "ครบ 100% แล้ว" in dialog
        assert "ที่ยังไม่ได้จัดสรร" in dialog and "เกิน 100%" in dialog  # both ways off
        assert "__n__" in dialog  # placeholder the page script fills in

    def test_log_rows_carry_a_watermark_svg(
        self,
        client_in,
        user,
    ):
        spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
        spend.icon = "car"
        spend.save()
        LogEntry.objects.create(
            user=user,
            date=date(2027, 1, 5),
            type="spend",
            from_pile=spend,
            amount=150,
        )
        html = client_in.get(reverse("planner:log"), {"m": "2027-01"}).content.decode()
        row = html.split('class="item entry entry-out"')[1].split("</li>")[0]
        assert 'class="entry-watermark" aria-hidden="true"' in row
        assert "<svg" in row.split("entry-watermark")[1].split("</span>")[0]


def test_log_rows_have_no_leading_icon_only_the_arrow_watermark(client_in, user):
    spend = Pile.objects.get(user=user, name="ค่าใช้จ่าย")
    LogEntry.objects.create(
        user=user,
        date=date(2027, 1, 5),
        type="spend",
        from_pile=spend,
        amount=150,
    )
    html = client_in.get(reverse("planner:log"), {"m": "2027-01"}).content.decode()
    row = html.split('class="item entry entry-out"')[1].split("</li>")[0]
    assert "entry-icon" not in row
    assert "entry-watermark" in row
    assert (
        "M7 7h10v10" in row.split("entry-watermark")[1]
    )  # the out arrow (arrow-up-right)
    assert "-฿150" in row  # the sign and the word still say what kind of entry it is


class TestAdjustAndIncome:
    def post(self, client, user, **data):
        month = user.planner_settings.start_month
        body = {"date": f"{month}-05", "amount": "500", "m": month, **data}
        return client.post(reverse("planner:log"), body)

    def pile(self, user, name="เงินใช้ฟรี"):
        return Pile.objects.get(user=user, name=name)

    def balance(self, user, pile, exclude=None):
        from money_plan.planner import services

        return services.pile_balance(
            user,
            pile,
            user.planner_settings.start_month,
            exclude,
        )

    def test_adjust_takes_the_real_balance_and_records_the_difference_up(
        self,
        client_in,
        user,
    ):
        free = self.pile(user)
        system = self.balance(user, free)
        assert (
            self.post(
                client_in,
                user,
                type="adjust",
                to_pile=free.pk,
                amount=f"{system + 500:.2f}",
            ).status_code
            == 302
        )
        entry = LogEntry.objects.get(user=user)
        assert (entry.type, entry.from_pile, entry.to_pile, entry.amount) == (
            "adjust",
            None,
            free,
            500,
        )
        assert (entry.tone, entry.sign) == ("adjust", "+")
        assert (
            self.balance(user, free) == system + 500
        )  # now the system shows the real balance

    def test_adjust_records_a_difference_downwards_too(self, client_in, user):
        free = self.pile(user)
        system = self.balance(user, free)
        self.post(
            client_in,
            user,
            type="adjust",
            to_pile=free.pk,
            amount=f"{system - 200:.2f}",
        )
        entry = LogEntry.objects.get(user=user)
        assert (entry.from_pile, entry.to_pile, entry.amount, entry.sign) == (
            free,
            None,
            200,
            "-",
        )
        assert self.balance(user, free) == system - 200

    def test_adjust_to_zero_is_allowed_but_not_to_less_or_the_same(
        self,
        client_in,
        user,
    ):
        free = self.pile(user)
        system = self.balance(user, free)
        assert (
            self.post(
                client_in,
                user,
                type="adjust",
                to_pile=free.pk,
                amount="-5",
            ).status_code
            == 200
        )
        assert (
            self.post(
                client_in,
                user,
                type="adjust",
                to_pile=free.pk,
                amount=f"{system:.2f}",
            ).status_code
            == 200
        )
        assert not LogEntry.objects.filter(user=user).exists()
        assert (
            self.post(
                client_in,
                user,
                type="adjust",
                to_pile=free.pk,
                amount="0",
            ).status_code
            == 302
        )
        assert self.balance(user, free) == 0

    def test_editing_an_adjustment_shows_the_real_balance_and_keeps_it_stable(
        self,
        client_in,
        user,
    ):
        free = self.pile(user)
        system = self.balance(user, free)
        self.post(
            client_in,
            user,
            type="adjust",
            to_pile=free.pk,
            amount=f"{system + 500:.2f}",
        )
        entry = LogEntry.objects.get(user=user)
        form_page = client_in.get(
            reverse("planner:log_edit", args=[entry.pk]),
        ).content.decode()
        assert (
            f'value="{system + 500:.2f}"' in form_page
        )  # the real balance, not the difference
        month = user.planner_settings.start_month
        resp = client_in.post(
            reverse("planner:log_edit", args=[entry.pk]),
            {
                "date": f"{month}-05",
                "type": "adjust",
                "to_pile": free.pk,
                "amount": f"{system + 500:.2f}",
                "m": month,
            },
        )
        assert resp.status_code == 302
        entry.refresh_from_db()
        assert (entry.amount, entry.to_pile) == (500, free)
        assert LogEntry.objects.filter(user=user).count() == 1

    def test_the_form_asks_for_the_real_balance_when_adjusting(self, client_in, user):
        html = client_in.get(reverse("planner:log")).content.decode()
        assert "ยอดที่กองมีอยู่จริง (บาท)" in html
        assert "ใส่ยอดที่กองนี้มีอยู่จริง" in html

    def test_income_note_is_optional(self, client_in, user):
        free = self.pile(user)
        assert (
            self.post(client_in, user, type="income", to_pile=free.pk).status_code
            == 302
        )
        assert (
            self.post(
                client_in,
                user,
                type="income",
                to_pile=free.pk,
                note="โบนัสปลายปี",
            ).status_code
            == 302
        )
        entries = LogEntry.objects.filter(user=user, type="income").order_by("id")
        assert [e.note for e in entries] == ["", "โบนัสปลายปี"]
        assert all(e.tone == "in" and e.sign == "+" for e in entries)

    def test_adjust_has_its_own_colour_and_sign(self, client_in, user):
        free = self.pile(user)
        self.post(
            client_in,
            user,
            type="adjust",
            to_pile=free.pk,
            amount=f"{self.balance(user, free) + 500:.2f}",
        )
        self.post(client_in, user, type="income", to_pile=free.pk)
        month = user.planner_settings.start_month
        html = client_in.get(reverse("planner:log"), {"m": month}).content.decode()
        assert html.count("entry-adjust") == 1
        assert html.count('class="item entry entry-in"') == 1
        adjust_row = html.split("entry-adjust")[1].split("</li>")[0]
        assert "+฿500" in adjust_row

    @pytest.mark.parametrize("kind", ["adjust", "income"])
    def test_a_from_pile_is_refused_for_both(self, client_in, user, kind):
        a, b = Pile.objects.filter(user=user)[:2]
        resp = self.post(
            client_in,
            user,
            type=kind,
            from_pile=a.pk,
            to_pile=b.pk,
            note="x",
        )
        assert resp.status_code == 200
        assert not LogEntry.objects.filter(user=user).exists()

    @pytest.mark.parametrize("kind", ["adjust", "income"])
    def test_a_destination_is_required(self, client_in, user, kind):
        assert self.post(client_in, user, type=kind, note="x").status_code == 200
        assert not LogEntry.objects.filter(user=user).exists()

    def test_income_raises_the_pile_balance_like_any_money_in(self, client_in, user):
        from money_plan.planner import services

        free = self.pile(user)
        month = user.planner_settings.start_month

        def balance() -> Decimal:
            return services.compute_months(user, month)[0].piles[free.name].before

        before = balance()
        self.post(
            client_in,
            user,
            type="income",
            to_pile=free.pk,
            amount="1000",
            note="ขายของ",
        )
        assert balance() == before + 1000

    def test_the_form_greys_out_the_pile_that_does_not_apply(self, client_in, user):
        html = client_in.get(reverse("planner:log")).content.decode()
        assert "get noFrom()" in html and "adjust" in html and "income" in html
        assert ':inert="noFrom"' in html and ':inert="noTo"' in html
        assert "รับเงิน" in html  # the new type is offered, translated
        assert (
            "เงินนี้ได้มาจากไหน? (ไม่บังคับ)" in html
        )  # the note asks for the source on income, but does not insist

    def test_log_rows_show_a_sync_icon_for_adjust_and_an_arrow_for_income(
        self,
        client_in,
        user,
    ):
        free = self.pile(user)
        self.post(
            client_in,
            user,
            type="adjust",
            to_pile=free.pk,
            amount=f"{self.balance(user, free) + 500:.2f}",
        )
        self.post(client_in, user, type="income", to_pile=free.pk, note="โบนัส")
        month = user.planner_settings.start_month
        html = client_in.get(reverse("planner:log"), {"m": month}).content.decode()
        adjust_row = html.split('class="item entry entry-adjust"')[1].split("</li>")[0]
        income_row = html.split('class="item entry entry-in"')[1].split("</li>")[0]
        assert "M3 12a9 9 0 0 1 9-9" in adjust_row  # refresh-cw
        assert "M17 7 7 17" in income_row  # arrow-down-left
