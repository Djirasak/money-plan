import re
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import translation

from money_plan.planner.templatetags.planner_tags import month_label

pytestmark = pytest.mark.django_db


def test_default_language_is_thai(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert "สรุปรายเดือน" in html


def test_english_when_language_switched(client_in):
    resp = client_in.post(
        reverse("set_language"),
        {"language": "en", "next": reverse("planner:summary")},
    )
    assert resp.status_code == 302
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert "Monthly summary" in html
    assert "สรุปรายเดือน" not in html


def test_month_label_follows_language():
    with translation.override("en"):
        assert month_label("2027-01") == "January 2027"
    with translation.override("th"):
        assert month_label("2027-01") == "มกราคม 2570"  # Buddhist Era


def test_no_thai_literals_left_in_code():
    """Source strings are English msgids; Thai lives only in locale/th."""
    root = Path(__file__).resolve().parents[2]
    thai = re.compile(r"[\u0e00-\u0e3e\u0e40-\u0e7f]")  # Thai, except the baht sign
    offenders = []
    for path in [*root.glob("planner/**/*.py"), *root.glob("templates/**/*.html")]:
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        if thai.search(path.read_text()):
            offenders.append(str(path.relative_to(root)))
    assert not offenders


def test_every_thai_message_is_translated():
    """Python and template strings alike must have a Thai translation."""
    po = Path(__file__).resolve().parents[3] / "locale/th/LC_MESSAGES/django.po"
    text = po.read_text()
    empty = re.findall(r'^msgid "(.+)"\nmsgstr ""$', text, re.MULTILINE)
    assert not empty, empty


def test_settings_language_toggle_is_one_icon_button_to_the_other_language(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert 'name="language" value="en"' in html  # Thai now -> offers English
    assert 'name="language" value="th"' not in html
    assert 'aria-label="เปลี่ยนภาษาเป็น English"' in html
    assert "data-busy" in html  # shows the grey loading overlay on submit


def test_language_toggle_round_trip(client_in):
    client_in.post(reverse("set_language"), {"language": "en", "next": "/settings/"})
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert 'name="language" value="th"' in html  # English now -> offers Thai
    assert 'aria-label="Switch language to ภาษาไทย"' in html


def test_vendor_scripts_loaded_on_every_page(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    for name in ("choices", "htmx", "alpine"):
        assert f"js/vendor/{name}.min.js" in html
    assert "X-CSRFToken" in html


def test_no_fuzzy_translations():
    """msgmerge marks guessed translations fuzzy; Django silently ignores them."""
    po = Path(__file__).resolve().parents[3] / "locale/th/LC_MESSAGES/django.po"
    assert "#, fuzzy" not in po.read_text()


def test_stored_months_stay_gregorian_whatever_the_display_language(client_in, user):
    """Only the label changes (B.E. in Thai); values in forms, URLs and the DB stay C.E."""
    start = user.planner_settings.start_month
    html = client_in.get(reverse("planner:summary"), {"m": start}).content.decode()
    year = int(start[:4])
    assert f'value="{start}"' in html  # <option value> is C.E.
    assert f"{year + 543}" in html  # label is B.E. in Thai
    client_in.post(reverse("set_language"), {"language": "en", "next": "/"})
    html = client_in.get(reverse("planner:summary"), {"m": start}).content.decode()
    assert f"{year + 543}" not in html
    assert f"{year}" in html


def test_month_picker_shows_buddhist_years_in_thai_but_posts_gregorian(client_in, user):
    year = int(user.planner_settings.start_month[:4])
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert f'<option value="{year}" selected>{year + 543}</option>' in html
    assert "ตุลาคม" in html  # full month names
    client_in.post(reverse("set_language"), {"language": "en", "next": "/settings/"})
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert f'<option value="{year}" selected>{year}</option>' in html


def test_target_label_reads_naturally():
    from decimal import Decimal

    from money_plan.planner.models import Pile
    from money_plan.planner.templatetags.planner_tags import target_label

    pile = Pile(target_percent=Decimal("60.00"), target_months=6)
    with translation.override("en"):
        assert target_label(pile) == "60% of salary x 6 months"
    with translation.override("th"):
        assert target_label(pile) == "60% ของเงินเดือน × 6 เดือน"
    assert target_label(Pile(target=Decimal(120000))) == "฿120,000"
