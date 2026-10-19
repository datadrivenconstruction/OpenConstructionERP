# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Saudi real estate sale is VAT exempt and carries the 5 percent RETT.

The property table called the post-2020 treatment ``zero_rated``. The amount
was the same 0.00, the meaning was not: a zero-rated supply keeps the
developer's input tax recovery and an exempt one does not, and the e-invoice
carries a different category for each (Z against E with VATEX-SA-30).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.property_dev.tax_engine import (
    RateNotInForceError,
    UnknownRateClassError,
    compute_stamp_duty,
    compute_vat,
)


def test_a_sale_after_the_reform_is_exempt() -> None:
    assert compute_vat(Decimal("1000000"), "SA", rate_class="exempt", effective_on=date(2020, 10, 4)) == Decimal("0.00")


def test_the_exemption_does_not_reach_back_before_the_reform() -> None:
    with pytest.raises(RateNotInForceError):
        compute_vat(Decimal("1000000"), "SA", rate_class="exempt", effective_on=date(2020, 10, 3))
    # Before the reform a sale was standard-rated, at 15 by then.
    assert compute_vat(Decimal("1000000"), "SA", effective_on=date(2020, 10, 3)) == Decimal("150000.00")


def test_the_mislabelled_zero_rate_is_refused() -> None:
    with pytest.raises(UnknownRateClassError):
        compute_vat(Decimal("1000000"), "SA", rate_class="zero_rated", effective_on=date(2026, 1, 1))


def test_rett_is_five_percent_of_the_price() -> None:
    assert compute_stamp_duty(Decimal("1000000"), "SA") == Decimal("50000.00")
