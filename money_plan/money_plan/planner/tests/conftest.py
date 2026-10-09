from decimal import Decimal

import pytest

from money_plan.planner import services
from money_plan.planner.models import Salary


@pytest.fixture
def client_in(client, user):
    client.force_login(user)
    services.ensure_defaults(user)
    Salary.objects.create(
        user=user,
        effective_month=user.planner_settings.start_month,
        amount=Decimal(48000),
    )
    return client
