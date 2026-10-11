import re

import pytest
from django.contrib.staticfiles import finders
from django.template import Context
from django.template import Template


@pytest.fixture(autouse=True)
def _built_assets_exist(monkeypatch):
    """project.min.css / project.min.js are build output (git-ignored), absent on CI:
    answer for them with a tracked file so the tests only look at the URL logic."""
    real_find = finders.find
    stand_in = real_find("css/tailwind.css")

    def find(path, *args, **kwargs):
        return (
            stand_in
            if path in ("css/project.min.css", "js/project.min.js")
            else real_find(path, *args, **kwargs)
        )

    monkeypatch.setattr(finders, "find", find)


def render(path="css/project.min.css") -> str:
    return Template("{% load planner_tags %}{% static_v '" + path + "' %}").render(
        Context(),
    )


def test_debug_adds_the_file_modified_time(settings):
    settings.DEBUG = True
    assert re.fullmatch(r"/static/css/project\.min\.css\?v=\d+", render())


def test_no_version_when_debug_is_off(settings):
    settings.DEBUG = False
    assert render() == "/static/css/project.min.css"


def test_a_missing_file_does_not_break_the_page(settings):
    settings.DEBUG = True
    assert render("css/nope.css") == "/static/css/nope.css"


@pytest.mark.django_db
def test_base_template_uses_it(client, settings):
    settings.DEBUG = True
    html = client.get("/accounts/login/").content.decode()
    assert re.search(r"project\.min\.css\?v=\d+", html)
    assert re.search(r"project\.min\.js\?v=\d+", html)
