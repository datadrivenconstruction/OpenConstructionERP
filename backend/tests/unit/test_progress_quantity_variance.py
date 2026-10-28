# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure quantity-variance engine.

Exercise app.modules.progress.quantity_variance directly with Decimal inputs -
no database, FastAPI or ORM - covering the empty report, the zero design-qty
guard (None variance percent), the exact earned==design boundary, over-run and
under-run classification, Decimal exactness, and the multi-position rollup.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.progress import quantity_variance as qv

D = Decimal


# --- Empty --------------------------------------------------------------------


def test_build_report_empty_has_zero_rollup() -> None:
    report = qv.build_report([])
    assert report.positions == ()
    rollup = report.rollup
    assert rollup.position_count == 0
    assert rollup.over_run_count == 0
    assert rollup.under_run_count == 0
    assert rollup.on_target_count == 0
    assert rollup.design_quantity_total == D("0")
    assert rollup.earned_quantity_total == D("0")
    assert rollup.variance_total == D("0")
    assert rollup.variance_percent is None


def test_summarize_empty_sequence() -> None:
    rollup = qv.summarize([])
    assert rollup.position_count == 0
    assert rollup.variance_percent is None


# --- Coercion / derivation ----------------------------------------------------


def test_to_decimal_coerces_and_guards() -> None:
    assert qv.to_decimal("12.5") == D("12.5")
    assert qv.to_decimal(D("7")) == D("7")
    assert qv.to_decimal(3) == D("3")
    assert qv.to_decimal(None) == D("0")
    assert qv.to_decimal("") == D("0")
    assert qv.to_decimal("   ") == D("0")
    assert qv.to_decimal("not-a-number") == D("0")
    assert qv.to_decimal("NaN") == D("0")
    assert qv.to_decimal("Infinity") == D("0")
    assert qv.to_decimal(None, default=D("1")) == D("1")
    assert isinstance(qv.to_decimal("5"), Decimal)


def test_derive_earned_quantity_is_exact() -> None:
    assert qv.derive_earned_quantity(D("120"), D("50")) == D("60")
    assert qv.derive_earned_quantity(D("100"), D("0")) == D("0")
    assert qv.derive_earned_quantity(D("100"), D("100")) == D("100")
    # Division by 100 stays exact (power of ten, no repeating decimals).
    assert qv.derive_earned_quantity(D("7"), D("33.333")) == D("2.33331")


# --- Zero design-quantity guard -----------------------------------------------


def test_zero_design_quantity_guards_variance_percent() -> None:
    # Something installed against a zero design quantity: percent is None (no
    # division by zero) and the position reads as an over-run (5 > 0).
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("0"),
        earned_quantity=D("5"),
    )
    assert row.variance == D("5")
    assert row.variance_percent is None
    assert row.is_over_run is True
    assert row.is_under_run is False
    assert row.status == qv.STATUS_OVER_RUN


def test_zero_design_and_zero_earned_is_on_target_none_percent() -> None:
    row = qv.compute_position_variance(
        boq_position_id="p0",
        design_quantity=D("0"),
        earned_quantity=D("0"),
    )
    assert row.variance == D("0")
    assert row.variance_percent is None
    assert row.is_over_run is False
    assert row.is_under_run is False
    assert row.status == qv.STATUS_ON_TARGET


# --- Boundary / classification ------------------------------------------------


def test_earned_equals_design_is_on_target_not_over_run() -> None:
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("50"),
        earned_quantity=D("50"),
    )
    assert row.variance == D("0")
    assert row.is_over_run is False
    assert row.is_under_run is False
    assert row.status == qv.STATUS_ON_TARGET
    assert row.variance_percent == D("0")


def test_over_run_classification_and_percent() -> None:
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("10"),
        earned_quantity=D("12"),
    )
    assert row.variance == D("2")
    assert row.variance_percent == D("20")
    assert row.is_over_run is True
    assert row.is_under_run is False
    assert row.status == qv.STATUS_OVER_RUN


def test_under_run_classification_and_percent() -> None:
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("10"),
        earned_quantity=D("8"),
    )
    assert row.variance == D("-2")
    assert row.variance_percent == D("-20")
    assert row.is_under_run is True
    assert row.is_over_run is False
    assert row.status == qv.STATUS_UNDER_RUN


# --- Decimal exactness / rounding ---------------------------------------------


def test_variance_is_exact_decimal() -> None:
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("0.1"),
        earned_quantity=D("0.3"),
    )
    # 0.3 - 0.1 == 0.2 exactly under Decimal (binary float gives 0.1999...).
    assert row.variance == D("0.2")
    assert isinstance(row.variance, Decimal)
    assert isinstance(row.earned_quantity, Decimal)


def test_variance_percent_quantized_half_up() -> None:
    # 1 / 3 * 100 = 33.333... -> quantised to 3 dp, half-up.
    row = qv.compute_position_variance(
        boq_position_id="p1",
        design_quantity=D("3"),
        earned_quantity=D("4"),
    )
    assert row.variance == D("1")
    assert row.variance_percent == D("33.333")


# --- build_report derives earned from percent ---------------------------------


def test_build_report_derives_earned_from_percent() -> None:
    inputs = [
        qv.PositionQuantityInput(
            boq_position_id="p1",
            design_quantity=D("200"),
            percent_complete=D("25"),
            ordinal="01.001",
            unit="m3",
        ),
    ]
    report = qv.build_report(inputs)
    assert len(report.positions) == 1
    row = report.positions[0]
    assert row.earned_quantity == D("50")  # 200 * 25 / 100
    assert row.variance == D("-150")
    assert row.variance_percent == D("-75")
    assert row.status == qv.STATUS_UNDER_RUN
    assert row.ordinal == "01.001"
    assert row.unit == "m3"
    # A percent-derived earned quantity can never exceed design (percent <=
    # 100), so this path is a pure under-run.
    assert report.rollup.under_run_count == 1
    assert report.rollup.over_run_count == 0


# --- Multi-position rollup ----------------------------------------------------


def test_multi_position_rollup_counts_and_totals() -> None:
    rows = [
        qv.compute_position_variance(
            boq_position_id="over",
            design_quantity=D("10"),
            earned_quantity=D("15"),
        ),
        qv.compute_position_variance(
            boq_position_id="under",
            design_quantity=D("20"),
            earned_quantity=D("5"),
        ),
        qv.compute_position_variance(
            boq_position_id="on",
            design_quantity=D("8"),
            earned_quantity=D("8"),
        ),
    ]
    rollup = qv.summarize(rows)
    assert rollup.position_count == 3
    assert rollup.over_run_count == 1
    assert rollup.under_run_count == 1
    assert rollup.on_target_count == 1
    assert rollup.design_quantity_total == D("38")  # 10 + 20 + 8
    assert rollup.earned_quantity_total == D("28")  # 15 + 5 + 8
    assert rollup.variance_total == D("-10")  # 5 - 15 + 0
    # -10 / 38 * 100 = -26.3157... -> -26.316 (half-up at 3 dp).
    assert rollup.variance_percent == D("-26.316")


def test_rollup_variance_percent_none_when_design_total_zero() -> None:
    rows = [
        qv.compute_position_variance(
            boq_position_id="z1",
            design_quantity=D("0"),
            earned_quantity=D("0"),
        ),
    ]
    rollup = qv.summarize(rows)
    assert rollup.design_quantity_total == D("0")
    assert rollup.variance_percent is None


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
