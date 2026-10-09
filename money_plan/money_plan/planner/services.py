from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from . import engine
from .models import LogEntry
from .models import PlanItem
from .models import PlanPeriod
from .models import Pile
from .models import PlannerSettings
from .models import Salary

HORIZON_MONTHS = 360


def current_month() -> str:
    return f"{timezone.localdate():%Y-%m}"


@transaction.atomic
def ensure_defaults(user: AbstractBaseUser) -> PlannerSettings:
    """First visit: a starter set of piles and a plan the user can edit."""
    cfg, created = PlannerSettings.objects.get_or_create(
        user=user,
        defaults={"start_month": current_month()},
    )
    if created and not user.piles.exists():
        reserve = Pile.objects.create(
            user=user,
            name="เงินสำรอง",
            color="#10b981",
            kind=Pile.FUND,
            order=3,
        )
        spend = Pile.objects.create(
            user=user,
            name="ค่าใช้จ่าย",
            color="#5b5bf0",
            order=1,
            overflow_to=reserve,
        )
        free = Pile.objects.create(
            user=user,
            name="เงินใช้ฟรี",
            color="#f59e0b",
            cap=Decimal(20000),
            order=2,
            overflow_to=reserve,
        )
        period = PlanPeriod.objects.create(
            user=user,
            effective_month=cfg.start_month,
            name="สะสมเงินสำรอง",
        )
        for pile, percent in ((spend, 55), (free, 12), (reserve, 33)):
            PlanItem.objects.create(period=period, pile=pile, percent=percent)
    return cfg


def month_range(start: str, count: int = HORIZON_MONTHS) -> list[str]:
    return [engine.add_months(start, i) for i in range(count)]


def compute_months(user: AbstractBaseUser, end_month: str) -> list[engine.Month]:
    cfg = ensure_defaults(user)
    piles = list(user.piles.select_related("overflow_to"))
    plan = []
    for period in user.plan_periods.prefetch_related("items__pile"):
        plan.append(
            engine.PlanRow(
                effective_month=period.effective_month,
                shares={i.pile.name: i.percent / 100 for i in period.items.all()},
                fixed={i.pile.name: i.fixed for i in period.items.all()},
            ),
        )
    entries = [e.to_engine() for e in LogEntry.objects.filter(user=user)
               .select_related("from_pile", "to_pile")]
    salaries = [
        engine.Salary(s.effective_month, s.amount)
        for s in Salary.objects.filter(user=user)
    ]
    if end_month < cfg.start_month:
        end_month = cfg.start_month
    return engine.compute(
        piles=[p.to_engine() for p in piles],
        salaries=salaries,
        plan=plan,
        entries=entries,
        start_month=cfg.start_month,
        end_month=end_month,
        salary_multiplier=cfg.salary_multiplier,
    )
