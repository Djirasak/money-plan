import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.views import defaults


@pytest.fixture
def request_():
    return RequestFactory().get("/boom/")


def test_404_page(client):
    resp = client.get("/definitely-not-here/")
    assert resp.status_code == 404
    assert "หาหน้านี้ไม่เจอ" in resp.content.decode()


def test_403_page(request_):
    resp = defaults.permission_denied(request_, PermissionDenied("x"))
    assert resp.status_code == 403
    html = resp.content.decode()
    assert "ตรงนี้เข้าไม่ได้นะ" in html
    assert "x</" not in html  # raw exception text is never shown


def test_500_page_renders_without_context(request_):
    resp = defaults.server_error(request_)
    assert resp.status_code == 500
    assert "ระบบสะดุดนิดหน่อย" in resp.content.decode()


def test_csrf_403_page(client):
    from django.template.loader import render_to_string

    html = render_to_string("403_csrf.html")
    assert "แบบฟอร์มหมดอายุแล้ว" in html
