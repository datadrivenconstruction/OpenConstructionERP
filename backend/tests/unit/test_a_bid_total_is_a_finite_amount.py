"""A bid total or line figure that is NaN/Infinity/garbage is refused at the schema edge."""

import pytest
from pydantic import ValidationError

from app.modules.tendering.schemas import BidCreate, BidLineItem, BidUpdate
from app.modules.tendering.service import _to_decimal


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "abc", "-5", "1e400"])
def test_bad_total_rejected(bad):
    with pytest.raises(ValidationError):
        BidCreate(company_name="A", total_amount=bad)
    with pytest.raises(ValidationError):
        BidUpdate(total_amount=bad)


def test_good_total_kept():
    assert BidCreate(company_name="A", total_amount="1234.50").total_amount == "1234.50"
    assert BidCreate(company_name="A", total_amount=" ").total_amount == "0"
    assert BidUpdate().total_amount is None


@pytest.mark.parametrize("field", ["quantity", "total"])
def test_line_float_must_be_finite(field):
    with pytest.raises(ValidationError):
        BidLineItem(**{field: float("inf")})
    with pytest.raises(ValidationError):
        BidLineItem(**{field: float("nan")})


def test_line_rate_must_be_finite():
    with pytest.raises(ValidationError):
        BidLineItem(unit_rate="NaN")


def test_to_decimal_non_finite_is_default():
    assert _to_decimal("NaN") == 0
    assert _to_decimal("Infinity") == 0
