# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure change-driver (Pareto) analytics engine.

Stdlib + pytest only; cost is asserted as exact Decimal, never float. Runs on
the local Python 3.11 runner like the impact and cycle-time engine tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.change_drivers import (
    PARTY_CLIENT,
    PARTY_CONTRACTOR,
    PARTY_DESIGNER,
    PARTY_EXTERNAL,
    PARTY_UNCLASSIFIED,
    SOURCE_CHANGE_ORDER,
    SOURCE_DISRUPTION_CLAIM,
    SOURCE_EOT_CLAIM,
    SOURCE_RISK,
    UNSPECIFIED_CAUSE,
    DriverRecord,
    build_driver_analytics,
    normalize_cause,
    responsible_party_for,
)


def _rec(
    cause: str,
    cost: str,
    *,
    source: str = SOURCE_CHANGE_ORDER,
    currency: str = "EUR",
    month: str = "2026-06",
) -> DriverRecord:
    return DriverRecord(source=source, cause=cause, cost=Decimal(cost), currency=currency, month=month)


# --------------------------------------------------------------------------
# normalize_cause
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Design Error", "design_error"),
        ("design-error", "design_error"),
        ("  Client   Request  ", "client_request"),
        ("", UNSPECIFIED_CAUSE),
        ("   ", UNSPECIFIED_CAUSE),
        (None, UNSPECIFIED_CAUSE),
    ],
)
def test_normalize_cause(raw: str | None, expected: str) -> None:
    assert normalize_cause(raw) == expected


def test_normalize_cause_truncates_long_free_text() -> None:
    assert len(normalize_cause("word " * 50)) == 80


# --------------------------------------------------------------------------
# responsible_party_for: fault allocation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "cause", "party"),
    [
        (SOURCE_CHANGE_ORDER, "client_request", PARTY_CLIENT),
        (SOURCE_CHANGE_ORDER, "design_error", PARTY_DESIGNER),
        (SOURCE_CHANGE_ORDER, "value_engineering", PARTY_CONTRACTOR),
        (SOURCE_CHANGE_ORDER, "differing_site_condition", PARTY_EXTERNAL),
        (SOURCE_CHANGE_ORDER, "mystery", PARTY_UNCLASSIFIED),
        (SOURCE_EOT_CLAIM, "employer", PARTY_CLIENT),
        (SOURCE_EOT_CLAIM, "contractor", PARTY_CONTRACTOR),
        (SOURCE_EOT_CLAIM, "neutral", PARTY_EXTERNAL),
        (SOURCE_DISRUPTION_CLAIM, "anything", PARTY_UNCLASSIFIED),
        (SOURCE_RISK, "technical", PARTY_UNCLASSIFIED),
    ],
)
def test_responsible_party_for(source: str, cause: str, party: str) -> None:
    assert responsible_party_for(source, cause) == party


# --------------------------------------------------------------------------
# Empty
# --------------------------------------------------------------------------


def test_empty_analytics() -> None:
    analytics = build_driver_analytics([])
    assert analytics.total_count == 0
    assert analytics.total_cost == Decimal("0")
    assert analytics.primary_currency == ""
    assert analytics.by_cause == []
    assert analytics.by_party == []
    assert analytics.by_currency == []
    assert analytics.trend == []


# --------------------------------------------------------------------------
# Pareto by cause: ranking, exact cost, cumulative %
# --------------------------------------------------------------------------


def test_pareto_by_cause_ranks_and_accumulates() -> None:
    analytics = build_driver_analytics(
        [
            _rec("design_error", "6000"),
            _rec("design_error", "0"),
            _rec("client_request", "3000"),
            _rec("weather", "1000"),
        ]
    )
    assert analytics.total_count == 4
    assert analytics.total_cost == Decimal("10000")

    causes = analytics.by_cause
    assert [r.key for r in causes] == ["design_error", "client_request", "weather"]

    design = causes[0]
    assert design.count == 2
    assert design.cost == Decimal("6000")
    assert isinstance(design.cost, Decimal)
    assert design.cost_pct == 60.0
    assert design.cumulative_pct == 60.0
    # Cumulative climbs monotonically to 100 on the last row.
    assert causes[1].cumulative_pct == 90.0
    assert causes[2].cumulative_pct == 100.0


def test_pareto_falls_back_to_count_when_no_cost() -> None:
    # Only time-based extension claims: no cost anywhere, so the Pareto ranks
    # and accumulates by count instead.
    analytics = build_driver_analytics(
        [
            _rec("employer", "0", source=SOURCE_EOT_CLAIM, currency=""),
            _rec("employer", "0", source=SOURCE_EOT_CLAIM, currency=""),
            _rec("contractor", "0", source=SOURCE_EOT_CLAIM, currency=""),
        ]
    )
    assert analytics.total_cost == Decimal("0")
    causes = {r.key: r for r in analytics.by_cause}
    assert causes["employer"].count == 2
    assert causes["employer"].cost_pct == pytest.approx(66.67, abs=0.01)
    assert causes["employer"].cumulative_pct == pytest.approx(66.67, abs=0.01)
    assert causes["contractor"].cumulative_pct == 100.0


# --------------------------------------------------------------------------
# Pareto by responsible party (fault rollup of the cause taxonomy)
# --------------------------------------------------------------------------


def test_pareto_by_party_rolls_up_fault() -> None:
    analytics = build_driver_analytics(
        [
            _rec("design_error", "5000"),  # designer
            _rec("client_request", "2000"),  # client
            _rec("employer", "0", source=SOURCE_EOT_CLAIM, currency="EUR"),  # client
            _rec("technical", "1000", source=SOURCE_RISK),  # unclassified
        ]
    )
    parties = {r.key: r for r in analytics.by_party}
    assert parties[PARTY_DESIGNER].cost == Decimal("5000")
    assert parties[PARTY_CLIENT].count == 2  # client_request + employer EOT
    assert parties[PARTY_CLIENT].cost == Decimal("2000")
    assert parties[PARTY_UNCLASSIFIED].cost == Decimal("1000")


# --------------------------------------------------------------------------
# Currency handling: never blended, primary named
# --------------------------------------------------------------------------


def test_by_currency_never_blended_and_primary_named() -> None:
    analytics = build_driver_analytics(
        [
            _rec("a", "5000", currency="GBP"),
            _rec("b", "100", currency="EUR"),
            _rec("c", "200", currency="USD"),
        ]
    )
    by_cur = {c.currency: c for c in analytics.by_currency}
    assert by_cur["GBP"].cost == Decimal("5000")
    assert by_cur["EUR"].cost == Decimal("100")
    assert analytics.primary_currency == "GBP"


def test_credit_reduces_cause_total() -> None:
    analytics = build_driver_analytics(
        [
            _rec("client_request", "3000"),
            _rec("client_request", "-500"),
        ]
    )
    assert analytics.by_cause[0].cost == Decimal("2500")
    assert analytics.total_cost == Decimal("2500")


def test_pareto_cross_bucket_credit_keeps_cumulative_monotonic() -> None:
    # A scope addition in one cause and a value-engineering credit in another
    # must not break the Pareto: normalising on absolute cost keeps the
    # cumulative climbing monotonically to 100 with every share inside 0..100,
    # while each bucket still reports its signed net cost verbatim and the
    # headline total stays the net signed sum.
    analytics = build_driver_analytics(
        [
            _rec("design_error", "3000"),
            _rec("client_request", "-500"),
        ]
    )
    causes = analytics.by_cause
    assert [r.key for r in causes] == ["design_error", "client_request"]
    assert causes[0].cost == Decimal("3000")
    assert causes[1].cost == Decimal("-500")
    assert causes[0].cost_pct == pytest.approx(85.71, abs=0.01)
    assert causes[1].cost_pct == pytest.approx(14.29, abs=0.01)
    assert causes[0].cumulative_pct == pytest.approx(85.71, abs=0.01)
    assert causes[1].cumulative_pct == 100.0
    cumulatives = [r.cumulative_pct for r in causes]
    assert cumulatives == sorted(cumulatives)
    assert all(0.0 <= r.cost_pct <= 100.0 for r in causes)
    assert analytics.total_cost == Decimal("2500")


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------


def test_trend_sorted_by_month_with_exact_cost() -> None:
    analytics = build_driver_analytics(
        [
            _rec("a", "100", month="2026-05"),
            _rec("b", "200", month="2026-04"),
            _rec("c", "300", month="2026-05"),
        ]
    )
    assert [(t.month, t.count, t.cost) for t in analytics.trend] == [
        ("2026-04", 1, Decimal("200")),
        ("2026-05", 2, Decimal("400")),
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
