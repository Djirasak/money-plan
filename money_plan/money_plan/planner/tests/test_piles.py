"""Pile forms exactly as a browser posts them (prefixed names, hidden inputs)."""

from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.urls import reverse

from money_plan.planner.models import Pile
from money_plan.planner.models import Salary

pytestmark = pytest.mark.django_db


class FormFields(HTMLParser):
    """Collect name -> value for every control of the forms on a page."""

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({})
        elif not self.forms:
            return
        elif tag == "input" and a.get("name"):
            if a.get("type") in ("checkbox", "radio") and "checked" not in a:
                return
            self.forms[-1][a["name"]] = a.get("value", "")
        elif tag == "select" and a.get("name"):
            self._select = a["name"]
            self.forms[-1].setdefault(self._select, "")
            self._first = True
        elif tag == "option" and self._select:
            if self._first or "selected" in a:
                self.forms[-1][self._select] = a.get("value", "")
            self._first = False

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def page_forms(client, name):
    parser = FormFields()
    parser.feed(client.get(reverse(name)).content.decode())
    return [f for f in parser.forms if f.get("action") == "save" or "action" in f]


def form_for(client, pile_name, user):
    pile = Pile.objects.get(user=user, name=pile_name)
    for form in page_forms(client, "planner:piles"):
        if form.get("id") == str(pile.pk):
            return pile, dict(form)
    raise AssertionError("pile form not found")


def test_editing_a_pile_as_the_browser_posts_it_is_saved(client_in, user):
    pile, data = form_for(client_in, "ค่าใช้จ่าย", user)
    prefix = f"p{pile.pk}"
    assert f"{prefix}-name" in data  # the page really uses prefixed names
    data[f"{prefix}-name"] = "Food"
    assert client_in.post(reverse("planner:piles"), data).status_code == 302
    pile.refresh_from_db()
    assert pile.name == "Food"


def test_target_is_a_fixed_amount(client_in, user):
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    data |= {f"{prefix}-target_mode": "fixed", f"{prefix}-target": "250000"}
    client_in.post(reverse("planner:piles"), data)
    pile.refresh_from_db()
    assert pile.target == Decimal(250000)
    assert pile.target_percent is None and pile.target_months is None
    assert pile.has_target and not pile.has_salary_target


def test_target_follows_the_salary(client_in, user):
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    data |= {
        f"{prefix}-target_mode": "salary",
        f"{prefix}-target_percent": "60",
        f"{prefix}-target_months": "6",
    }
    client_in.post(reverse("planner:piles"), data)
    pile.refresh_from_db()
    assert (pile.target, pile.target_percent, pile.target_months) == (None, Decimal(60), 6)
    assert pile.to_engine().target_for(Decimal(48000)) == Decimal(172800)  # 60% x 48,000 x 6


@pytest.mark.parametrize(
    "extra",
    [
        {"target_mode": "fixed"},  # amount missing
        {"target_mode": "salary", "target_percent": "60"},  # months missing
        {"target_mode": "salary", "target_months": "6"},  # percent missing
        {"target_mode": "salary", "target_percent": "60", "target_months": "0"},
    ],
)
def test_incomplete_targets_are_rejected(client_in, user, extra):
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    data |= {f"{prefix}-{k}": v for k, v in extra.items()}
    data[f"{prefix}-target"] = data.get(f"{prefix}-target") if "target" in extra else ""
    client_in.post(reverse("planner:piles"), data)
    pile.refresh_from_db()
    assert not pile.has_target


def test_switching_back_to_no_target_clears_everything(client_in, user):
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    client_in.post(
        reverse("planner:piles"),
        data | {f"{prefix}-target_mode": "fixed", f"{prefix}-target": "5"},
    )
    pile, data = form_for(client_in, "เงินสำรอง", user)
    client_in.post(reverse("planner:piles"), data | {f"{prefix}-target_mode": "none"})
    pile.refresh_from_db()
    assert (pile.target, pile.target_percent, pile.target_months) == (None, None, None)


def test_summary_shows_the_target_for_the_month_following_the_salary(client_in, user):
    start = user.planner_settings.start_month
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    client_in.post(
        reverse("planner:piles"),
        data
        | {
            f"{prefix}-target_mode": "salary",
            f"{prefix}-target_percent": "50",
            f"{prefix}-target_months": "2",
        },
    )
    html = client_in.get(reverse("planner:summary_content"), {"m": start}).content.decode()
    assert "฿48,000" in html  # 50% x 48,000 x 2
    Salary.objects.filter(user=user).update(amount=60000)
    html = client_in.get(reverse("planner:summary_content"), {"m": start}).content.decode()
    assert "฿60,000" in html  # the target moved with the raise


def test_new_pile_form_is_prefixed_too(client_in, user):
    forms = page_forms(client_in, "planner:piles")
    new = next(f for f in forms if "new-name" in f)
    new |= {"new-name": "Trip", "new-target_mode": "salary", "new-target_percent": "10", "new-target_months": "3"}
    client_in.post(reverse("planner:piles"), new)
    trip = Pile.objects.get(user=user, name="Trip")
    assert trip.target_months == 3


def test_piles_are_cards_with_edit_and_delete_buttons(client_in, user):
    html = client_in.get(reverse("planner:piles")).content.decode()
    for pile in Pile.objects.filter(user=user):
        assert f'data-open-dialog="pile-edit-{pile.pk}"' in html  # edit opens its modal
        assert f'data-delete-id="{pile.pk}"' in html  # delete asks for confirmation
        assert f'id="pile-edit-{pile.pk}"' in html
    assert 'data-open-dialog="pile-new"' in html and 'id="pile-new"' in html
    assert 'id="confirm-delete"' in html


def test_order_is_gone_from_the_forms_and_new_piles_go_last(client_in, user):
    html = client_in.get(reverse("planner:piles")).content.decode()
    assert "-order" not in html and "ลำดับ" not in html
    forms = page_forms(client_in, "planner:piles")
    new = next(f for f in forms if "new-name" in f)
    client_in.post(reverse("planner:piles"), new | {"new-name": "Trip", "new-target_mode": "none"})
    trip = Pile.objects.get(user=user, name="Trip")
    assert trip.order == max(Pile.objects.filter(user=user).exclude(pk=trip.pk).values_list("order", flat=True)) + 1


def test_invalid_pile_form_reopens_its_dialog_with_the_input_kept(client_in, user):
    pile, data = form_for(client_in, "เงินสำรอง", user)
    prefix = f"p{pile.pk}"
    resp = client_in.post(
        reverse("planner:piles"),
        data | {f"{prefix}-name": "Keep me", f"{prefix}-target_mode": "salary"},  # percent/months missing
    )
    assert resp.status_code == 200  # re-rendered, not redirected
    html = resp.content.decode()
    assert f'data-auto-open-id="pile-edit-{pile.pk}"' in html
    assert 'value="Keep me"' in html  # what the user typed is still there
    assert "กรอกเปอร์เซ็นต์ของเงินเดือน" in html  # inline error + toast
    pile.refresh_from_db()
    assert pile.name != "Keep me"


def test_invalid_new_pile_reopens_the_create_dialog(client_in, user):
    forms = page_forms(client_in, "planner:piles")
    new = next(f for f in forms if "new-name" in f)
    resp = client_in.post(reverse("planner:piles"), new | {"new-name": "", "new-color": "#ff0000"})
    assert resp.status_code == 200
    assert 'data-auto-open-id="pile-new"' in resp.content.decode()


def test_cards_summarise_each_pile(client_in):
    html = client_in.get(reverse("planner:piles")).content.decode()
    assert "ทบได้ไม่เกิน ฿20,000" in html  # starter "free" pile has a 20,000 cap
