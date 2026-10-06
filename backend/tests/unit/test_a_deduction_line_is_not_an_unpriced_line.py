# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An imported deduction line carries no price on purpose and is not reported as unpriced.

A bill item with a negative amount is imported with its quantity and no price,
flagged ``metadata.deduction``; one markup line on the bill takes its amount
off. "Every position should have a unit rate" would otherwise flag each one.
"""

from __future__ import annotations

import asyncio

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import PositionHasUnitRate


def _row(pos_id: str, unit_rate: float, metadata: dict) -> dict:
    return {
        "id": pos_id,
        "parent_id": None,
        "ordinal": pos_id,
        "description": "Minori lavori di finitura",
        "unit": "pcs",
        "quantity": 2,
        "unit_rate": unit_rate,
        "total": 2 * unit_rate,
        "classification": {},
        "source": "xpwe_import",
        "type": "position",
        "metadata": metadata,
    }


def _failed(rows: list[dict]) -> list[str]:
    results = asyncio.run(PositionHasUnitRate().validate(ValidationContext(data={"positions": rows})))
    return [r.element_ref for r in results if not r.passed]


def test_a_deduction_line_without_a_price_passes() -> None:
    assert _failed([_row("d1", 0, {"deduction": True, "deduction_amount": "-100.0000"})]) == []


def test_any_other_line_without_a_price_still_fails() -> None:
    assert _failed([_row("p1", 0, {}), _row("p2", 0, {"deduction": "yes"})]) == ["p1", "p2"]
