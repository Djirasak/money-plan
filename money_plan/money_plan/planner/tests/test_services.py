from money_plan.planner import services


def test_window_covers_three_years_ahead_of_today(monkeypatch):
    monkeypatch.setattr(services, "current_month", lambda: "2026-10")
    months = services.month_window("2026-10")
    assert months[0] == "2026-10"
    assert months[-1] == "2029-10"
    assert len(months) == 37


def test_window_from_a_past_start_still_reaches_three_years_past_today(monkeypatch):
    monkeypatch.setattr(services, "current_month", lambda: "2026-10")
    months = services.month_window("2025-01")
    assert months[0] == "2025-01"
    assert months[-1] == "2029-10"


def test_window_from_a_future_start_is_measured_from_the_start(monkeypatch):
    monkeypatch.setattr(services, "current_month", lambda: "2026-10")
    months = services.month_window("2027-06")
    assert months[0] == "2027-06"
    assert months[-1] == "2030-06"


def test_window_has_no_gaps_or_duplicates(monkeypatch):
    monkeypatch.setattr(services, "current_month", lambda: "2026-12")
    months = services.month_window("2025-11")
    assert months == sorted(set(months))
    assert len(months) == 50  # 2025-11 .. 2029-12
