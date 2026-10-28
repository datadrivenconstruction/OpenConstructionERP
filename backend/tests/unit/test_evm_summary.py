"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the scalar EVM rollup (Section 6 - earned value).

These import only :mod:`app.modules.schedule.evm_math`, which is intentionally
free of ORM / DB imports, so the whole module runs without a PostgreSQL
cluster (and on Python 3.11 locally). They lock down the PMBOK identities:
PV/EV/AC, BAC, SV/CV, SPI/CPI and the CPI-method forecast (EAC/ETC/VAC),
plus the divide-by-zero -> None contract.

Money contract: the nine money fields are ``Decimal`` (computed and
accumulated in Decimal, never float); ``to_json`` serialises them as strings
(Decimal-as-string wire contract). The ``spi`` / ``cpi`` ratios stay plain
``float | None`` and serialise as numbers / null.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.schedule.evm_math import (
    EvmCostRow,
    EvmSummary,
    coerce_progress_decimal,
    coerce_progress_value,
    compute_evm_summary,
    planned_value_decimal,
    planned_value_for_dates,
)

# The money fields on EvmSummary, in declaration order.
_MONEY_FIELDS = (
    "planned_value",
    "earned_value",
    "actual_cost",
    "budget_at_completion",
    "schedule_variance",
    "cost_variance",
    "estimate_at_completion",
    "estimate_to_complete",
    "variance_at_completion",
)


def _row(
    start: str | None,
    end: str | None,
    planned: str | None,
    actual: str | None,
    progress: str | None,
) -> EvmCostRow:
    return EvmCostRow(
        start_date=start,
        end_date=end,
        cost_planned=Decimal(planned) if planned is not None else None,
        cost_actual=Decimal(actual) if actual is not None else None,
        progress_pct=progress,
    )


def test_spi_cpi_and_forecast_two_activities():
    """Two activities, data date past both ends so PV == BAC.

    A: 50%, PV=1000, AC=600  -> EV=500
    B: 100%, PV=2000, AC=1800 -> EV=2000
    Totals: PV=3000, EV=2500, AC=2400, BAC=3000.
    """
    rows = [
        _row("2026-01-01", "2026-02-01", "1000", "600", "50"),
        _row("2026-01-01", "2026-02-01", "2000", "1800", "100"),
    ]
    out = compute_evm_summary(rows, date(2026, 4, 1))

    assert out.has_cost_data is True
    # Money fields are exact Decimals (no float drift).
    assert out.planned_value == Decimal("3000.0000")
    assert out.earned_value == Decimal("2500.0000")
    assert out.actual_cost == Decimal("2400.0000")
    assert out.budget_at_completion == Decimal("3000.0000")
    assert out.schedule_variance == Decimal("-500.0000")  # EV - PV
    assert out.cost_variance == Decimal("100.0000")  # EV - AC
    # Ratios stay float.
    assert out.spi == pytest.approx(2500.0 / 3000.0, rel=1e-3)
    assert out.cpi == pytest.approx(2500.0 / 2400.0, rel=1e-3)
    # EAC = BAC / CPI ; ETC = EAC - AC ; VAC = BAC - EAC. The money fields are
    # Decimal; compare via float() since pytest.approx(rel=...) cannot scale a
    # Decimal expected value (float * Decimal raises).
    expected_eac = 3000.0 / (2500.0 / 2400.0)
    assert isinstance(out.estimate_at_completion, Decimal)
    assert float(out.estimate_at_completion) == pytest.approx(expected_eac, rel=1e-3)
    assert float(out.estimate_to_complete) == pytest.approx(expected_eac - 2400.0, rel=1e-3)
    assert float(out.variance_at_completion) == pytest.approx(3000.0 - expected_eac, rel=1e-3)


def test_money_fields_are_decimal_and_ratios_float():
    """EvmSummary: the nine money fields are Decimal; spi/cpi are float."""
    rows = [_row("2026-01-01", "2026-02-01", "1000", "600", "50")]
    out = compute_evm_summary(rows, date(2026, 4, 1))

    for fname in _MONEY_FIELDS:
        value = getattr(out, fname)
        # Either a Decimal (always for the six unconditional ones) or None
        # (only the eac/etc/vac trio when undefined). Here all are defined.
        assert isinstance(value, Decimal), f"{fname} should be Decimal, got {type(value)}"
    assert isinstance(out.spi, float), f"spi should be float, got {type(out.spi)}"
    assert isinstance(out.cpi, float), f"cpi should be float, got {type(out.cpi)}"
    assert isinstance(out.has_cost_data, bool)


def test_to_json_serialises_money_as_string_and_ratios_as_number():
    """to_json: money -> str(Decimal); spi/cpi -> float/None; bool stays bool."""
    rows = [_row("2026-01-01", "2026-02-01", "1000", "600", "50")]
    data = compute_evm_summary(rows, date(2026, 4, 1)).to_json()

    for fname in _MONEY_FIELDS:
        assert isinstance(data[fname], str), f"{fname} should serialise as str, got {type(data[fname])}"
        # And the string must round-trip back to a Decimal losslessly.
        assert Decimal(data[fname]) == Decimal(data[fname])
    # PV/EV/AC string values are the quantized Decimals.
    assert data["planned_value"] == "1000.0000"
    assert data["earned_value"] == "500.0000"
    assert data["actual_cost"] == "600.0000"
    # Ratios are numbers (not strings), bool stays bool.
    assert isinstance(data["spi"], float)
    assert isinstance(data["cpi"], float)
    assert data["has_cost_data"] is True


def test_pv_is_time_phased_to_data_date():
    """An in-progress activity contributes a prorated PV, not its full budget.

    10-day activity, BAC=1000, data date at day 4 -> PV = 1000 * 4/10 = 400.
    EV is BAC * progress% regardless of the data date: 30% -> 300.
    """
    rows = [_row("2026-01-01", "2026-01-11", "1000", "250", "30")]
    out = compute_evm_summary(rows, date(2026, 1, 5))  # 4 elapsed days

    assert out.planned_value == Decimal("400.0000")
    assert out.earned_value == Decimal("300.0000")
    assert out.budget_at_completion == Decimal("1000.0000")
    # SV = 300 - 400 = -100 (behind schedule); CV = 300 - 250 = 50 (under cost).
    assert out.schedule_variance == Decimal("-100.0000")
    assert out.cost_variance == Decimal("50.0000")


def test_no_cost_data_yields_none_indices_and_forecast():
    """No cost columns at all -> has_cost_data False and all ratios None."""
    rows = [_row("2026-01-01", "2026-02-01", None, None, "40")]
    out = compute_evm_summary(rows, date(2026, 4, 1))

    assert out.has_cost_data is False
    assert out.planned_value == Decimal("0.0000")
    assert out.earned_value == Decimal("0.0000")
    assert out.actual_cost == Decimal("0.0000")
    assert out.budget_at_completion == Decimal("0.0000")
    assert out.spi is None
    assert out.cpi is None
    assert out.estimate_at_completion is None
    assert out.estimate_to_complete is None
    assert out.variance_at_completion is None
    # And on the wire: money is "0.0000" strings, forecast trio is JSON null.
    data = out.to_json()
    assert data["planned_value"] == "0.0000"
    assert data["estimate_at_completion"] is None
    assert data["spi"] is None


def test_zero_actual_cost_leaves_cpi_and_eac_none():
    """Cost-loaded plan but zero AC -> CPI undefined, so EAC/ETC/VAC are None.

    PV is present (SPI computable) but no actuals captured yet.
    """
    rows = [_row("2026-01-01", "2026-02-01", "1000", None, "50")]
    out = compute_evm_summary(rows, date(2026, 4, 1))

    assert out.has_cost_data is True
    assert out.budget_at_completion == Decimal("1000.0000")
    assert out.earned_value == Decimal("500.0000")
    assert out.actual_cost == Decimal("0.0000")
    assert out.spi == pytest.approx(500.0 / 1000.0, rel=1e-3)
    assert out.cpi is None  # EV / 0 is undefined
    assert out.estimate_at_completion is None
    assert out.estimate_to_complete is None
    assert out.variance_at_completion is None


def test_decimal_precision_is_preserved_not_lost_through_float():
    """A cent-precise budget survives the rollup without binary-float drift.

    0.1 + 0.2 in float is 0.30000000000000004; the Decimal path keeps it exact.
    """
    rows = [
        _row("2026-01-01", "2026-02-01", "0.10", "0", "100"),
        _row("2026-01-01", "2026-02-01", "0.20", "0", "100"),
    ]
    out = compute_evm_summary(rows, date(2026, 4, 1))
    assert out.budget_at_completion == Decimal("0.3000")
    assert out.earned_value == Decimal("0.3000")
    assert out.to_json()["budget_at_completion"] == "0.3000"


def test_empty_rows_returns_zeroed_summary():
    out = compute_evm_summary([], date(2026, 4, 1))
    assert out.has_cost_data is False
    assert out.planned_value == Decimal("0.0000")
    assert out.budget_at_completion == Decimal("0.0000")
    assert out.spi is None
    assert out.cpi is None
    assert out.to_json()["estimate_at_completion"] is None
    assert out.to_json()["planned_value"] == "0.0000"


def test_progress_is_clamped_and_garbage_safe():
    assert coerce_progress_value("50") == 50.0
    assert coerce_progress_value("150") == 100.0  # clamp high
    assert coerce_progress_value("-10") == 0.0  # clamp low
    assert coerce_progress_value(None) == 0.0
    assert coerce_progress_value("not-a-number") == 0.0


def test_progress_decimal_is_clamped_and_garbage_safe():
    """Decimal progress coercion clamps to 0..100 and never raises."""
    assert coerce_progress_decimal("50") == Decimal("50")
    assert coerce_progress_decimal("150") == Decimal("100")  # clamp high
    assert coerce_progress_decimal("-10") == Decimal("0")  # clamp low
    assert coerce_progress_decimal(None) == Decimal("0")
    assert coerce_progress_decimal("not-a-number") == Decimal("0")
    assert coerce_progress_decimal("33.33") == Decimal("33.33")  # fractional kept
    # NaN / inf strings are coerced to 0, not propagated.
    assert coerce_progress_decimal("NaN") == Decimal("0")
    assert coerce_progress_decimal("Infinity") == Decimal("0")
    # And the result is always a Decimal.
    assert isinstance(coerce_progress_decimal("50"), Decimal)


def test_planned_value_for_dates_boundaries():
    bac = 1000.0
    # Before start -> 0.
    assert planned_value_for_dates("2026-01-10", "2026-01-20", bac, date(2026, 1, 1)) == 0.0
    # On/after end -> full BAC.
    assert planned_value_for_dates("2026-01-10", "2026-01-20", bac, date(2026, 1, 20)) == pytest.approx(bac)
    assert planned_value_for_dates("2026-01-10", "2026-01-20", bac, date(2026, 2, 1)) == pytest.approx(bac)
    # Unparseable dates or zero BAC -> 0 (defensive, never raises).
    assert planned_value_for_dates(None, "2026-01-20", bac, date(2026, 1, 15)) == 0.0
    assert planned_value_for_dates("2026-01-10", "2026-01-20", 0.0, date(2026, 1, 15)) == 0.0


def test_planned_value_decimal_boundaries_and_type():
    """Decimal PV proration matches the float helper's contract, in Decimal."""
    bac = Decimal("1000")
    # Before start -> 0.
    assert planned_value_decimal("2026-01-10", "2026-01-20", bac, date(2026, 1, 1)) == Decimal("0")
    # On/after end -> full BAC.
    assert planned_value_decimal("2026-01-10", "2026-01-20", bac, date(2026, 1, 20)) == bac
    assert planned_value_decimal("2026-01-10", "2026-01-20", bac, date(2026, 2, 1)) == bac
    # Mid-span: 10-day span (Jan 10 -> Jan 20), as_of at day 5 -> 50% = 500.
    mid = planned_value_decimal("2026-01-10", "2026-01-20", bac, date(2026, 1, 15))
    assert mid == Decimal("500")
    assert isinstance(mid, Decimal)
    # Unparseable dates or zero BAC -> 0.
    assert planned_value_decimal(None, "2026-01-20", bac, date(2026, 1, 15)) == Decimal("0")
    assert planned_value_decimal("2026-01-10", "2026-01-20", Decimal("0"), date(2026, 1, 15)) == Decimal("0")


def test_summary_dataclass_money_field_annotations_are_decimal():
    """Lock the contract at the type level: the six unconditional money fields
    are annotated Decimal, the forecast trio Decimal | None, spi/cpi float|None."""
    ann = EvmSummary.__annotations__
    assert ann["planned_value"] == "Decimal"
    assert ann["earned_value"] == "Decimal"
    assert ann["actual_cost"] == "Decimal"
    assert ann["budget_at_completion"] == "Decimal"
    assert ann["schedule_variance"] == "Decimal"
    assert ann["cost_variance"] == "Decimal"
    assert ann["estimate_at_completion"] == "Decimal | None"
    assert ann["estimate_to_complete"] == "Decimal | None"
    assert ann["variance_at_completion"] == "Decimal | None"
    assert ann["spi"] == "float | None"
    assert ann["cpi"] == "float | None"
