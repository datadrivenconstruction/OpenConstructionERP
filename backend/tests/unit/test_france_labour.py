# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""French labour facts live in the shared labour standards catalogue, dated and sourced.

The distinguishing cases are dates and review flags: the SMIC row starts on
1 January 2026 and is shown but not enforced while a later 2026 revision is
unconfirmed; the CIBTP rates hold for the April 2026 campaign only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core import labour_standards as ls


def test_the_smic_starts_in_2026_and_is_shown_but_not_enforced() -> None:
    assert ls.standard("FR", "minimum_wage_hourly", date(2025, 12, 31)) is None
    row = ls.standard("FR", "minimum_wage_hourly", date(2026, 1, 1))
    assert row is not None and row.value == Decimal("12.02")
    assert ls.hard_standard("FR", "minimum_wage_hourly", date(2026, 1, 1)) is None
    monthly = ls.standard("FR", "minimum_wage_monthly", date(2026, 6, 1))
    assert monthly is not None
    # 12.02 x 35 x 52 / 12 hours (151.67 rounded), the monthly SMIC at 35 hours a week.
    assert (Decimal("12.02") * Decimal(35 * 52) / 12).quantize(Decimal("0.01")) == monthly.value


def test_the_legal_week_and_the_default_overtime_premiums() -> None:
    on = date(2026, 10, 19)
    assert ls.hard_standard("FR", "legal_working_week_hours", on).value == Decimal("35")
    assert ls.hard_standard("FR", "overtime_premium_first_8_hours_pct", on).value == Decimal("25")
    assert ls.hard_standard("FR", "overtime_premium_beyond_8_hours_pct", on).value == Decimal("50")
    assert ls.hard_standard("FR", "public_holiday_days", on).value == Decimal("11")


def test_the_building_funds_hold_for_their_campaign_only() -> None:
    inside, before, after = date(2026, 10, 1), date(2026, 3, 31), date(2027, 4, 1)
    assert ls.hard_standard("FR", "btp_bad_weather_fund_pct_structural_works", inside).value == Decimal("0.68")
    assert ls.hard_standard("FR", "btp_bad_weather_fund_pct_finishing_works", inside).value == Decimal("0.13")
    for day in (before, after):
        assert ls.standard("FR", "btp_bad_weather_fund_pct_structural_works", day) is None
    leave = ls.standard("FR", "btp_paid_leave_fund_pct", inside)
    assert leave is not None and leave.value == Decimal("20.20") and leave.needs_expert_review
    assert ls.hard_standard("FR", "btp_paid_leave_fund_pct", inside) is None
    assert ls.hard_standard("FR", "btp_oppbtp_levy_pct", inside).value == Decimal("0.11")
    assert ls.standard("FR", "btp_oppbtp_levy_pct", date(2027, 1, 1)) is None


def test_the_unconfirmed_btp_overtime_quota_is_not_shipped() -> None:
    keys = {row.key for row in ls.load_standards() if row.country == "FR"}
    assert not any("quota" in key for key in keys)
