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
    for path in [
        *(ROOT / "templates").rglob("*.html"),
        *ROOT.glob("planner/**/*.py"),
        ROOT / "static/js/project.js",
    ]:
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        if PICTOGRAPHS.search(path.read_text()):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders  # use {% icon %} (lucide) or words instead


def test_icon_tag_renders_decorative_inline_svg():
    html = Template('{% load planner_tags %}{% icon "plus" "size-6" %}').render(
        Context(),
    )
    assert html.startswith('<svg class="size-6" aria-hidden="true" focusable="false"')
    assert "currentColor" in html


def test_icon_tag_escapes_class():
    html = Template('{% load planner_tags %}{% icon "plus" cls %}').render(
        Context({"cls": '"><script>'}),
    )
    assert "<script>" not in html


def test_every_icon_file_exists_and_is_an_svg():
    files = list(ICON_DIR.glob("*.svg"))
    assert len(files) >= 10
    assert all(f.read_text().lstrip().startswith("<svg") for f in files)


@pytest.mark.parametrize(
    "name",
    ["planner:settings", "planner:plan", "planner:piles", "planner:log"],
)
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
    assert "data-theme-toggle" in html and 'role="switch" aria-checked="false"' in html
    assert 'aria-label="โหมดมืด"' in html
    # the saved/system theme sets the shadcn "dark" class before the CSS paints
    assert html.index("classList.toggle('dark'") < html.index("project.min.css")
    assert 'id="busy-overlay"' in html and 'role="status"' in html


def test_ui_does_not_hardcode_light_only_colours():
    """Surfaces and text use semantic tokens so dark mode can swap them."""
    bad = re.compile(
        r"(?<![\w/-])(bg-white|bg-slate-\d+|text-slate-\d+|bg-(?:rose|emerald|amber)-(?:50|100|200))(?![\w/%-])",
    )
    offenders = {}
    for path in (ROOT / "templates").rglob("*.html"):
        found = bad.findall(path.read_text())
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert not offenders, offenders


def test_messages_are_toasts_with_the_right_roles(client_in, user):
    from money_plan.planner.models import Pile

    pile = Pile.objects.get(user=user, name="เงินสำรอง")
    prefix = f"p{pile.pk}"
    bad = {
        "action": "save",
        "id": pile.pk,
        f"{prefix}-name": pile.name,
        f"{prefix}-color": "#10b981",
        f"{prefix}-kind": "fund",
        f"{prefix}-mode": "rollover",
        f"{prefix}-target_mode": "salary",
    }  # percent and months missing
    html = client_in.post(reverse("planner:piles"), bad, follow=True).content.decode()
    toaster = html[html.index('id="toaster"') :]
    assert 'class="toast" role="alert"' in toaster  # errors are announced assertively
    assert 'data-category="error"' in toaster and 'data-duration="9000"' in toaster
    assert "กรอกเปอร์เซ็นต์ของเงินเดือน" in toaster and "กรอกจำนวนเดือน" in toaster
    assert 'class="mb-3 space-y-2"' not in html  # no inline banner at the top
    ok = client_in.post(reverse("planner:log_delete", args=[999999]), follow=True)
    assert ok.status_code == 404


def test_placeholders_read_as_examples_not_values(client_in):
    html = client_in.get(reverse("planner:piles")).content.decode()
    assert 'placeholder="เช่น 60"' in html
    assert 'placeholder="60"' not in html and 'placeholder="6"' not in html


def test_settings_offers_twelve_colour_themes(client_in):
    html = client_in.get(reverse("planner:settings")).content.decode()
    assert html.count("data-color-choice=") == 12
    assert 'data-color-choice="indigo"' in html
    assert 'role="radiogroup"' in html


def test_default_theme_is_light_not_the_system_setting(client_in):
    html = client_in.get(reverse("planner:summary")).content.decode()
    assert "prefers-color-scheme" not in html


def test_no_template_has_a_comment_that_spans_lines():
    """``{# ... #}`` must stay on one line: a second line makes Django print the whole comment on the page."""
    templates = Path(__file__).resolve().parents[2] / "templates"
    broken = [
        f"{path.relative_to(templates)}:{number}"
        for path in templates.rglob("*.html")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "{#" in line and "#}" not in line.split("{#", 1)[1]
    ]
    assert not broken, f"multi-line {{# #}} comments (use {{% comment %}}): {broken}"
