"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the rate-freshness (re-price-due) helpers.

These live in ``app.modules.costs.service`` and are pure functions - no
database, no session - so every case here pins behaviour by passing an
explicit ``today`` reference date. They back the "flag a rate whose PRICE is
stale by date, not just by usage" feature: a rate can be applied constantly
yet still carry a unit price fixed years ago, and price freshness catches that
independently of the usage-ledger certainty badge.

Run:
    cd backend
    python -m pytest tests/unit/test_rate_freshness.py -v --tb=short
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.costs.service import (
    PRICE_DEFAULT_ANNUAL_ESCALATION_PCT,
    PRICE_STALENESS_HORIZON_DAYS,
    classify_price_freshness,
    escalated_reprice_value,
    is_reprice_due,
    price_age_days,
    price_freshness,
)

# A fixed anchor so the date math is deterministic regardless of wall clock.
AS_OF = date(2025, 1, 1)


def _at_age(days: int) -> date:
    """Reference ``today`` that is exactly ``days`` after ``AS_OF``."""
    return AS_OF + timedelta(days=days)


# ── price_age_days ─────────────────────────────────────────────────────────


def test_price_age_days_counts_whole_days() -> None:
    assert price_age_days(AS_OF, today=_at_age(10)) == 10


def test_price_age_days_none_when_no_date() -> None:
    assert price_age_days(None, today=_at_age(10)) is None
    assert price_age_days("", today=_at_age(10)) is None


def test_price_age_days_future_date_clamps_to_zero() -> None:
    # A price dated in the future is never negative age.
    assert price_age_days(_at_age(30), today=AS_OF) == 0


def test_price_age_days_accepts_iso_string() -> None:
    assert price_age_days("2025-01-01", today=date(2025, 2, 1)) == 31


def test_price_age_days_ignores_junk_date() -> None:
    assert price_age_days("not-a-date", today=_at_age(10)) is None


# ── is_reprice_due ─────────────────────────────────────────────────────────


def test_is_reprice_due_below_horizon_false() -> None:
    assert is_reprice_due(AS_OF, today=_at_age(364)) is False


def test_is_reprice_due_at_and_past_horizon_true() -> None:
    assert is_reprice_due(AS_OF, today=_at_age(365)) is True
    assert is_reprice_due(AS_OF, today=_at_age(400)) is True


def test_is_reprice_due_none_date_false() -> None:
    assert is_reprice_due(None, today=_at_age(4000)) is False


def test_is_reprice_due_horizon_off_when_non_positive() -> None:
    # A non-positive horizon switches the check off even for an ancient price.
    assert is_reprice_due(AS_OF, horizon_days=0, today=_at_age(4000)) is False


def test_is_reprice_due_custom_horizon() -> None:
    assert is_reprice_due(AS_OF, horizon_days=30, today=_at_age(31)) is True
    assert is_reprice_due(AS_OF, horizon_days=30, today=_at_age(29)) is False


def test_is_reprice_due_ignores_usage_frequency() -> None:
    # The helper takes only a date - by construction it cannot look at usage,
    # which is the whole point: a stale price is flagged however busy the rate.
    assert is_reprice_due(AS_OF, today=_at_age(500)) is True


# ── classify_price_freshness ───────────────────────────────────────────────


def test_classify_none_when_no_date() -> None:
    assert classify_price_freshness(None, today=_at_age(10)) is None


def test_classify_green_within_warn() -> None:
    # Default horizon 365, warn fraction 0.75 -> warn at 273 days.
    assert classify_price_freshness(AS_OF, today=_at_age(100)) == "green"
    assert classify_price_freshness(AS_OF, today=_at_age(272)) == "green"


def test_classify_yellow_between_warn_and_horizon() -> None:
    assert classify_price_freshness(AS_OF, today=_at_age(273)) == "yellow"
    assert classify_price_freshness(AS_OF, today=_at_age(364)) == "yellow"


def test_classify_red_at_and_past_horizon() -> None:
    assert classify_price_freshness(AS_OF, today=_at_age(365)) == "red"
    assert classify_price_freshness(AS_OF, today=_at_age(900)) == "red"


def test_classify_none_when_horizon_off() -> None:
    assert classify_price_freshness(AS_OF, horizon_days=0, today=_at_age(900)) is None


def test_classify_custom_horizon_and_warn() -> None:
    # horizon 100, warn 0.5 -> yellow from 50, red from 100.
    assert classify_price_freshness(AS_OF, horizon_days=100, warn_fraction=0.5, today=_at_age(40)) == "green"
    assert classify_price_freshness(AS_OF, horizon_days=100, warn_fraction=0.5, today=_at_age(60)) == "yellow"
    assert classify_price_freshness(AS_OF, horizon_days=100, warn_fraction=0.5, today=_at_age(100)) == "red"


# ── escalated_reprice_value ────────────────────────────────────────────────


def test_escalate_one_full_year_compounds_once() -> None:
    # 100 at +3 %/yr over exactly one year -> 103.
    got = escalated_reprice_value("100", AS_OF, annual_pct="3", today=_at_age(365))
    assert got == Decimal("103")


def test_escalate_two_full_years_compounds() -> None:
    # 100 * 1.03^2 = 106.09.
    got = escalated_reprice_value("100", AS_OF, annual_pct="3", today=_at_age(730))
    assert got == Decimal("106.09")


def test_escalate_partial_year_is_prorated_linearly() -> None:
    # 0 full years + 182/365 of a year at 3 %: 100 * (1 + 0.03 * 182/365).
    got = escalated_reprice_value("100", AS_OF, annual_pct="3", today=_at_age(182))
    assert got == Decimal("101.4959")


def test_escalate_zero_pct_returns_same_rate() -> None:
    got = escalated_reprice_value("100", AS_OF, annual_pct="0", today=_at_age(400))
    assert got == Decimal("100")


def test_escalate_uses_decimal_default_pct() -> None:
    # Default is a Decimal, and one year at the default lands above the rate.
    assert isinstance(PRICE_DEFAULT_ANNUAL_ESCALATION_PCT, Decimal)
    got = escalated_reprice_value("200", AS_OF, today=_at_age(365))
    assert got is not None and got > Decimal("200")


def test_escalate_none_when_no_date() -> None:
    assert escalated_reprice_value("100", None, today=_at_age(400)) is None


def test_escalate_none_when_age_zero_or_future() -> None:
    assert escalated_reprice_value("100", AS_OF, today=AS_OF) is None
    assert escalated_reprice_value("100", _at_age(30), today=AS_OF) is None


def test_escalate_none_for_missing_or_bad_rate() -> None:
    assert escalated_reprice_value(None, AS_OF, today=_at_age(400)) is None
    assert escalated_reprice_value("0", AS_OF, today=_at_age(400)) is None
    assert escalated_reprice_value("-5", AS_OF, today=_at_age(400)) is None
    assert escalated_reprice_value("abc", AS_OF, today=_at_age(400)) is None


def test_escalate_quantizes_to_four_places() -> None:
    got = escalated_reprice_value("100", AS_OF, annual_pct="3", today=_at_age(365))
    assert got is not None
    # Quantised to 4 dp, matching the usage ledger's Numeric(18, 4).
    assert got.as_tuple().exponent == -4


# ── price_freshness aggregator ─────────────────────────────────────────────


def test_price_freshness_no_date_is_all_neutral() -> None:
    out = price_freshness(None, "100", today=_at_age(4000))
    assert out["price_as_of"] is None
    assert out["price_age_days"] is None
    assert out["reprice_due"] is False
    assert out["price_freshness_band"] is None
    assert out["suggested_reprice_value"] is None
    # The horizon in force is still reported so the UI can explain the rule.
    assert out["staleness_horizon_days"] == PRICE_STALENESS_HORIZON_DAYS


def test_price_freshness_fresh_has_no_offer() -> None:
    out = price_freshness(AS_OF, "100", today=_at_age(30))
    assert out["price_age_days"] == 30
    assert out["reprice_due"] is False
    assert out["price_freshness_band"] == "green"
    # A fresh price never carries a one-click reprice offer.
    assert out["suggested_reprice_value"] is None


def test_price_freshness_due_offers_escalated_value() -> None:
    out = price_freshness(AS_OF, "100", annual_pct="3", today=_at_age(365))
    assert out["reprice_due"] is True
    assert out["price_freshness_band"] == "red"
    assert out["price_as_of"] == AS_OF
    assert out["suggested_reprice_value"] == Decimal("103")


def test_price_freshness_due_without_rate_has_no_offer() -> None:
    # Flag is raised even with no rate to escalate; the offer is just absent.
    out = price_freshness(AS_OF, None, today=_at_age(500))
    assert out["reprice_due"] is True
    assert out["price_freshness_band"] == "red"
    assert out["suggested_reprice_value"] is None


def test_price_freshness_echoes_iso_string_date() -> None:
    out = price_freshness("2025-01-01", "100", today=_at_age(10))
    assert out["price_as_of"] == AS_OF
    assert out["price_age_days"] == 10
