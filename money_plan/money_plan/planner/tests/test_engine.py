from datetime import date
from decimal import Decimal as D

from money_plan.planner.engine import FUND
from money_plan.planner.engine import GTE
from money_plan.planner.engine import LT
from money_plan.planner.engine import Condition
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


def two_piles():
    return [Pile("spend", mode=SWEEP, overflow_to="save"), Pile("save", kind=FUND)]


def test_plan_switches_when_a_pile_reaches_an_amount():
    plan = [
        PlanRow("2027-01", {"spend": D("0.5"), "save": D("0.5")}, key="base"),
        PlanRow(
            "2027-01",
            {"spend": D("0.9"), "save": D("0.1")},
            condition=Condition("save", GTE, D(20000)),
            key="rich",
        ),
    ]
    months = run(two_piles(), end="2027-04", plan=plan)
    # January: save has 0 -> base. It ends with 24,000 and the swept 24,000 arrives
    # in February, so save starts February at 48,000 >= 20,000 -> rich from then on.
    assert [m.plan_key for m in months] == ["base", "rich", "rich", "rich"]
    assert months[1].piles["spend"].allocation == D(43200)  # 90% of 48,000


def test_plan_applies_only_while_a_pile_is_below_an_amount():
    plan = [
        PlanRow("2027-01", {"spend": D(1)}, key="normal"),
        PlanRow(
            "2027-01",
            {"spend": D(1)},
            condition=Condition("spend", LT, D(10000)),
            key="lean",
        ),
    ]
    months = run([Pile("spend")], end="2027-02", plan=plan)
    # January starts at 0 (< 10,000) -> lean. 48,000 carries over, so February is
    # no longer below the threshold and the older plan takes over again.
    assert [m.plan_key for m in months] == ["lean", "normal"]


def test_condition_uses_the_balance_at_the_start_of_the_month():
    plan = [
        PlanRow("2027-01", {"spend": D(1)}, key="base"),
        PlanRow("2027-01", {"spend": D(1)}, condition=Condition("spend", GTE, D(1)), key="cond"),
    ]
    months = run([Pile("spend")], end="2027-02", plan=plan)
    assert months[0].plan_key == "base"  # nothing carried in yet
    assert months[1].plan_key == "cond"  # 48,000 carried in


def test_newest_start_month_wins_then_later_row_on_a_tie():
    plan = [
        PlanRow("2027-01", {"spend": D(1)}, key="a"),
        PlanRow("2027-02", {"spend": D(1)}, key="b"),
        PlanRow("2027-02", {"spend": D(1)}, key="c"),
    ]
    months = run([Pile("spend")], end="2027-03", plan=plan)
    assert [m.plan_key for m in months] == ["a", "c", "c"]


def test_unmet_condition_falls_back_to_the_next_older_plan():
    plan = [
        PlanRow("2027-01", {"spend": D(1)}, key="old"),
        PlanRow("2027-02", {"spend": D(1)}, condition=Condition("spend", GTE, D(10**9)), key="never"),
    ]
    months = run([Pile("spend")], end="2027-03", plan=plan)
    assert [m.plan_key for m in months] == ["old", "old", "old"]


def test_no_applicable_plan_means_no_allocation():
    plan = [PlanRow("2027-02", {"spend": D(1)}, key="later")]
    months = run([Pile("spend")], end="2027-02", plan=plan)
    assert months[0].plan_key == "" and months[0].piles["spend"].allocation == 0


def test_target_follows_the_salary():
    pile = Pile("save", kind=FUND, target_percent=D(60), target_months=6)
    assert pile.target_for(D(48000)) == D(172800)  # 60% * 48,000 * 6
    assert pile.target_for(D(50000)) == D(180000)
    assert Pile("x", target=D(1000)).target_for(D(50000)) == D(1000)  # fixed stays fixed
    assert Pile("y").target_for(D(50000)) is None


def test_reserve_plan_returns_when_a_raise_moves_the_target():
    """Build the reserve to 60% x salary x 6, go back to normal, and resume after a raise."""
    save = Pile("save", kind=FUND, target_percent=D(60), target_months=1)
    spend = Pile("spend")  # keeps its own money; only the reserve plan feeds "save"
    reserve_plan = PlanRow(
        "2027-01",
        {"save": D(1)},
        condition=Condition("save", LT, use_target=True),
        key="reserve",
    )
    normal = PlanRow("2027-01", {"spend": D(1)}, key="normal")
    salaries = [Salary("2027-01", D(10000)), Salary("2027-04", D(20000))]
    months = run(
        [spend, save],
        end="2027-05",
        salaries=salaries,
        plan=[normal, reserve_plan],
    )
    # target = 60% of salary: 6,000 until March, 12,000 from April.
    assert [m.piles["save"].target for m in months] == [D(6000)] * 3 + [D(12000)] * 2
    # Jan: 0 < 6,000 -> reserve (+10,000). Feb/Mar: 10,000 >= 6,000 -> normal.
    # Apr: the raise lifts the target to 12,000 > 10,000 -> reserve again (+20,000).
    # May: 30,000 >= 12,000 -> normal.
    assert [m.plan_key for m in months] == ["reserve", "normal", "normal", "reserve", "normal"]


def test_use_target_without_a_target_falls_back_to_the_amount():
    plan = [
        PlanRow("2027-01", {"spend": D(1)}, key="base"),
        PlanRow(
            "2027-01",
            {"spend": D(1)},
            condition=Condition("spend", GTE, D(1), use_target=True),
            key="cond",
        ),
    ]
    months = run([Pile("spend")], end="2027-02", plan=plan)
    assert [m.plan_key for m in months] == ["base", "cond"]  # amount 1 is used
