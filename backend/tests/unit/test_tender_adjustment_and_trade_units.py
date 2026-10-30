"""Tender premium or rebate on a schedule of rates, and the rmt / cwt / job units.

A bid quoted as a percentage above or below a schedule of rates is a signed
``tender_adjustment`` markup line on the bill or on one section. Only that
category may be negative; the totals engine prices it like any percentage line.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.unit_conversion import convert_between
from app.core.validation.engine import ValidationContext
from app.core.validation.messages import available_locales, is_key_present
from app.modules.boq.schemas import MarkupCreate, MarkupUpdate
from app.modules.boq.service import _calculate_markup_amounts
from app.modules.boq.units import is_approved_unit, normalise_unit
from app.modules.boq.validators import MarkupPercentageWithinBand, TenderAdjustmentIsPlausible


def _row(
    name: str, percentage: str, *, category: str = "tender_adjustment", scope: str | None = None
) -> dict[str, Any]:
    return {
        "id": f"m-{name}",
        "name": name,
        "markup_type": "percentage",
        "category": category,
        "percentage": percentage,
        "fixed_amount": "0",
        "apply_to": "direct_cost",
        "sort_order": 0,
        "is_active": True,
        "scope_position_id": scope,
        "overrides_id": None,
    }


def _context(rows: list[dict[str, Any]]) -> ValidationContext:
    return ValidationContext(data={"positions": [], "markups": rows}, metadata={"locale": "en"})


def test_rebate_below_schedule_is_accepted_only_as_tender_adjustment() -> None:
    assert MarkupCreate(name="Below CSR", category="tender_adjustment", percentage=-7.5).percentage == -7.5
    with pytest.raises(ValidationError):
        MarkupCreate(name="Overhead", category="overhead", percentage=-5)
    assert MarkupUpdate(percentage=-3).percentage == -3  # sign checked against the stored row in the service


def test_negative_tender_adjustment_reduces_the_bill() -> None:
    line = SimpleNamespace(
        is_active=True, apply_to="direct_cost", markup_type="percentage", percentage="-10", id=None, metadata_={}
    )
    [(_, amount)] = _calculate_markup_amounts(Decimal("1000"), [line])
    assert amount == Decimal("-100")


@pytest.mark.asyncio
async def test_plausible_rebate_passes_and_band_rule_ignores_the_sign() -> None:
    ctx = _context([_row("Below CSR", "-12")])
    assert await TenderAdjustmentIsPlausible().validate(ctx) == []
    assert await MarkupPercentageWithinBand().validate(ctx) == []


@pytest.mark.asyncio
async def test_out_of_band_and_duplicate_scope_are_flagged() -> None:
    rows = [_row("Premium", "65"), _row("Second", "5"), _row("Section B", "-4", scope="sec-b")]
    results = await TenderAdjustmentIsPlausible().validate(_context(rows))
    messages = [r.message for r in results]
    assert len(results) == 2
    assert any("65" in m for m in messages)
    assert any("Second" in m and "Premium" in m for m in messages)


def test_tender_adjustment_messages_resolve_in_every_locale() -> None:
    for locale in available_locales():
        for leaf in ("fail", "duplicate", "suggestion"):
            assert is_key_present(f"boq_markup.tender_adjustment_plausible.{leaf}", locale), (locale, leaf)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("rmt", "lm"), ("R.Mt", "lm"), ("running metre", "lm"), ("job", "lsum"), ("cwt", "cwt"), ("hundredweight", "cwt")],
)
def test_trade_units_normalise(raw: str, canonical: str) -> None:
    assert normalise_unit(raw) == canonical
    assert is_approved_unit(canonical)


def test_cwt_converts_as_long_hundredweight() -> None:
    kg = convert_between(Decimal("1"), "cwt", "kg")
    assert kg is not None
    assert abs(kg - Decimal("50.80234544")) < Decimal("0.00001")
