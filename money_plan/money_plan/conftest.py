from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.utils import translation
from django.core.management import call_command

from money_plan.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from money_plan.users.models import User


@pytest.fixture(scope="session", autouse=True)
def _compiled_messages() -> None:
    """The .mo files are not committed; build them so translations work."""
    call_command("compilemessages", verbosity=0)


@pytest.fixture(autouse=True)
def _default_language(settings):
    """LocaleMiddleware leaves the last request's language active on the thread;
    start every test from the project default so names/labels are predictable."""
    translation.activate(settings.LANGUAGE_CODE)
    yield
    translation.deactivate()


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()
