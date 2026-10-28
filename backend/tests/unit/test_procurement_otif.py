"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the pure OTIF delivery-performance helper.

Exercises app.modules.procurement.otif.compute_project_delivery_performance
directly with in-memory ReceiptRecord rows: no database, no session, no
FastAPI. Covers the empty case, the zero-denominator guards, the on-time and
in-full boundaries, the OTIF "both" requirement, average-days-late over only
late receipts, the multi-supplier rollup, supplier ordering, and Decimal/rate
exactness.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.procurement.otif import (
    ReceiptRecord,
    compute_project_delivery_performance,
)


def _rec(
    *,
    supplier: str | None = "S1",
    received: str = "2026-04-10",
    promised: str | None = "2026-04-10",
    ordered: str = "10",
    got: str = "10",
    name: str | None = None,
) -> ReceiptRecord:
    """Build a ReceiptRecord from compact string inputs."""
    return ReceiptRecord(
        supplier_id=supplier,
        received_date=date.fromisoformat(received),
        promised_date=date.fromisoformat(promised) if promised else None,
        ordered_qty=Decimal(ordered),
        received_qty=Decimal(got),
        supplier_name=name,
    )


def test_empty_returns_all_zero_counts_and_none_rates() -> None:
    perf = compute_project_delivery_performance([])
    o = perf.overall
    assert perf.suppliers == []
    assert o.total_receipts == 0
    assert o.scheduled_receipts == 0
    assert o.unscheduled_receipts == 0
    # Every rate is guarded to None on a zero denominator (never 0.0, no crash).
    assert o.on_time_rate is None
    assert o.in_full_rate is None
    assert o.otif_rate is None
    assert o.avg_days_late is None


def test_on_time_boundary_received_equals_promised_is_on_time() -> None:
    perf = compute_project_delivery_performance([_rec(received="2026-04-10", promised="2026-04-10")])
    o = perf.overall
    assert o.on_time_count == 1
    assert o.late_count == 0
    assert o.on_time_rate == Decimal("1.0000")
    assert o.avg_days_late is None  # nothing late -> guarded to None


def test_one_day_late_is_not_on_time() -> None:
    perf = compute_project_delivery_performance([_rec(received="2026-04-11", promised="2026-04-10")])
    o = perf.overall
    assert o.on_time_count == 0
    assert o.late_count == 1
    assert o.on_time_rate == Decimal("0.0000")
    assert o.avg_days_late == Decimal("1.00")


def test_in_full_boundary_equal_is_full_one_short_is_not() -> None:
    full = compute_project_delivery_performance([_rec(ordered="10", got="10")]).overall
    assert full.in_full_count == 1
    assert full.in_full_rate == Decimal("1.0000")

    short = compute_project_delivery_performance([_rec(ordered="10", got="9")]).overall
    assert short.in_full_count == 0
    assert short.in_full_rate == Decimal("0.0000")

    over = compute_project_delivery_performance([_rec(ordered="10", got="11")]).overall
    assert over.in_full_count == 1  # over-delivery still counts as in full


def test_otif_requires_both_on_time_and_in_full() -> None:
    # On time but one unit short -> not OTIF.
    a = compute_project_delivery_performance(
        [_rec(received="2026-04-10", promised="2026-04-10", ordered="10", got="9")]
    ).overall
    assert a.on_time_count == 1
    assert a.in_full_count == 0
    assert a.otif_count == 0
    assert a.otif_rate == Decimal("0.0000")

    # In full but late -> not OTIF.
    b = compute_project_delivery_performance(
        [_rec(received="2026-04-12", promised="2026-04-10", ordered="10", got="10")]
    ).overall
    assert b.in_full_count == 1
    assert b.on_time_count == 0
    assert b.otif_count == 0

    # Both on time AND in full -> OTIF.
    c = compute_project_delivery_performance(
        [_rec(received="2026-04-09", promised="2026-04-10", ordered="10", got="10")]
    ).overall
    assert c.otif_count == 1
    assert c.otif_rate == Decimal("1.0000")


def test_avg_days_late_only_over_late_receipts() -> None:
    perf = compute_project_delivery_performance(
        [
            _rec(received="2026-04-10", promised="2026-04-10"),  # on time, 0 days
            _rec(received="2026-04-12", promised="2026-04-10"),  # 2 days late
            _rec(received="2026-04-14", promised="2026-04-10"),  # 4 days late
        ]
    )
    o = perf.overall
    assert o.total_receipts == 3
    assert o.on_time_count == 1
    assert o.late_count == 2
    # Average over ONLY the two late receipts: (2 + 4) / 2 = 3.00.
    assert o.avg_days_late == Decimal("3.00")
    # On-time rate over all three scheduled receipts: 1 / 3.
    assert o.on_time_rate == Decimal("0.3333")


def test_unscheduled_excluded_from_on_time_and_otif_denominators() -> None:
    perf = compute_project_delivery_performance(
        [
            _rec(promised=None, ordered="10", got="10"),  # unscheduled, in full
            _rec(received="2026-04-10", promised="2026-04-10", ordered="10", got="10"),
        ]
    )
    o = perf.overall
    assert o.total_receipts == 2
    assert o.scheduled_receipts == 1
    assert o.unscheduled_receipts == 1
    # On-time / OTIF denominators are the SCHEDULED receipts only (1).
    assert o.on_time_count == 1
    assert o.on_time_rate == Decimal("1.0000")
    assert o.otif_rate == Decimal("1.0000")
    # In-full denominator is ALL receipts (2); both are in full.
    assert o.in_full_count == 2
    assert o.in_full_rate == Decimal("1.0000")


def test_all_unscheduled_guards_on_time_and_otif_to_none() -> None:
    perf = compute_project_delivery_performance([_rec(promised=None, ordered="10", got="10")])
    o = perf.overall
    assert o.scheduled_receipts == 0
    assert o.on_time_rate is None  # zero-denominator guard
    assert o.otif_rate is None
    assert o.in_full_rate == Decimal("1.0000")  # in-full still evaluable
    assert o.avg_days_late is None


def test_multi_supplier_rollup() -> None:
    perf = compute_project_delivery_performance(
        [
            # Supplier A: one on-time-in-full, one late-and-short.
            _rec(
                supplier="A",
                received="2026-04-09",
                promised="2026-04-10",
                ordered="10",
                got="10",
                name="Alpha",
            ),
            _rec(supplier="A", received="2026-04-12", promised="2026-04-10", ordered="10", got="8"),
            # Supplier B: one on-time but short.
            _rec(
                supplier="B",
                received="2026-04-10",
                promised="2026-04-10",
                ordered="5",
                got="4",
                name="Bravo",
            ),
        ]
    )

    # Project-wide rollup aggregates every supplier.
    o = perf.overall
    assert o.supplier_id is None
    assert o.total_receipts == 3
    assert o.on_time_count == 2  # A first + B
    assert o.in_full_count == 1  # only A first
    assert o.otif_count == 1
    assert o.otif_rate == Decimal("0.3333")

    # Per-supplier rows, ordered by id: A then B.
    assert [s.supplier_id for s in perf.suppliers] == ["A", "B"]
    a, b = perf.suppliers

    assert a.supplier_name == "Alpha"
    assert a.total_receipts == 2
    assert a.on_time_count == 1
    assert a.late_count == 1
    assert a.otif_count == 1
    assert a.otif_rate == Decimal("0.5000")
    assert a.avg_days_late == Decimal("2.00")

    assert b.supplier_name == "Bravo"
    assert b.on_time_count == 1
    assert b.in_full_count == 0
    assert b.otif_count == 0
    assert b.otif_rate == Decimal("0.0000")
    assert b.avg_days_late is None


def test_rate_decimal_exactness_two_thirds() -> None:
    # 2 of 3 on time -> 0.6667 (HALF_UP at four decimal places).
    perf = compute_project_delivery_performance(
        [
            _rec(received="2026-04-10", promised="2026-04-10"),
            _rec(received="2026-04-10", promised="2026-04-10"),
            _rec(received="2026-04-12", promised="2026-04-10"),
        ]
    )
    o = perf.overall
    assert o.on_time_rate == Decimal("0.6667")
    # Exact canonical string form (the service serialises rates via str()).
    assert str(o.on_time_rate) == "0.6667"


def test_none_supplier_group_sorts_last() -> None:
    perf = compute_project_delivery_performance([_rec(supplier=None), _rec(supplier="Z")])
    assert [s.supplier_id for s in perf.suppliers] == ["Z", None]
