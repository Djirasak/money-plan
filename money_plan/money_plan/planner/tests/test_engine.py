from datetime import date
from decimal import Decimal as D

from money_plan.planner.engine import FUND
from money_plan.planner.engine import ROLLOVER
from money_plan.planner.engine import SWEEP
from money_plan.planner.engine import Entry
from money_plan.planner.engine import PlanRow
from money_plan.planner.engine import Pile
from money_plan.planner.engine import Salary
from money_plan.planner.engine import add_months
from money_plan.planner.engine import compute
from money_plan.planner.engine import salary_for

SALARIES = [Salary("2027-01", D(48000))]
PLAN = [PlanRow("2027-01", {"spend": D("0.55"), "free": D("0.12"), "save": D("0.33")})]


def run(piles, entries=(), end="2027-03", salaries=SALARIES, plan=PLAN, **kw):
    return compute(
        piles=piles,
        salaries=salaries,
        plan=plan,
        entries=list(entries),
        start_month="2027-01",
        end_month=end,
        **kw,
    )


def test_add_months_wraps_year():
    assert add_months("2026-11", 3) == "2027-02"
    assert add_months("2027-01", -1) == "2026-12"


def test_salary_uses_latest_effective_not_after_month():
    salaries = [Salary("2026-01", D(41000)), Salary("2027-01", D(48000))]
    assert salary_for("2026-12", salaries) == D(41000)
    assert salary_for("2027-01", salaries) == D(48000)
    assert salary_for("2025-12", salaries) == D(0)


def test_allocation_matches_screenshot():
    piles = [Pile("spend"), Pile("free"), Pile("save", kind=FUND)]
    jan = run(piles)[0]
    assert jan.piles["spend"].allocation == D(26400)
    assert jan.piles["free"].allocation == D(5760)
    assert jan.piles["save"].allocation == D(15840)


def test_rollover_unlimited_carries_everything():
    months = run([Pile("spend", mode=ROLLOVER)])
    assert months[0].piles["spend"].carry_out == D(26400)
    assert months[1].piles["spend"].carry_in == D(26400)
    assert months[1].piles["spend"].before == D(52800)


def test_rollover_cap_overflows_exactly_to_target():
    piles = [
        Pile("free", cap=D(20000), overflow_to="save"),
        Pile("save", kind=FUND),
    ]
    months = run(piles, end="2027-04")
    free = [m.piles["free"] for m in months]
    # 5,760 per month: 5760, 11520, 17280, 23040 -> capped at 20,000 in Apr
    assert free[2].carry_out == D(17280)
    assert free[3].before == D(23040)
    assert free[3].carry_out == D(20000)
    assert free[3].overflow == D(3040)
    # nothing lost, nothing duplicated: fund gets overflow next month
    total_before_apr = sum(m.piles["save"].allocation for m in months[:3])
    assert months[3].piles["save"].carry_in == total_before_apr


def test_sweep_always_zero_carry_and_moves_all_to_target():
    piles = [Pile("spend", mode=SWEEP, overflow_to="save"), Pile("save", kind=FUND)]
    months = run(piles)
    for m in months:
        assert m.piles["spend"].carry_out == 0
        assert m.piles["spend"].overflow == D(26400)
    assert months[1].piles["save"].carry_in == D(15840) + D(26400)


def test_fund_never_overflows():
    months = run([Pile("save", kind=FUND, cap=D(1), overflow_to="save")])
    assert all(m.piles["save"].overflow == 0 for m in months)
    assert months[2].piles["save"].carry_out == D(15840) * 3


def test_entries_net_and_used():
    piles = [Pile("spend"), Pile("free")]
    entries = [
        Entry(date(2027, 1, 5), "spend", D(1000), from_pile="spend"),
        Entry(date(2027, 1, 6), "transfer", D(500), "spend", "free"),
        Entry(date(2027, 1, 7), "adjust", D(2000), to_pile="free"),
        Entry(date(2027, 2, 1), "spend", D(100), from_pile="spend"),  # next month
    ]
    jan = run(piles, entries)[0]
    assert jan.piles["spend"].net == D(-1500)
    assert jan.piles["spend"].used == D(1000)
    assert jan.piles["free"].net == D(2500)
    assert jan.piles["free"].used == 0
    assert jan.piles["spend"].used_pct == (D(1000) / D(26400) * 100)


def test_negative_balance_carries_forward_without_overflow():
    piles = [Pile("spend", mode=SWEEP, overflow_to="save"), Pile("save", kind=FUND)]
    entries = [Entry(date(2027, 1, 5), "spend", D(30000), from_pile="spend")]
    months = run(piles, entries)
    assert months[0].piles["spend"].carry_out == D(-3600)
    assert months[0].piles["spend"].overflow == 0
    assert months[1].piles["spend"].carry_in == D(-3600)


def test_salary_change_mid_plan():
    salaries = [Salary("2027-01", D(48000)), Salary("2027-03", D(50000))]
    months = run([Pile("spend", mode=SWEEP)], salaries=salaries)
    assert [m.salary for m in months] == [D(48000), D(48000), D(50000)]


def test_salary_multiplier():
    assert run([Pile("spend")], salary_multiplier=D("0.6"))[0].salary == D(28800)


def test_plan_change_applies_from_effective_month():
    plan = [
        PlanRow("2027-01", {"spend": D("0.5")}),
        PlanRow("2027-02", {"spend": D("0.6")}),
    ]
    months = run([Pile("spend", mode=SWEEP)], plan=plan)
    assert [m.piles["spend"].allocation for m in months] == [
        D(24000),
        D(28800),
        D(28800),
    ]


def test_fixed_amount_allocation_on_top_of_share():
    plan = [
        PlanRow("2027-01", {"spend": D("0.5")}, {"spend": D(1000), "save": D(500)}),
    ]
    jan = run([Pile("spend"), Pile("save", kind=FUND)], plan=plan)[0]
    assert jan.piles["spend"].allocation == D(25000)
    assert jan.piles["save"].allocation == D(500)
