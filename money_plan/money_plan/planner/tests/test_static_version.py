import re

import pytest
from django.template import Context
from django.template import Template


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
