"""Guards for the UI rules in CLAUDE.md that a template edit can silently break."""

import re
from pathlib import Path

import pytest
from django.template import Context
from django.template import Template
from django.urls import reverse

from money_plan.planner.templatetags.planner_tags import ICON_DIR

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
# arrows, geometric shapes, misc symbols, dingbats, emoji planes
PICTOGRAPHS = re.compile("[←-⇿■-◿☀-➿\U0001f000-\U0001faff]")


def test_no_pictographs_or_emoji_in_ui_sources():
    offenders = []
    for path in [*(ROOT / "templates").rglob("*.html"), *ROOT.glob("planner/**/*.py"), ROOT / "static/js/project.js"]:
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        if PICTOGRAPHS.search(path.read_text()):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders  # use {% icon %} (lucide) or words instead


def test_icon_tag_renders_decorative_inline_svg():
    html = Template('{% load planner_tags %}{% icon "plus" "size-6" %}').render(Context())
    assert html.startswith('<svg class="size-6" aria-hidden="true" focusable="false"')
    assert "currentColor" in html


def test_icon_tag_escapes_class():
    html = Template('{% load planner_tags %}{% icon "plus" cls %}').render(Context({"cls": '"><script>'}))
    assert "<script>" not in html


def test_every_icon_file_exists_and_is_an_svg():
    files = list(ICON_DIR.glob("*.svg"))
    assert len(files) >= 10
    assert all(f.read_text().lstrip().startswith("<svg") for f in files)


@pytest.mark.parametrize("name", ["planner:settings", "planner:plan", "planner:piles", "planner:log"])
def test_every_visible_input_has_an_accessible_name(client_in, name):
    html = client_in.get(reverse(name)).content.decode()
    for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", html):
        if re.search(r'type="(hidden|submit|checkbox|radio)"', tag):
            continue
        ident = re.search(r'\bid="([^"]+)"', tag)
        named = "aria-label=" in tag or (ident and f'for="{ident.group(1)}"' in html)
        assert named, f"unlabelled control: {tag[:120]}"


def test_bottom_nav_uses_icons_not_glyphs(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    nav = html[html.index("<nav") : html.index("</nav>")]
    assert nav.count("<svg") == 3


def test_dark_mode_toggle_and_no_flash_script(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert 'data-theme-toggle role="switch" aria-checked="false"' in html
    assert 'aria-label="โหมดมืด"' in html
    # the saved/system theme is applied by an inline script in <head>, before the CSS paints
    assert html.index("dataset.theme") < html.index("project.min.css")
    assert 'id="busy-overlay"' in html and 'role="status"' in html


def test_ui_does_not_hardcode_light_only_colours():
    """Surfaces and text use semantic tokens so dark mode can swap them."""
    bad = re.compile(r"(?<![\w/-])(bg-white|bg-slate-\d+|text-slate-\d+|bg-(?:rose|emerald|amber)-(?:50|100|200))(?![\w/%-])")
    offenders = {}
    for path in (ROOT / "templates").rglob("*.html"):
        found = bad.findall(path.read_text())
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert not offenders, offenders
