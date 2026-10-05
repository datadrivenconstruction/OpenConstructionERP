# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An instalment tied to a schedule milestone moves when the schedule does.

And the plan as a whole is checked against the statutory ceilings on what a
consumer may be asked to pay before work starts, where one is recorded.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.contracts.payment_plan import (
    DEPOSIT_LIMITS,
    check_deposit,
    client_status,
    deposit_limit_for,
    forecast_dates,
)

PLANNED = date(2026, 11, 2)
SLIPPED = date(2026, 11, 16)
REACHED = date(2026, 11, 20)


# ── Forecast ──────────────────────────────────────────────────────────────


def test_a_linked_milestone_follows_the_schedule_not_the_contract():
    f = forecast_dates(trigger="completion", planned_date=PLANNED, activity_finish=SLIPPED, reached_on=None)
    assert f.reached == SLIPPED
    assert f.due == SLIPPED


def test_a_reached_milestone_counts_from_the_day_it_was_reached():
    f = forecast_dates(trigger="completion", planned_date=PLANNED, activity_finish=SLIPPED, reached_on=REACHED)
    assert f.reached == REACHED


def test_a_date_trigger_keeps_the_contract_date_whatever_the_schedule_says():
    f = forecast_dates(trigger="date", planned_date=PLANNED, activity_finish=SLIPPED, reached_on=None)
    assert f.reached == PLANNED


def test_an_unlinked_milestone_falls_back_to_its_planned_date():
    f = forecast_dates(trigger="completion", planned_date=PLANNED, activity_finish=None, reached_on=None)
    assert f.reached == PLANNED


def test_lag_and_payment_terms_add_up():
    f = forecast_dates(
        trigger="completion",
        planned_date=None,
        activity_finish=SLIPPED,
        reached_on=None,
        lag_days=3,
        terms_days=14,
    )
    assert f.reached == date(2026, 11, 19)
    assert f.due == date(2026, 12, 3)


def test_no_date_from_anywhere_forecasts_nothing():
    f = forecast_dates(trigger="approval", planned_date=None, activity_finish=None, reached_on=None, terms_days=30)
    assert f.reached is None
    assert f.due is None


def test_negative_offsets_never_pull_a_date_forward():
    f = forecast_dates(
        trigger="date", planned_date=PLANNED, activity_finish=None, reached_on=None, lag_days=-5, terms_days=-5
    )
    assert f.reached == f.due == PLANNED


# ── What the client sees ──────────────────────────────────────────────────


TODAY = date(2026, 11, 10)


@pytest.mark.parametrize(
    ("status", "due", "expected"),
    [
        # Nothing is owed before the work is done, however late the schedule runs.
        ("pending", date(2026, 11, 1), "upcoming"),
        ("pending", None, "upcoming"),
        ("reached", date(2026, 11, 20), "due"),
        ("reached", date(2026, 11, 9), "overdue"),
        ("invoiced", date(2026, 11, 10), "invoiced"),
        ("invoiced", date(2026, 11, 9), "overdue"),
        ("invoiced", None, "invoiced"),
        ("paid", date(2026, 10, 1), "paid"),
        ("something_new", None, "upcoming"),
    ],
)
def test_the_client_status(status, due, expected):
    assert client_status(status, due, TODAY) == expected


# ── Statutory deposit ceilings ────────────────────────────────────────────


def test_california_takes_the_lesser_of_a_thousand_dollars_and_ten_percent():
    ca = deposit_limit_for("us-ca")
    assert ca is not None
    # Ten percent is the lower figure on a small job ...
    assert ca.ceiling(Decimal("8000")) == Decimal("800.00")
    # ... and the thousand dollars on anything above ten thousand.
    assert ca.ceiling(Decimal("250000")) == Decimal("1000")


def test_california_over_the_cap_is_reported_with_its_numbers():
    ca = deposit_limit_for("US-CA")
    result = check_deposit(ca, price=Decimal("250000"), deposit=Decimal("25000"), currency="usd")
    assert result.outcome == "over"
    assert result.ceiling == Decimal("1000")
    assert result.deposit == Decimal("25000")
    assert check_deposit(ca, price=Decimal("250000"), deposit=Decimal("1000"), currency="USD").outcome == "within"


def test_california_leaves_a_contract_of_five_hundred_dollars_or_less_alone():
    ca = deposit_limit_for("US-CA")
    assert check_deposit(ca, price=Decimal("500"), deposit=Decimal("500"), currency="USD").outcome == "below_threshold"


def test_a_contract_in_another_currency_is_not_converted():
    ca = deposit_limit_for("US-CA")
    assert check_deposit(ca, price=Decimal("250000"), deposit=Decimal("25000"), currency="EUR").outcome == (
        "other_currency"
    )


def test_exactly_one_third_is_within_a_one_third_cap():
    md = deposit_limit_for("US-MD")
    assert md.ceiling(Decimal("30000")) == Decimal("10000.00")
    assert check_deposit(md, price=Decimal("30000"), deposit=Decimal("10000"), currency="USD").outcome == "within"
    assert check_deposit(md, price=Decimal("30000"), deposit=Decimal("10000.01"), currency="USD").outcome == "over"


def test_victoria_lowers_the_rate_from_twenty_thousand_dollars():
    vic = deposit_limit_for("AU-VIC")
    assert vic.ceiling(Decimal("19999")) == Decimal("1999.90")
    assert vic.ceiling(Decimal("20000")) == Decimal("1000.00")


def test_a_place_without_a_recorded_limit_has_none():
    assert deposit_limit_for("US-TX") is None
    assert deposit_limit_for("") is None
    assert deposit_limit_for(None) is None


def test_every_limit_says_where_it_comes_from_and_that_nobody_has_signed_it_off():
    seen: set[str] = set()
    for limit in DEPOSIT_LIMITS:
        assert limit.jurisdiction not in seen, limit.jurisdiction
        seen.add(limit.jurisdiction)
        assert limit.reference and limit.source_url.startswith("https://")
        assert limit.checked_on
        assert limit.percent is not None or limit.amount is not None or limit.tiers
        # Research, not legal advice: flipping this is a lawyer's call.
        assert limit.verified is False
