"""AI takeoff quantities stay exact decimals from the model's text to the response.

Worked example: three rows of 0.1, 0.2 and 1234.565 m2. As floats the first
two sum to 0.30000000000000004 and the third rounds to 1234.56; as decimals
the category total is exactly 1234.865 and the row reads 1234.57.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.modules.takeoff.text_analyze import as_quantity, check_items


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.1", Decimal("0.1")),
        (0.1, Decimal("0.1")),
        (12, Decimal(12)),
        ("1234.565", Decimal("1234.565")),
        ("nan", Decimal(0)),
        ("inf", Decimal(0)),
        ("abc", Decimal(0)),
        (None, Decimal(0)),
        (True, Decimal(0)),
    ],
)
def test_as_quantity_reads_exactly_or_answers_zero(raw, expected) -> None:  # noqa: ANN001
    assert as_quantity(raw) == expected


def test_checked_quantities_are_decimals_and_sum_exactly() -> None:
    text = "Floor tiles 0.1 m2\nWall tiles 0.2 m2\nScreed 1234.565 m2\n"
    items = [
        {"description": "Floor tiles", "quantity": as_quantity("0.1"), "unit": "m2", "confidence": 0.9},
        {"description": "Wall tiles", "quantity": as_quantity("0.2"), "unit": "m2", "confidence": 0.9},
        {"description": "Screed", "quantity": as_quantity("1234.565"), "unit": "m2", "confidence": 0.9},
    ]
    rows = check_items(items, text)
    assert all(isinstance(r.quantity, Decimal) for r in rows)
    assert all(r.grounded for r in rows)
    assert sum((r.quantity for r in rows), Decimal(0)) == Decimal("1234.865")
    assert rows[2].quantity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("1234.57")
