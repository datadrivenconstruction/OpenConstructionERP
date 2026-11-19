# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The award figures from the subcontractor award worked examples.

Example 1: a unit-price award of 412,380.00 with a 3 % discount is a contract
of 400,008.60, and a 5 % retention cap on it is 20,000.43.

Example 2: an offer of 120,000.00 + 98,450.00 + 50,000.00 = 268,450.00 revised
to a lump sum of 255,000.00 becomes a lump-sum contract whose lines are
113,987.71 + 93,517.41 + 47,494.88, adding up to 255,000.00 exactly, with the
offered unit rates kept.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_award_terms_math.py -q
"""

from __future__ import annotations

from decimal import Decimal as D

from app.modules.tendering.award_math import (
    LUMP_SUM,
    UNIT_PRICE,
    AwardInputs,
    OfferLine,
    compute_award,
    spread_pro_rata,
)


def _lines(*totals: str) -> tuple[OfferLine, ...]:
    return tuple(OfferLine(quantity=D("1"), unit_rate=D(t)) for t in totals)


def test_a_unit_price_award_takes_the_discount_off_the_lines_sum() -> None:
    figures = compute_award(
        AwardInputs(
            lines=_lines("200000.00", "150000.00", "62380.00"),
            discount_percent=D("3"),
            retention_cap_percent=D("5"),
        )
    )
    assert figures.contract_type == UNIT_PRICE
    assert figures.lines_total == D("412380.00")
    assert figures.discount_amount == D("12371.40")
    assert figures.contract_sum == D("400008.60")
    assert figures.retention_cap_amount == D("20000.43")
    assert sum(figures.line_totals) == D("400008.60")
    assert figures.line_rates == [D("194000.0000"), D("145500.0000"), D("60508.6000")]


def test_a_revised_lump_sum_is_spread_over_the_lines_pro_rata() -> None:
    figures = compute_award(
        AwardInputs(lines=_lines("120000.00", "98450.00", "50000.00"), terms_lump_sum=D("255000.00"))
    )
    assert figures.contract_type == LUMP_SUM
    assert figures.lines_total == D("268450.00")
    assert figures.contract_sum == D("255000.00")
    assert figures.line_totals == [D("113987.71"), D("93517.41"), D("47494.88")]
    assert sum(figures.line_totals) == D("255000.00")
    # The offered unit rates stay on the lines of a lump-sum contract.
    assert figures.line_rates == [D("120000.00"), D("98450.00"), D("50000.00")]
    assert figures.lines_reconcile


def test_the_offer_lump_sum_counts_when_the_terms_name_none() -> None:
    figures = compute_award(
        AwardInputs(lines=_lines("100.00", "100.00"), pricing_mode=LUMP_SUM, offer_lump_sum=D("150.00"))
    )
    assert figures.contract_type == LUMP_SUM
    assert figures.lump_sum_source == "offer"
    assert figures.line_totals == [D("75.00"), D("75.00")]


def test_a_bid_with_no_priced_lines_is_a_lump_sum_of_its_total() -> None:
    figures = compute_award(AwardInputs(bid_total=D("9999.99")))
    assert figures.contract_type == LUMP_SUM
    assert figures.contract_sum == D("9999.99")
    assert figures.line_totals == []


def test_a_unit_price_award_without_discount_keeps_its_lines() -> None:
    lines = (OfferLine(quantity=D("3"), unit_rate=D("10.333")),)
    figures = compute_award(AwardInputs(lines=lines))
    assert figures.contract_type == UNIT_PRICE
    assert figures.contract_sum == D("31.00")
    assert figures.line_totals == [D("31.00")]
    assert figures.line_rates == [D("10.333")]


def test_a_spread_over_zero_lines_puts_the_sum_on_the_last() -> None:
    assert spread_pro_rata([D("0"), D("0")], D("10")) == [D("0"), D("10.00")]
    assert spread_pro_rata([], D("10")) == []
