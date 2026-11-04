"""Money and quantity comparisons in the BOQ service are exact (Decimal), not float."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.boq.service import (
    _is_section,
    _stamp_resource_variant_snapshots,
    _stamp_variant_snapshot,
    is_empty_position,
    resource_fx_factor,
)


def _pos(quantity: str, unit_rate: str, unit: str = "") -> SimpleNamespace:
    return SimpleNamespace(unit=unit, quantity=quantity, unit_rate=unit_rate, description="")


def _meta(rate: float | None = None) -> dict:
    meta: dict = {"variant_default": "mean"}
    if rate is not None:
        meta["variant_snapshot"] = {
            "label": "average",
            "source": "default_mean",
            "rate": rate,
            "currency": "EUR",
            "captured_at": "2026-01-01T00:00:00",
        }
    return meta


# Section detection


@pytest.mark.parametrize("qty,rate", [("0", "0"), ("0.000", "0.0000"), ("", ""), ("-0", "0")])
def test_zero_quantity_and_rate_is_section(qty: str, rate: str) -> None:
    assert _is_section(_pos(qty, rate))


@pytest.mark.parametrize("qty,rate", [("1e-400", "0"), ("0", "1e-400"), ("0.0001", "0"), ("0", "0.0001")])
def test_tiny_nonzero_value_is_not_a_section(qty: str, rate: str) -> None:
    # float("1e-400") underflows to 0.0; the exact value is not zero.
    assert not _is_section(_pos(qty, rate))


def test_non_finite_values_still_read_as_zero() -> None:
    assert _is_section(_pos("nan", "inf"))


def test_section_needs_section_unit() -> None:
    assert not _is_section(_pos("0", "0", unit="m2"))


def test_empty_position_uses_exact_quantity() -> None:
    assert is_empty_position(_pos("0.000", "5"))
    assert not is_empty_position(_pos("1e-400", "5"))


# Variant snapshot tolerance


@pytest.mark.parametrize(("old", "new"), [(10.0, "10.005"), (1.0, "1.005"), (2.675, "2.68")])
def test_snapshot_half_cent_difference_restamps(old: float, new: str) -> None:
    # A difference of exactly 0.005 is not below the tolerance, so it is a change.
    meta = _stamp_variant_snapshot(_meta(old), unit_rate=Decimal(new), currency="EUR")
    assert meta["variant_snapshot"]["rate"] == pytest.approx(float(new))
    assert meta["variant_snapshot"]["captured_at"] != "2026-01-01T00:00:00"


def test_snapshot_sub_half_cent_difference_is_noop() -> None:
    meta = _stamp_variant_snapshot(_meta(10.0), unit_rate=Decimal("10.0049"), currency="EUR")
    assert meta["variant_snapshot"]["captured_at"] == "2026-01-01T00:00:00"


def test_snapshot_rate_rounded_to_four_places() -> None:
    meta = _stamp_variant_snapshot(_meta(), unit_rate="123456789012.34565", currency="EUR")
    assert meta["variant_snapshot"]["rate"] == 123456789012.3456  # half-even at 4dp


def test_snapshot_rejects_garbage_rate_as_zero() -> None:
    meta = _stamp_variant_snapshot(_meta(), unit_rate="abc", currency="EUR")
    assert meta["variant_snapshot"]["rate"] == 0.0


def test_resource_snapshot_half_cent_difference_restamps() -> None:
    res = {
        "unit_rate": "10.005",
        "currency": "EUR",
        "variant_default": "mean",
        "variant_snapshot": {"label": "average", "source": "default_mean", "rate": 10.0, "captured_at": "old"},
    }
    _stamp_resource_variant_snapshots({"resources": [res]}, position_currency="EUR")
    assert res["variant_snapshot"]["captured_at"] != "old"


# Totals


def test_many_cent_lines_sum_exactly() -> None:
    from app.modules.boq.service import _resource_line_total

    total = sum((_resource_line_total("1", "0.10") for _ in range(10_000)), Decimal("0"))
    assert total == Decimal("1000.0000")


def test_three_decimal_quantity_and_large_rate() -> None:
    from app.modules.boq.service import _resource_line_total

    assert _resource_line_total("1234.567", "98765432.1") == Decimal("121932543211.4007")


@pytest.mark.parametrize("rate", ["1e30", "123456789012345678901234567890.5"])
def test_snapshot_huge_rate_does_not_raise(rate: str) -> None:
    meta = _stamp_variant_snapshot(_meta(), unit_rate=rate, currency="EUR")
    assert meta["variant_snapshot"]["rate"] == pytest.approx(float(rate))


@pytest.mark.parametrize("raw", ["1e400", "1e22", "1e30", "inf", "nan", "0", "-2", "abc"])
def test_fx_rate_not_finite_or_out_of_bounds_is_rejected(raw: str) -> None:
    assert resource_fx_factor("EUR", "USD", {"EUR": raw}) is None


def test_fx_rate_sane_value_accepted() -> None:
    assert resource_fx_factor("EUR", "USD", {"EUR": "1.0850"}) == Decimal("1.0850")
