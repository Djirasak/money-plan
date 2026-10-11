import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def run(**kwargs):
    call_command("initial_user_data", username="seed", email="s@example.com", **kwargs)


def test_creates_superuser_with_planner_defaults():
    run(password="pw-123456")
    user = get_user_model().objects.get(username="seed")
    assert user.is_superuser
    assert user.check_password("pw-123456")
    assert user.piles.exists()
    assert user.planner_settings.start_month


def test_is_idempotent_and_keeps_password():
    run(password="first-pw-1")
    run(password="other-pw-2")
    user = get_user_model().objects.get(username="seed")
    assert user.check_password("first-pw-1")
    assert get_user_model().objects.filter(username="seed").count() == 1
    assert user.piles.count() == 3


def test_reset_password_flag():
    run(password="first-pw-1")
    run(password="other-pw-2", reset_password=True)
    assert get_user_model().objects.get(username="seed").check_password("other-pw-2")


def test_first_run_skips_when_a_user_exists(user):
    run(password="pw-123456", first_run=True)
    assert not get_user_model().objects.filter(username="seed").exists()


def test_first_run_creates_user_on_empty_db():
    run(password="pw-123456", first_run=True)
    assert get_user_model().objects.filter(username="seed").exists()
