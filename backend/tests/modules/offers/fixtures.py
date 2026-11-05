"""Worked examples of the customer offer (DOMAIN sec. 10) as plain line lists."""

from __future__ import annotations

from typing import Any


def _sec(ordinal: str, text: str) -> dict[str, Any]:
    return {"kind": "section", "ordinal": ordinal, "description": text}


def _item(
    ordinal: str, text: str, qty: str, rate: str, role: str = "base", unit: str = "pcs", **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "item",
        "ordinal": ordinal,
        "description": text,
        "quantity": qty,
        "unit_rate": rate,
        "role": role,
        "unit": unit,
        **extra,
    }


def de_items() -> list[dict[str, Any]]:
    """Bathroom and kitchen renovation: net 48,350.00 with one optional item of 640.00."""
    return [
        _sec("01", "Demolition"),
        _item("01.0010", "Demolition and disposal", "1", "4350.00", "lump_sum", "LS"),
        _sec("02", "Bathroom"),
        _item("02.0010", "Wall and floor tiling", "38.5", "118.00", unit="m2"),
        _item("02.0020", "Sanitary installation", "1", "9800.00", "lump_sum", "LS"),
        _item("02.0030", "Shower enclosure", "1", "2400.00"),
        _item("02.0040", "Heated towel rail", "1", "640.00", "optional"),
        _sec("03", "Kitchen and electrics"),
        _item("03.0010", "Kitchen fitting", "1", "14000.00", "lump_sum", "LS"),
        _item("03.0020", "Electrical works", "1", "8100.00", "lump_sum", "LS"),
        _sec("04", "Finishes"),
        _item("04.0010", "Painting walls and ceilings", "180", "25.00", unit="m2"),
        _item("04.0020", "Final cleaning", "1", "657.00", "lump_sum", "LS"),
    ]


def uk_items() -> list[dict[str, Any]]:
    """The same net with 3,500.00 of it a provisional sum."""
    items = [i for i in de_items() if i.get("ordinal") not in ("03.0010", "02.0040")]
    at = next(i for i, row in enumerate(items) if row.get("ordinal") == "03.0020")
    items.insert(at, _item("03.0010", "Kitchen fitting", "1", "10500.00", "lump_sum", "LS"))
    items.insert(at + 1, _item("03.0015", "Provisional sum: kitchen appliances", "1", "3500.00", "provisional_sum"))
    return items


def us_ca_items() -> list[dict[str, Any]]:
    return [
        _sec("1", "Remodel"),
        _item("1.1", "Framing and structure", "1", "18340.00", "lump_sum", "LS"),
        _item("1.2", "Drywall and finishes", "1", "19340.00", "lump_sum", "LS"),
        _item("1.3", "Final trim and cleanup", "1", "10670.00", "lump_sum", "LS"),
    ]
