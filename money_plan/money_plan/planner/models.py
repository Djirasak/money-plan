import re
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import engine

month_validator = RegexValidator(
    r"^\d{4}-(0[1-9]|1[0-2])$",
    _("Month must be in YYYY-MM format"),
)
color_validator = RegexValidator(r"^#[0-9a-fA-F]{6}$", _("Color must be #rrggbb"))
FORBIDDEN_START = ("=", "+", "-", "@")
MAX_SALARIES = 60


def validate_pile_name(value: str) -> None:
    if value.startswith(FORBIDDEN_START):
        msg = _("Pile name cannot start with = + - or @")
        raise ValidationError(msg)
    if re.search(r"[\x00-\x1f]", value):
        msg = _("Pile name contains invalid characters")
        raise ValidationError(msg)


class PlannerSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="planner_settings",
    )
    start_month = models.CharField(max_length=7, validators=[month_validator])
    salary_multiplier = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal(1),
    )


class Pile(models.Model):
    BUDGET = engine.BUDGET
    FUND = engine.FUND
    KIND_CHOICES = [(BUDGET, _("Monthly budget")), (FUND, _("Savings fund"))]
    SWEEP = engine.SWEEP
    ROLLOVER = engine.ROLLOVER
    MODE_CHOICES = [(SWEEP, _("Sweep to another pile")), (ROLLOVER, _("Rollover"))]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="piles",
    )
    name = models.CharField(max_length=24, validators=[validate_pile_name])
    color = models.CharField(
        max_length=7,
        default="#5b5bf0",
        validators=[color_validator],
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=BUDGET)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=ROLLOVER)
    cap = models.DecimalField(
        _("Rollover cap"),
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    overflow_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    target = models.DecimalField(
        _("Target"),
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_pile_name_per_user",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def to_engine(self) -> engine.Pile:
        return engine.Pile(
            name=self.name,
            kind=self.kind,
            mode=self.mode,
            cap=self.cap,
            overflow_to=self.overflow_to.name if self.overflow_to else None,
            target=self.target,
        )


class Salary(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salaries",
    )
    effective_month = models.CharField(max_length=7, validators=[month_validator])
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["-effective_month"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "effective_month"],
                name="unique_salary_month_per_user",
            ),
        ]


class PlanPeriod(models.Model):
    """A split of the salary that applies from ``effective_month`` onwards."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plan_periods",
    )
    effective_month = models.CharField(max_length=7, validators=[month_validator])
    name = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["-effective_month"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "effective_month"],
                name="unique_plan_month_per_user",
            ),
        ]


class PlanItem(models.Model):
    period = models.ForeignKey(
        PlanPeriod,
        on_delete=models.CASCADE,
        related_name="items",
    )
    pile = models.ForeignKey(Pile, on_delete=models.CASCADE, related_name="+")
    percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["period", "pile"],
                name="unique_item_per_pile_per_period",
            ),
        ]


class LogEntry(models.Model):
    SPEND, TRANSFER, SWEEP, ADJUST = "spend", "transfer", "sweep", "adjust"
    TYPE_CHOICES = [
        (SPEND, _("Spend")),
        (TRANSFER, _("Transfer")),
        (SWEEP, _("Sweep")),
        (ADJUST, _("Adjust")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="log_entries",
    )
    date = models.DateField(default=date.today)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=SPEND)
    from_pile = models.ForeignKey(
        Pile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing",
    )
    to_pile = models.ForeignKey(
        Pile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "log entries"

    @property
    def month(self) -> str:
        return f"{self.date:%Y-%m}"

    def to_engine(self) -> engine.Entry:
        return engine.Entry(
            date=self.date,
            type=self.type,
            amount=self.amount,
            from_pile=self.from_pile.name if self.from_pile else None,
            to_pile=self.to_pile.name if self.to_pile else None,
        )
