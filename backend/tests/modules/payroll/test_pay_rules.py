"""Overtime, night, weekend, holiday and per diem rules per country profile."""

from datetime import date, datetime
from decimal import Decimal

from app.modules.payroll import pay_rules as pr


def _line(day, hours, start=None, end=None, rate="20", emp="e1"):
    return pr.WorkLine(
        employee_id=emp,
        employee_name=emp.upper(),
        work_date=day,
        hours=Decimal(str(hours)),
        rate=Decimal(rate),
        cost_code="C1",
        started_at=start,
        ended_at=end,
    )


def _by_type(rows):
    out = {}
    for r in rows:
        out[r.pay_type] = out.get(r.pay_type, Decimal("0")) + r.hours
    return out


def test_every_profile_loads_and_neutral_is_flat():
    profiles = pr.load_profiles()
    assert {"neutral", "de_brtv_bau", "gb_cijc_cis", "us_flsa_prevailing", "au_bcgoa", "ae_labour_law"} <= set(profiles)
    rows = pr.classify([_line(date(2026, 10, 5), 12)], pr.profile_for("neutral"))
    assert _by_type(rows) == {"regular": Decimal("12")}


def test_de_daily_overtime_night_and_sunday():
    de = pr.profile_for(country="DE")
    mon, sun = date(2026, 10, 5), date(2026, 10, 11)
    rows = pr.classify([_line(mon, 10), _line(sun, 4, datetime(2026, 10, 11, 21), datetime(2026, 10, 12, 1))], de)
    t = _by_type(rows)
    assert t["regular"] == 8
    assert t["overtime"] == 2
    assert t["sunday"] == 4
    assert t["night_premium"] == 4
    ot = next(r for r in rows if r.pay_type == "overtime")
    assert ot.amount == Decimal("50.00")  # 2 h x 20 x 1.25
    night = next(r for r in rows if r.pay_type == "night_premium")
    assert night.amount == Decimal("16.00")  # 4 h x 20 x 0.20


def test_us_weekly_overtime_over_40():
    us = pr.profile_for(country="US")
    week = [_line(date(2026, 10, 5 + i), 9) for i in range(5)]  # 45 h Monday to Friday
    assert _by_type(pr.classify(week, us)) == {"regular": Decimal("40"), "overtime_weekly": Decimal("5")}


def test_au_tiers_and_per_diem():
    au = pr.profile_for(country="AU")
    rows = pr.classify([_line(date(2026, 10, 6), 11)], au)
    t = _by_type(rows)
    assert t["regular"] == 8
    assert t["overtime"] == 3
    assert sorted(r.multiplier for r in rows if r.pay_type == "overtime") == [Decimal("1.5"), Decimal("2.0")]
    assert any(r.pay_type == "per_diem" and r.amount == Decimal("54.00") for r in rows)


def test_gcc_holiday_multiplier():
    ae = pr.profile_for(country="AE")
    day = date(2026, 12, 2)
    rows = pr.classify([_line(day, 8)], ae, holidays=[day])
    assert _by_type(rows) == {"holiday": Decimal("8")}
    assert rows[0].amount == Decimal("240.00")


def test_gb_flags_cis_and_weekly_overtime():
    gb = pr.profile_for(country="GB")
    assert gb["flags"]["cis_deductions"] is True
    t = _by_type(pr.classify([_line(date(2026, 10, 5 + i), 8) for i in range(5)], gb))
    assert t == {"regular": Decimal("39"), "overtime_weekly": Decimal("1")}


def test_night_window_crossing_midnight():
    window = {"start": "22:00", "end": "04:00"}
    assert pr.night_hours(datetime(2026, 1, 1, 20), datetime(2026, 1, 2, 6), window) == Decimal("6.00")
    assert pr.night_hours(datetime(2026, 1, 1, 8), datetime(2026, 1, 1, 16), window) == 0


def test_max_hours_breaches_and_burden():
    de = pr.profile_for(country="DE")
    lines = [_line(date(2026, 10, 5), 11)] + [_line(date(2026, 10, 6 + i), 10) for i in range(4)]
    breaches = pr.max_hours_breaches(lines, de)
    assert {b["scope"] for b in breaches} == {"day", "week"}
    assert pr.burden(Decimal("1000"), de) == Decimal("380.00")
