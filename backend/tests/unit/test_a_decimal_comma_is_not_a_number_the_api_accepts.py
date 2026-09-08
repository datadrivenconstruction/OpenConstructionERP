# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The wire format for money stays dot-decimal, and this test keeps it that way.

Most of the countries this product ships a language for write one and a half as
``1,5``. That belongs in the UI, and the frontend normalises it before the value
is posted (``frontend/src/shared/lib/parseDecimal.ts``). The temptation, once
somebody discovers that a German estimator's entry is rejected, is to make the
API lenient instead - to teach ``DecimalMoney`` to read ``"48,60"``.

That would be the wrong repair, which is why this asserts the REJECTION rather
than fixing anything. ``"1,234"`` is one thousand two hundred and thirty-four to
an American and one-point-two-three-four to a German, and a payload carries no
locale to break the tie. A lenient parser therefore has to guess, and a guess
about money is a silent wrong number in someone's bill of quantities. The
normalisation has to happen where the locale is actually known, which is the
field the person typed into.

So: the API contract is dot-decimal, the frontend meets it, and a comma is a
client bug that must surface as a 422 rather than a plausible amount.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.allowances.schemas import AllowanceCreate
from app.modules.cvr.schemas import CvrLineCreate

# Every spelling a comma-locale user might produce if the frontend stopped
# normalising. Each must be refused, not guessed at.
COMMA_SPELLINGS = ["1,5", "48,60", "1.234,56", "1,234.56", "1 234,56"]

# The dot-decimal forms the frontend is contracted to send instead.
DOT_SPELLINGS = [("1.5", Decimal("1.5")), ("48.60", Decimal("48.60")), ("1234.56", Decimal("1234.56"))]


def test_the_population_this_guards_is_not_empty() -> None:
    """A gate that measures nothing passes for the wrong reason."""
    assert len(COMMA_SPELLINGS) >= 5
    assert len(DOT_SPELLINGS) >= 3


@pytest.mark.parametrize("raw", COMMA_SPELLINGS)
def test_an_allowance_refuses_a_comma_decimal(raw: str) -> None:
    with pytest.raises(ValidationError):
        AllowanceCreate(label="Provisional sum", allowance_type="provisional_sum", held_amount=raw)


@pytest.mark.parametrize("raw", COMMA_SPELLINGS)
def test_a_cvr_cost_head_refuses_a_comma_decimal(raw: str) -> None:
    with pytest.raises(ValidationError):
        CvrLineCreate(cost_code="1.1", description="Groundworks", cost_to_date=raw)


@pytest.mark.parametrize("raw,expected", DOT_SPELLINGS)
def test_the_dot_decimal_the_frontend_sends_is_accepted(raw: str, expected: Decimal) -> None:
    """The other direction, so this cannot pass by rejecting everything."""
    allowance = AllowanceCreate(label="Provisional sum", allowance_type="provisional_sum", held_amount=raw)
    assert allowance.held_amount == expected

    line = CvrLineCreate(cost_code="1.1", description="Groundworks", cost_to_date=raw)
    assert line.cost_to_date == expected
