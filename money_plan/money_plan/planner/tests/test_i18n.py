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
        assert month_label("2027-01") == "Jan 2027"
    with translation.override("th"):
        assert month_label("2027-01") == "ม.ค. 2027"


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
