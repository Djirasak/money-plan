"""Pure monthly planning engine (no Django imports, easy to test).

Each month is computed from the previous one, per pile:

    before = allocation + carry_in + net      (net = money in - money out)

then the end-of-month rule of the pile decides ``carry_out`` and ``overflow``.
Overflow lands in the ``overflow_to`` pile as part of *next* month's carry-in.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)

BUDGET = "budget"
FUND = "fund"
SWEEP = "sweep"
ROLLOVER = "rollover"


@dataclass(frozen=True)
class Pile:
    name: str
    kind: str = BUDGET  # BUDGET | FUND
    mode: str = ROLLOVER  # SWEEP | ROLLOVER (budget piles only)
    cap: Decimal | None = None  # rollover cap, None = unlimited
    overflow_to: str | None = None
    target: Decimal | None = None  # goal of a fund pile


@dataclass(frozen=True)
class Salary:
    effective_month: str  # "YYYY-MM"
    amount: Decimal


@dataclass(frozen=True)
class PlanRow:
    """What each pile receives from ``effective_month`` onwards.

    A pile gets ``salary * share + fixed`` every month.
    """

    effective_month: str
    shares: dict[str, Decimal] = field(default_factory=dict)  # 0.55 = 55%
    fixed: dict[str, Decimal] = field(default_factory=dict)  # baht


@dataclass(frozen=True)
class Entry:
    date: date
    type: str  # spend | transfer | sweep | adjust
    amount: Decimal
    from_pile: str | None = None
    to_pile: str | None = None

    @property
    def month(self) -> str:
        return f"{self.date:%Y-%m}"


@dataclass
class PileMonth:
    name: str
    allocation: Decimal = ZERO
    carry_in: Decimal = ZERO
    net: Decimal = ZERO
    used: Decimal = ZERO
    before: Decimal = ZERO  # allocation + carry_in + net
    carry_out: Decimal = ZERO
    overflow: Decimal = ZERO
    overflow_to: str | None = None

    @property
    def used_pct(self) -> Decimal:
        budget = self.allocation + self.carry_in
        return (self.used / budget * 100) if budget > 0 else ZERO


@dataclass
class Month:
    month: str
    salary: Decimal
    piles: dict[str, PileMonth] = field(default_factory=dict)


def add_months(month: str, n: int) -> str:
    year, mon = map(int, month.split("-"))
    idx = year * 12 + (mon - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def salary_for(month: str, salaries: Iterable[Salary]) -> Decimal:
    """Row with the latest effective_month <= month; 0 when none applies."""
    applicable = [s for s in salaries if s.effective_month <= month]
    if not applicable:
        return ZERO
    return max(applicable, key=lambda s: s.effective_month).amount


def plan_for(month: str, plan: Iterable[PlanRow]) -> PlanRow | None:
    applicable = [p for p in plan if p.effective_month <= month]
    if not applicable:
        return None
    return max(applicable, key=lambda p: p.effective_month)


def _settle(pile: Pile, before: Decimal) -> tuple[Decimal, Decimal]:
    """End-of-month rule -> (carry_out, overflow)."""
    if pile.kind == FUND or before <= 0:
        return before, ZERO  # funds accumulate; debt carries forward
    if pile.mode == SWEEP:
        return ZERO, before
    if pile.cap is None or before <= pile.cap:
        return before, ZERO
    return pile.cap, before - pile.cap


def compute(
    *,
    piles: list[Pile],
    salaries: list[Salary],
    plan: list[PlanRow],
    entries: list[Entry],
    start_month: str,
    end_month: str,
    salary_multiplier: Decimal = Decimal(1),
) -> list[Month]:
    """Compute every month from ``start_month`` to ``end_month`` inclusive."""
    names = {p.name for p in piles}
    by_month: dict[str, list[Entry]] = {}
    for e in entries:
        by_month.setdefault(e.month, []).append(e)

    carry = {p.name: ZERO for p in piles}
    result: list[Month] = []
    month = start_month
    while month <= end_month:
        salary = salary_for(month, salaries) * salary_multiplier
        row_plan = plan_for(month, plan) or PlanRow(month)
        row = Month(month=month, salary=salary)
        incoming = {n: ZERO for n in names}

        for pile in piles:
            pm = PileMonth(name=pile.name, carry_in=carry[pile.name])
            pm.allocation = salary * row_plan.shares.get(
                pile.name,
                ZERO,
            ) + row_plan.fixed.get(pile.name, ZERO)
            for e in by_month.get(month, []):
                if e.to_pile == pile.name:
                    pm.net += e.amount
                if e.from_pile == pile.name:
                    pm.net -= e.amount
                    if e.type == "spend":
                        pm.used += e.amount
            pm.before = pm.allocation + pm.carry_in + pm.net
            pm.carry_out, pm.overflow = _settle(pile, pm.before)
            if pm.overflow and pile.overflow_to in names:
                pm.overflow_to = pile.overflow_to
                incoming[pile.overflow_to] += pm.overflow
            row.piles[pile.name] = pm

        carry = {n: row.piles[n].carry_out + incoming[n] for n in names}
        result.append(row)
        month = add_months(month, 1)
    return result
