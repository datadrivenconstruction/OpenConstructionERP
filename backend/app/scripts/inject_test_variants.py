"""Inject test variants metadata into a few UK_GBP cost items so we can
verify the Cost DB / BOQ variant UI without re-running the full importer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / "backend" / "openestimate.db"
print(f"DB: {DB}")
con = sqlite3.connect(str(DB))
cur = con.cursor()

TEST_VARIANTS = [
    {
        "code_match": "UK_GBP_CONCRETE_C30",
        "variants": [
            {"index": 0, "label": "Ready-mix delivered", "price": 125.50, "price_per_unit": 125.50},
            {"index": 1, "label": "Site-mixed", "price": 98.75, "price_per_unit": 98.75},
            {"index": 2, "label": "Pumped", "price": 142.00, "price_per_unit": 142.00},
            {"index": 3, "label": "Self-compacting", "price": 168.40, "price_per_unit": 168.40},
        ],
        "stats": {
            "min": 98.75, "max": 168.40, "mean": 133.66, "median": 125.50,
            "unit": "m3", "group": "Concrete works", "count": 4, "position_count": 312,
        },
    },
    {
        "code_match": "UK_GBP_REBAR_B500",
        "variants": [
            {"index": 0, "label": "8 mm bar", "price": 0.92, "price_per_unit": 0.92},
            {"index": 1, "label": "10 mm bar", "price": 1.08, "price_per_unit": 1.08},
            {"index": 2, "label": "12 mm bar", "price": 1.24, "price_per_unit": 1.24},
            {"index": 3, "label": "16 mm bar", "price": 1.48, "price_per_unit": 1.48},
            {"index": 4, "label": "20 mm bar", "price": 1.65, "price_per_unit": 1.65},
            {"index": 5, "label": "25 mm bar", "price": 1.92, "price_per_unit": 1.92},
        ],
        "stats": {
            "min": 0.92, "max": 1.92, "mean": 1.38, "median": 1.36,
            "unit": "kg", "group": "Reinforcement steel", "count": 6, "position_count": 1245,
        },
    },
    {
        "code_match": "UK_GBP_PAINT_INTERIOR",
        "variants": [
            {"index": 0, "label": "Standard emulsion 1 coat", "price": 4.20, "price_per_unit": 4.20},
            {"index": 1, "label": "Standard emulsion 2 coats", "price": 7.80, "price_per_unit": 7.80},
            {"index": 2, "label": "Premium washable 2 coats", "price": 12.50, "price_per_unit": 12.50},
        ],
        "stats": {
            "min": 4.20, "max": 12.50, "mean": 8.17, "median": 7.80,
            "unit": "m2", "group": "Painting and decorating", "count": 3, "position_count": 87,
        },
    },
]


def find_or_pick(code_hint: str) -> tuple[str, str, str, str] | None:
    """Pick a real existing cost item with region UK_GBP and overwrite its
    metadata. We don't want to add new rows; we want to reuse real ones so
    the rate / description shows real product data."""
    cur.execute(
        "SELECT id, code, description, metadata FROM oe_costs_item "
        "WHERE region='USA_USD' AND description LIKE ? AND source='cwicr' "
        "LIMIT 1",
        (f"%{code_hint}%",),
    )
    row = cur.fetchone()
    return row


# Pick 3 real items and inject variants
candidates_hints = ["concrete", "reinforcement", "paint"]
patched: list[dict] = []
for hint, payload in zip(candidates_hints, TEST_VARIANTS, strict=False):
    row = find_or_pick(hint)
    if row is None:
        # Fallback: pick any UK row
        cur.execute(
            "SELECT id, code, description, metadata FROM oe_costs_item "
            "WHERE region='USA_USD' AND source='cwicr' LIMIT 1 OFFSET ?",
            (len(patched) * 100,),
        )
        row = cur.fetchone()
    if row is None:
        print(f"  No row found for hint={hint!r}")
        continue
    id_, code, desc, metadata_raw = row
    try:
        meta = json.loads(metadata_raw) if metadata_raw else {}
    except json.JSONDecodeError:
        meta = {}
    meta["variants"] = payload["variants"]
    meta["variant_stats"] = payload["stats"]
    cur.execute(
        "UPDATE oe_costs_item SET metadata = ? WHERE id = ?",
        (json.dumps(meta), id_),
    )
    patched.append({"id": id_, "code": code, "description": desc[:60], "variants_n": len(payload["variants"])})

con.commit()
con.close()

print(f"\nPatched {len(patched)} cost items:")
for p in patched:
    print(f"  {p['code']!r:30s} ({p['variants_n']} variants) — {p['description']!r}")
