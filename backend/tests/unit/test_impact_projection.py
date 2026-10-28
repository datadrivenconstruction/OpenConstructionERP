# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure change cost/schedule impact projection engine.

Stdlib + pytest only; money is asserted as exact Decimal, never float.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.impact_projection import (
    KIND_CHANGE_ORDER,
    KIND_VARIATION_ORDER,
    ApprovedChange,
    CurrencyImpact,
    ImpactProjection,
    KindImpact,
    TimelineImpactEvent,
    project_impacts,
    to_timeline_events,
)


def _change(
    ref_id: str,
    cost: str,
    days: int,
    *,
    kind: str = KIND_CHANGE_ORDER,
    currency: str = "EUR",
    status: str = "approved",
    approved_at: str | None = None,
) -> ApprovedChange:
    """Build an ApprovedChange with a Decimal cost from a string literal."""
    return ApprovedChange(
        ref_id=ref_id,
        kind=kind,
        cost_impact=Decimal(cost),
        schedule_impact_days=days,
        currency=currency,
        status=status,
        approved_at=approved_at,
    )


# --------------------------------------------------------------------------
# Empty input
# --------------------------------------------------------------------------


def test_empty_input_projection():
    proj = project_impacts([])
    assert proj == ImpactProjection(
        approved_count=0,
        total_schedule_delta_days=0,
        by_kind=[],
        by_currency=[],
        primary_currency="",
        primary_currency_cost=Decimal("0"),
    )
    # Primary cost is an exact Decimal zero, not a float.
    assert isinstance(proj.primary_currency_cost, Decimal)
    assert proj.primary_currency_cost == Decimal("0")


def test_empty_input_timeline_events():
    assert to_timeline_events("proj-1", []) == []


# --------------------------------------------------------------------------
# Summation of Decimal costs and int days
# --------------------------------------------------------------------------


def test_summation_costs_and_days_exact_decimal():
    changes = [
        _change("CO-1", "1500.50", 3),
        _change("CO-2", "0.25", 2),
        _change("CO-3", "1000.25", 5),
    ]
    proj = project_impacts(changes)

    assert proj.approved_count == 3
    assert proj.total_schedule_delta_days == 10

    # Single kind + single currency: both buckets carry the full signed sum.
    assert len(proj.by_kind) == 1
    kind = proj.by_kind[0]
    assert kind.kind == KIND_CHANGE_ORDER
    assert kind.count == 3
    assert kind.total_cost == Decimal("2501.00")
    assert isinstance(kind.total_cost, Decimal)
    assert kind.total_days == 10

    assert len(proj.by_currency) == 1
    cur = proj.by_currency[0]
    assert cur == CurrencyImpact(currency="EUR", total_cost=Decimal("2501.00"), count=3)


def test_costs_kept_at_full_precision_no_rounding():
    # Three thirds-of-a-cent must NOT be quantized away.
    changes = [_change(f"CO-{i}", "0.001", 0) for i in range(3)]
    proj = project_impacts(changes)
    assert proj.by_currency[0].total_cost == Decimal("0.003")
    assert proj.primary_currency_cost == Decimal("0.003")


# --------------------------------------------------------------------------
# by_kind grouping across change orders + variation orders
# --------------------------------------------------------------------------


def test_by_kind_groups_and_sorts():
    changes = [
        _change("VO-1", "500.00", 4, kind=KIND_VARIATION_ORDER),
        _change("CO-1", "200.00", 1, kind=KIND_CHANGE_ORDER),
        _change("VO-2", "300.50", 2, kind=KIND_VARIATION_ORDER),
        _change("CO-2", "100.00", 3, kind=KIND_CHANGE_ORDER),
    ]
    proj = project_impacts(changes)

    # Sorted by kind string: "change_order" before "variation_order".
    assert [k.kind for k in proj.by_kind] == [KIND_CHANGE_ORDER, KIND_VARIATION_ORDER]

    co, vo = proj.by_kind
    assert co == KindImpact(kind=KIND_CHANGE_ORDER, count=2, total_cost=Decimal("300.00"), total_days=4)
    assert vo == KindImpact(kind=KIND_VARIATION_ORDER, count=2, total_cost=Decimal("800.50"), total_days=6)
    assert proj.total_schedule_delta_days == 10


def test_arbitrary_kind_grouped_as_is():
    changes = [
        _change("X-1", "10.00", 0, kind="site_instruction"),
        _change("X-2", "20.00", 0, kind="site_instruction"),
    ]
    proj = project_impacts(changes)
    assert len(proj.by_kind) == 1
    assert proj.by_kind[0].kind == "site_instruction"
    assert proj.by_kind[0].total_cost == Decimal("30.00")
    assert proj.by_kind[0].count == 2


# --------------------------------------------------------------------------
# by_currency grouping including an empty-currency bucket
# --------------------------------------------------------------------------


def test_by_currency_groups_including_empty_bucket():
    changes = [
        _change("CO-1", "1000.00", 0, currency="USD"),
        _change("CO-2", "500.00", 0, currency="EUR"),
        _change("CO-3", "250.00", 0, currency="EUR"),
        _change("CO-4", "99.99", 0, currency=""),  # unpriced -> own bucket
    ]
    proj = project_impacts(changes)

    # Sorted by currency string: "" first, then "EUR", then "USD".
    assert [c.currency for c in proj.by_currency] == ["", "EUR", "USD"]

    empty_bucket, eur, usd = proj.by_currency
    assert empty_bucket == CurrencyImpact(currency="", total_cost=Decimal("99.99"), count=1)
    assert eur == CurrencyImpact(currency="EUR", total_cost=Decimal("750.00"), count=2)
    assert usd == CurrencyImpact(currency="USD", total_cost=Decimal("1000.00"), count=1)

    # No blended cross-currency total exists; primary is the largest absolute.
    assert proj.primary_currency == "USD"
    assert proj.primary_currency_cost == Decimal("1000.00")


# --------------------------------------------------------------------------
# Primary currency selection
# --------------------------------------------------------------------------


def test_primary_currency_when_one_dominates():
    changes = [
        _change("CO-1", "100.00", 0, currency="EUR"),
        _change("CO-2", "5000.00", 0, currency="GBP"),
        _change("CO-3", "200.00", 0, currency="USD"),
    ]
    proj = project_impacts(changes)
    assert proj.primary_currency == "GBP"
    assert proj.primary_currency_cost == Decimal("5000.00")


def test_primary_currency_tiebreak_by_string_order():
    # Equal absolute totals -> currency string sort order decides (EUR < USD).
    changes = [
        _change("CO-1", "750.00", 0, currency="USD"),
        _change("CO-2", "750.00", 0, currency="EUR"),
    ]
    proj = project_impacts(changes)
    assert proj.primary_currency == "EUR"
    assert proj.primary_currency_cost == Decimal("750.00")


def test_primary_currency_uses_absolute_but_reports_signed():
    # A large credit (negative) in one currency must still win primary by
    # absolute magnitude, while its reported total stays negative.
    changes = [
        _change("CO-1", "-9000.00", 0, currency="USD"),  # big credit
        _change("CO-2", "1000.00", 0, currency="EUR"),
    ]
    proj = project_impacts(changes)
    assert proj.primary_currency == "USD"
    assert proj.primary_currency_cost == Decimal("-9000.00")


# --------------------------------------------------------------------------
# Negative (credit) changes reduce totals and behave in every sum
# --------------------------------------------------------------------------


def test_credit_reduces_totals_within_currency_and_kind():
    changes = [
        _change("CO-1", "2000.00", 5, kind=KIND_CHANGE_ORDER, currency="EUR"),
        _change("CO-2", "-500.00", -2, kind=KIND_CHANGE_ORDER, currency="EUR"),
    ]
    proj = project_impacts(changes)

    assert proj.by_currency[0] == CurrencyImpact(currency="EUR", total_cost=Decimal("1500.00"), count=2)
    assert proj.by_kind[0].total_cost == Decimal("1500.00")
    # Signed day sum: acceleration partly offsets the slip.
    assert proj.by_kind[0].total_days == 3
    assert proj.total_schedule_delta_days == 3
    assert proj.primary_currency == "EUR"
    assert proj.primary_currency_cost == Decimal("1500.00")


def test_net_negative_currency_total_can_be_negative():
    changes = [
        _change("CO-1", "-1000.00", 0, currency="EUR"),
        _change("CO-2", "300.00", 0, currency="EUR"),
    ]
    proj = project_impacts(changes)
    assert proj.by_currency[0].total_cost == Decimal("-700.00")
    assert proj.primary_currency == "EUR"
    assert proj.primary_currency_cost == Decimal("-700.00")


# --------------------------------------------------------------------------
# to_timeline_events: sign-as-string, count, order
# --------------------------------------------------------------------------


def test_to_timeline_events_preserves_count_and_order():
    changes = [
        _change("CO-3", "10.00", 1),
        _change("CO-1", "20.00", 2),
        _change("CO-2", "30.00", 3),
    ]
    events = to_timeline_events("proj-9", changes)
    assert len(events) == 3
    # Order is exactly the input order, not sorted.
    assert [e.ref_id for e in events] == ["CO-3", "CO-1", "CO-2"]
    assert all(e.project_id == "proj-9" for e in events)


def test_to_timeline_events_cost_delta_is_signed_string():
    changes = [
        _change("CO-1", "1500.50", 3, currency="EUR"),
        _change("CO-2", "-250.75", -1, currency="USD"),  # credit
    ]
    events = to_timeline_events("proj-1", changes)

    assert events[0] == TimelineImpactEvent(
        project_id="proj-1",
        ref_id="CO-1",
        kind=KIND_CHANGE_ORDER,
        cost_delta="1500.50",
        schedule_delta_days=3,
        currency="EUR",
    )
    # Credit keeps its leading minus sign; value is a str, not a Decimal/float.
    assert events[1].cost_delta == "-250.75"
    assert isinstance(events[1].cost_delta, str)
    assert events[1].schedule_delta_days == -1
    assert events[1].currency == "USD"


def test_timeline_cost_delta_round_trips_to_same_decimal():
    change = _change("CO-1", "0.001", 0)
    [event] = to_timeline_events("p", [change])
    # The string form reconstructs the exact original Decimal (lossless).
    assert Decimal(event.cost_delta) == change.cost_impact


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
