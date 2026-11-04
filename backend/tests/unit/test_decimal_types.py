"""Unit tests for app.core.decimal_types."""

from decimal import Decimal

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.core.decimal_types import Decimal18_2, FiniteDecimal, finite_decimal


class _M(BaseModel):
    a: Decimal18_2
    b: finite_decimal(5, 2, non_negative=True) | None = None
    c: finite_decimal(5, 2, positive=True) = Decimal("1")
    d: FiniteDecimal = Decimal("0")
    e: Decimal18_2 = Field(default=Decimal("0"), ge=0, le=100)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN", "1e400", "1" + "0" * 16])
def test_rejects_non_finite_and_overflow(bad):
    with pytest.raises(ValidationError):
        _M(a=bad)


def test_accepts_boundary_and_rounds_extra_fraction():
    assert _M(a="9999999999999999.99").a == Decimal("9999999999999999.99")
    assert _M(a="1.123456789").a == Decimal("1.12")
    assert _M(a="-5").a == Decimal("-5")


def test_non_negative_and_positive():
    with pytest.raises(ValidationError):
        _M(a=1, b="-0.01")
    with pytest.raises(ValidationError):
        _M(a=1, c="0")
    with pytest.raises(ValidationError):
        _M(a=1, b="1000")
    assert _M(a=1, b="999.99").b == Decimal("999.99")
    assert _M(a=1, b=None).b is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_field_level_constraints_do_not_crash_on_nan(bad):
    with pytest.raises(ValidationError):
        _M(a=1, e=bad)


def test_field_level_bounds_still_apply():
    with pytest.raises(ValidationError):
        _M(a=1, e="101")


def test_invalid_factory_args():
    with pytest.raises(ValueError):
        finite_decimal(2, 3)


def test_field_level_gt_lt_are_not_shadowed():
    class _G(BaseModel):
        a: Decimal18_2 = Field(..., gt=0)
        b: Decimal18_2 = Field(default=Decimal("0"), lt=5)
        c: Decimal18_2 | None = Field(default=None, gt=0)

    for bad in ({"a": 0}, {"a": 1, "b": 6}, {"a": 1, "c": 0}, {"a": 1, "b": "1e40"}, {"a": 1, "b": "NaN"}):
        with pytest.raises(ValidationError):
            _G(**bad)
    assert _G(a=1, b=4, c=None).b == 4


class _Q(BaseModel):
    qty: finite_decimal(18, 2)
    pct: finite_decimal(5, 2, non_negative=True)
    delta: finite_decimal(10, 2)
    raw: FiniteDecimal = Decimal("0")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.125", "1.13"), ("-1.125", "-1.13"), ("2.994", "2.99"), ("0.005", "0.01"), ("7", "7"), (1.5, "1.5")],
)
def test_extra_fraction_is_rounded_half_up_not_rejected(raw, expected):
    assert _Q(qty=raw, pct=1, delta=raw).qty == Decimal(expected)
    assert _Q(qty=raw, pct=1, delta=raw).delta == Decimal(expected)


def test_percentage_with_three_decimals_is_accepted_and_rounded():
    assert _Q(qty=1, pct="12.345", delta=0).pct == Decimal("12.35")


def test_rounding_up_into_overflow_is_rejected():
    with pytest.raises(ValidationError):
        _Q(qty=1, pct="999.995", delta=0)
    assert _Q(qty=1, pct="999.994", delta=0).pct == Decimal("999.99")


def test_giant_exponent_is_rejected_not_crashing():
    with pytest.raises(ValidationError):
        _Q(qty="1e999999", pct=1, delta=0)


def test_signed_fields_keep_negatives_and_non_negative_rejects_them():
    assert _Q(qty="-5.5", pct=0, delta="-0.004").delta == Decimal("0.00")
    assert _Q(qty=1, pct=0, delta="-250.25").delta == Decimal("-250.25")
    with pytest.raises(ValidationError):
        _Q(qty=1, pct="-0.01", delta=0)


def test_column_less_generic_type_keeps_all_digits():
    assert _Q(qty=1, pct=0, delta=0, raw="1.123456789012").raw == Decimal("1.123456789012")
