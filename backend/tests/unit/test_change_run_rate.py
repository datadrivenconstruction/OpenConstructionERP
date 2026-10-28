# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure change run-rate / cumulative curve engine.

Stdlib + pytest only; money is asserted as exact Decimal, never float. Runs on
the local Python 3.11 runner like the impact and cycle-time engine tests.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.change_intelligence.change_run_rate import (
    BUCKET_APPROVED,
    BUCKET_PENDING,
    KIND_CHANGE_ORDER,
    KIND_VARIATION_ORDER,
    KIND_VARIATION_REQUEST,
    ChangeEvent,
    build_run_rate,
    classify_change_bucket,
    resolve_effective_date,
)


def _event(
    ref_id: str,
    cost: str,
    at: date,
    *,
    kind: str = KIND_CHANGE_ORDER,
    bucket: str = BUCKET_APPROVED,
    currency: str = "EUR",
) -> ChangeEvent:
    return ChangeEvent(ref_id=ref_id, kind=kind, bucket=bucket, cost=Decimal(cost), currency=currency, at=at)


# --------------------------------------------------------------------------
# classify_change_bucket
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        (KIND_CHANGE_ORDER, "approved", BUCKET_APPROVED),
        (KIND_CHANGE_ORDER, "executed", BUCKET_APPROVED),
        (KIND_CHANGE_ORDER, "draft", BUCKET_PENDING),
        (KIND_CHANGE_ORDER, "submitted", BUCKET_PENDING),
        (KIND_CHANGE_ORDER, "rejected", None),
        (KIND_CHANGE_ORDER, "cancelled", None),
        (KIND_VARIATION_ORDER, "issued", BUCKET_APPROVED),
        (KIND_VARIATION_ORDER, "completed", BUCKET_APPROVED),
        (KIND_VARIATION_ORDER, "voided", None),
        (KIND_VARIATION_REQUEST, "draft", BUCKET_PENDING),
        (KIND_VARIATION_REQUEST, "under_review", BUCKET_PENDING),
        (KIND_VARIATION_REQUEST, "approved", None),  # downstream VO carries value
        (KIND_VARIATION_REQUEST, "converted_to_vo", None),
        (KIND_VARIATION_REQUEST, "rejected", None),
        ("mystery_kind", "draft", None),
    ],
)
def test_classify_change_bucket(kind: str, status: str, expected: str | None) -> None:
    assert classify_change_bucket(kind, status) == expected


def test_classify_is_case_insensitive() -> None:
    assert classify_change_bucket(KIND_CHANGE_ORDER, "APPROVED") == BUCKET_APPROVED


# --------------------------------------------------------------------------
# resolve_effective_date
# --------------------------------------------------------------------------


def test_approved_prefers_approved_then_submitted_then_created() -> None:
    created = date(2026, 1, 1)
    submitted = date(2026, 2, 1)
    approved = date(2026, 3, 1)
    assert resolve_effective_date(BUCKET_APPROVED, created, submitted, approved) == approved
    assert resolve_effective_date(BUCKET_APPROVED, created, submitted, None) == submitted
    assert resolve_effective_date(BUCKET_APPROVED, created, None, None) == created


def test_pending_prefers_submitted_then_created() -> None:
    created = date(2026, 1, 1)
    submitted = date(2026, 2, 1)
    # A pending change never looks at an approval date.
    assert resolve_effective_date(BUCKET_PENDING, created, submitted, date(2026, 3, 1)) == submitted
    assert resolve_effective_date(BUCKET_PENDING, created, None, None) == created


# --------------------------------------------------------------------------
# Empty
# --------------------------------------------------------------------------


def test_empty_run_rate() -> None:
    rr = build_run_rate(
        [],
        contract_value=Decimal("100000"),
        project_start=date(2026, 1, 1),
        project_end=date(2026, 12, 31),
        now=date(2026, 6, 30),
    )
    assert rr.change_count == 0
    assert rr.total_change_value == Decimal("0")
    assert rr.points == []
    assert rr.intake_rate_per_month == 0.0
    # No change yet, but a grounded forecast of zero change is still returned.
    assert rr.forecast is not None
    assert rr.forecast.final_change_value == Decimal("0.00")


# --------------------------------------------------------------------------
# Cumulative curve + percentages + intake rate
# --------------------------------------------------------------------------


def test_cumulative_points_and_change_pct() -> None:
    rr = build_run_rate(
        [
            _event("CO1", "10000", date(2026, 2, 15), bucket=BUCKET_APPROVED),
            _event("CO2", "5000", date(2026, 4, 10), bucket=BUCKET_PENDING),
        ],
        contract_value=Decimal("100000"),
        project_start=date(2026, 1, 1),
        project_end=date(2026, 12, 31),
        now=date(2026, 6, 30),
    )
    assert rr.approved_value == Decimal("10000")
    assert rr.pending_value == Decimal("5000")
    assert rr.total_change_value == Decimal("15000")
    assert rr.current_change_pct == Decimal("15.00")

    assert [(p.month, p.cumulative_value, p.change_pct) for p in rr.points] == [
        ("2026-02", Decimal("10000"), Decimal("10.00")),
        ("2026-04", Decimal("15000"), Decimal("15.00")),
    ]
    # Two changes across Feb..Jun inclusive = 5 months.
    assert rr.intake_rate_per_month == pytest.approx(0.4)


def test_change_pct_is_none_without_contract_value() -> None:
    rr = build_run_rate(
        [_event("CO1", "10000", date(2026, 2, 15))],
        contract_value=None,
        project_start=date(2026, 1, 1),
        project_end=date(2026, 12, 31),
        now=date(2026, 6, 30),
    )
    assert rr.current_change_pct is None
    assert rr.points[0].change_pct is None
    assert rr.forecast is None


def test_primary_currency_is_largest_absolute() -> None:
    rr = build_run_rate(
        [
            _event("A", "100", date(2026, 2, 1), currency="EUR"),
            _event("B", "9000", date(2026, 3, 1), currency="GBP"),
        ],
        contract_value=None,
        project_start=None,
        project_end=None,
        now=date(2026, 6, 30),
    )
    assert rr.currency == "GBP"


# --------------------------------------------------------------------------
# Linear burn-rate forecast
# --------------------------------------------------------------------------


def test_linear_forecast_extrapolates_to_completion() -> None:
    start = date(2026, 1, 1)
    now = start + timedelta(days=100)
    end = start + timedelta(days=200)
    rr = build_run_rate(
        [_event("CO1", "10000", start + timedelta(days=30), bucket=BUCKET_APPROVED)],
        contract_value=Decimal("100000"),
        project_start=start,
        project_end=end,
        now=now,
    )
    fc = rr.forecast
    assert fc is not None
    assert fc.method == "linear_burn_rate"
    assert fc.elapsed_days == 100
    assert fc.total_days == 200
    # 10000 over 100 days = 100/day; across 200 days = 20000 = 20% of 100000.
    assert fc.rate_per_day == Decimal("100.0000")
    assert fc.final_change_value == Decimal("20000.00")
    assert fc.final_change_pct == Decimal("20.00")
    assert fc.at_date == end.isoformat()


def test_forecast_past_completion_uses_current_value() -> None:
    start = date(2026, 1, 1)
    end = start + timedelta(days=100)
    now = end + timedelta(days=30)  # already past completion
    rr = build_run_rate(
        [_event("CO1", "12345.67", start + timedelta(days=10))],
        contract_value=Decimal("100000"),
        project_start=start,
        project_end=end,
        now=now,
    )
    assert rr.forecast is not None
    assert rr.forecast.final_change_value == Decimal("12345.67")


def test_forecast_none_without_dates() -> None:
    rr = build_run_rate(
        [_event("CO1", "10000", date(2026, 2, 15))],
        contract_value=Decimal("100000"),
        project_start=None,
        project_end=None,
        now=date(2026, 6, 30),
    )
    assert rr.forecast is None


def test_money_totals_are_exact_decimal() -> None:
    rr = build_run_rate(
        [
            _event("A", "0.001", date(2026, 2, 1)),
            _event("B", "0.002", date(2026, 3, 1)),
        ],
        contract_value=None,
        project_start=None,
        project_end=None,
        now=date(2026, 6, 30),
    )
    assert rr.total_change_value == Decimal("0.003")
    assert isinstance(rr.total_change_value, Decimal)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
