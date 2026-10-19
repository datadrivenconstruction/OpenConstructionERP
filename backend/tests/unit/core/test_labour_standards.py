# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory labour facts are sourced, dated data, and unconfirmed ones cannot be enforced.

The catalogue is ``app/core/country_data/labour_standards.json``. The point of
the split between :func:`standard` and :func:`hard_standard` is that a fact the
research could not confirm (Egypt's 35% and 70% overtime premiums, whose
article number was not found) is still visible and editable, but a rule that
enforces something must ask for a confirmed one and gets ``None`` instead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core import labour_standards as ls
from app.modules.labor_rates.seed import DEFAULT_RATE_TEMPLATES


@pytest.fixture(autouse=True)
def _fresh():
    ls.load_standards.cache_clear()
    yield
    ls.load_standards.cache_clear()


@pytest.mark.unit
def test_every_shipped_row_is_sourced_and_dated() -> None:
    rows = ls.load_standards()
    assert rows, "the catalogue is empty; this test is checking nothing"
    for row in rows:
        assert row.source and row.source_url.startswith("https://"), row.key
        assert row.confidence in {"H", "M", "L"}
        if row.confidence == "L":
            assert row.needs_expert_review, f"{row.key}: a low-confidence fact must be flagged for review"


@pytest.mark.unit
def test_the_egyptian_minimum_wage_starts_on_1_march_2025() -> None:
    assert ls.standard("EG", "minimum_wage_monthly", date(2025, 2, 28)) is None
    wage = ls.hard_standard("EG", "minimum_wage_monthly", date(2025, 3, 1))
    assert wage is not None
    assert wage.value == Decimal("7000")
    assert wage.unit == "EGP/month"


@pytest.mark.unit
def test_unconfirmed_overtime_premiums_are_visible_but_not_enforceable() -> None:
    on = date(2026, 1, 1)
    for key, pct in (("overtime_premium_day_pct", "35"), ("overtime_premium_night_pct", "70")):
        row = ls.standard("EG", key, on)
        assert row is not None and row.value == Decimal(pct)
        assert row.needs_expert_review is True
        assert ls.hard_standard("EG", key, on) is None


@pytest.mark.unit
def test_labour_law_facts_start_with_the_law() -> None:
    assert ls.standard("EG", "max_hours_per_week", date(2025, 8, 31)) is None
    assert ls.hard_standard("EG", "max_hours_per_week", date(2025, 9, 1)).value == Decimal("48")
    assert ls.hard_standard("EG", "max_hours_per_day", date(2025, 9, 1)).value == Decimal("8")
    assert ls.hard_standard("EG", "annual_leave_days", date(2026, 1, 1)).value == Decimal("21")


@pytest.mark.unit
def test_the_validator_refuses_overlapping_windows_and_bad_rows() -> None:
    good = {
        "country": "EG",
        "key": "k",
        "value": "1",
        "unit": "days",
        "effective_from": "2025-01-01",
        "effective_to": None,
        "source": "s",
        "source_url": "https://example.org/",
        "confidence": "H",
        "needs_expert_review": False,
    }
    assert ls.parse_standards([good])
    later = {**good, "effective_from": "2025-06-01"}
    with pytest.raises(ValueError):
        ls.parse_standards([good, later])
    closed = {**good, "effective_to": "2025-05-31"}
    assert len(ls.parse_standards([closed, later])) == 2
    for broken in (
        {**good, "value": "seven"},
        {**good, "source_url": "ftp://x"},
        {**good, "confidence": "L"},
        {**good, "effective_to": "2024-01-01"},
        {k: v for k, v in good.items() if k != "unit"},
    ):
        with pytest.raises(ValueError):
            ls.parse_standards([broken])


@pytest.mark.unit
def test_the_egyptian_schedule_day_fits_the_statutory_limits() -> None:
    """The schedule's Egyptian day must fit inside the statutory day and week."""
    from app.modules.schedule.service import get_work_calendar

    cal = get_work_calendar("EG")
    on = date(2026, 1, 1)
    assert Decimal(cal["hours_per_day"]) <= ls.hard_standard("EG", "max_hours_per_day", on).value
    week = Decimal(cal["hours_per_day"]) * len(cal["work_days"])
    assert week <= ls.hard_standard("EG", "max_hours_per_week", on).value


_EGP = [row for row in DEFAULT_RATE_TEMPLATES if row["currency"] == "EGP"]


@pytest.mark.unit
def test_there_are_egyptian_rate_templates() -> None:
    assert len(_EGP) >= 2


@pytest.mark.unit
@pytest.mark.parametrize("row", _EGP, ids=lambda r: r["name"])
def test_egyptian_templates_pay_at_least_the_minimum_wage(row) -> None:
    on = date(2026, 1, 1)
    monthly = ls.hard_standard("EG", "minimum_wage_monthly", on).value
    weekly_hours = ls.hard_standard("EG", "max_hours_per_week", on).value
    # The most hours a month can lawfully hold is the floor's worst case: the
    # same monthly minimum spread over more hours is the lowest hourly figure.
    hourly_floor = monthly / (weekly_hours * 52 / 12)
    assert row["base_wage"] >= hourly_floor


@pytest.mark.unit
@pytest.mark.parametrize("row", _EGP, ids=lambda r: r["name"])
def test_egyptian_templates_take_their_on_costs_from_the_catalogue(row) -> None:
    on = date(2026, 1, 1)
    components = {label: (kind, value) for label, kind, value in row["components"]}
    employer = ls.hard_standard("EG", "employer_social_insurance_pct", on).value
    assert any(kind == "percentage" and value == employer for kind, value in components.values())

    leave = ls.hard_standard("EG", "annual_leave_days", on).value
    holidays = ls.hard_standard("EG", "public_holiday_days", on).value
    productive = Decimal(5 * 52) - leave - holidays
    provision = (leave + holidays) / productive * 100
    assert any(
        kind == "percentage" and value == provision.quantize(Decimal("0.01")) for kind, value in components.values()
    )
