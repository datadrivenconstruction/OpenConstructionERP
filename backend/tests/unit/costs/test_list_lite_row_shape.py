# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A slim cost list row carries what the list views read, and nothing heavier.

``GET /v1/costs/`` with ``lite=true`` is what every list in the app asks for:
the cost database page, the cost-match override picker and the BOQ "From
Database" modal. A CWICR row is mostly bulk that no list renders, its component
breakdown with a variant catalogue on every abstract-resource component, and
``metadata.variants``. Fifty such rows measured close to a megabyte in full.

These tests pin the slim row's shape on rows built like an imported country
pack (sixteen components, variant catalogues, scope-of-work steps, nine
description languages): the exact top-level field set, which ``metadata_``
keys survive, that nothing but the bulk is dropped, and that a page of slim
rows stays a small fraction of the same page in full. The last one is the
guard against a heavy key being added back to the whitelist.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.modules.costs.router import _LITE_METADATA_KEYS, _localize_response_payload, _slim_list_row
from app.modules.costs.schemas import CostItemResponse

# Every top-level field of a slim row. It is the full row's field set plus
# ``components_count``; a new field on the response lands here on purpose.
_LITE_ROW_FIELDS = frozenset(
    {
        "id",
        "code",
        "description",
        "descriptions",
        "unit",
        "rate",
        "buildup_rate",
        "currency",
        "source",
        "classification",
        "components",
        "components_count",
        "tags",
        "region",
        "mass_per_unit",
        "mass_basis",
        "catalog_id",
        "hazards",
        "is_active",
        "metadata_",
        "created_at",
        "updated_at",
    }
)

_LANGUAGES = ("en", "de", "ru", "fr", "es", "pt", "zh", "ar", "hi")


def _catalogue(common_start: str, count: int, base: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    variants = [
        {
            "index": i,
            "label": f"Sorte {i + 1}, Festigkeitsklasse C{20 + 5 * i}/{25 + 5 * i}, lose geliefert",
            "full_label": f"{common_start} Sorte {i + 1}, Festigkeitsklasse C{20 + 5 * i}/{25 + 5 * i}, lose geliefert",
            "price": round(base + 7.35 * i, 2),
            "price_per_unit": round((base + 7.35 * i) / 1.2, 2),
        }
        for i in range(count)
    ]
    prices = [v["price"] for v in variants]
    stats = {
        "min": min(prices),
        "max": max(prices),
        "mean": round(sum(prices) / len(prices), 2),
        "median": prices[len(prices) // 2],
        "unit": "m3",
        "group": "Beton",
        "count": len(prices),
        "common_start": common_start,
    }
    return variants, stats


def _pack_row(seq: int) -> SimpleNamespace:
    """One cost row in the shape a country pack import writes."""
    components: list[dict[str, Any]] = []
    for c in range(16):
        comp: dict[str, Any] = {
            "name": f"Transportbeton, Schalung und Bewehrung, Arbeitsgang {c + 1}",
            "code": f"KALI-{seq:03d}-{c:02d}",
            "unit": "Std." if c % 4 == 0 else "m3",
            "quantity": 0.1275,
            "unit_rate": 84.5,
            "cost": 10.77,
            "type": "labor" if c % 4 == 0 else "material",
        }
        if c % 3 == 0:
            variants, stats = _catalogue("Transportbeton nach DIN EN 206", 12, 90.0 + c)
            comp["available_variants"] = variants
            comp["available_variant_stats"] = stats
        components.append(comp)
    top_variants, top_stats = _catalogue("Beton, Sortenliste C", 16, 110.0)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid.UUID(int=seq + 1),
        code=f"KALI_KATO_{seq:05d}",
        description=f"Stahlbetonwand, Ortbeton C30/37, Dicke 24 cm, Position {seq}",
        descriptions={lang: f"Reinforced concrete wall, cast in place, 24 cm ({lang}) {seq}" for lang in _LANGUAGES},
        unit="m3",
        rate="412.37",
        currency="EUR",
        source="cwicr",
        classification={
            "collection": "Hochbau",
            "department": "Betonarbeiten",
            "section": "Waende",
            "subsection": "Ortbetonwaende",
            "category": "BAUARBEITEN",
        },
        components=components,
        tags=["concrete", "walls"],
        region="DE_BERLIN",
        mass_per_unit="",
        mass_basis="",
        catalog_id=None,
        is_active=True,
        metadata_={
            "variants": top_variants,
            "variant_stats": top_stats,
            "scope_of_work": [f"Arbeitsschritt {s + 1}: Schalung stellen, Bewehrung einbauen" for s in range(12)],
            "labor_cost": 118.4,
            "material_cost": 251.3,
            "equipment_cost": 42.67,
            "other_cost": 0.0,
            "labor_hours": 3.2,
            "workers_per_unit": 2.0,
        },
        created_at=now,
        updated_at=now,
    )


def _full_row(seq: int) -> dict[str, Any]:
    return _localize_response_payload(CostItemResponse.model_validate(_pack_row(seq)), "de")


def test_the_slim_row_has_exactly_the_list_fields() -> None:
    full = _full_row(1)
    slim = _slim_list_row(copy.deepcopy(full))

    assert set(slim) == _LITE_ROW_FIELDS
    # Nothing is dropped from the top level: the slim row is the full row
    # plus its component count.
    assert set(full) | {"components_count"} == _LITE_ROW_FIELDS


def test_only_the_bulk_is_dropped() -> None:
    full = _full_row(2)
    slim = _slim_list_row(copy.deepcopy(full))

    assert slim["components"] == []
    assert slim["components_count"] == 16
    assert "variants" not in slim["metadata_"]
    # The fixture carries every whitelisted key, so each one is checked below.
    assert set(slim["metadata_"]) == set(_LITE_METADATA_KEYS)
    # What the lists render or copy onto a BOQ position survives unchanged:
    # the variant count and common base, the cost split, the work steps.
    for key in _LITE_METADATA_KEYS:
        assert slim["metadata_"][key] == full["metadata_"][key], key
    for key in full:
        if key not in ("components", "metadata_"):
            assert slim[key] == full[key], key


def test_the_metadata_whitelist_holds_no_catalogue() -> None:
    # A deliberate change detector. Each key here is read by a list view or
    # copied onto a new BOQ position from a list row; a variant catalogue or a
    # component array belongs on ``GET /v1/costs/{id}`` instead.
    assert _LITE_METADATA_KEYS == (
        "variant_stats",
        "labor_cost",
        "material_cost",
        "equipment_cost",
        "other_cost",
        "labor_hours",
        "workers_per_unit",
        "scope_of_work",
    )


def test_a_page_of_slim_rows_is_a_small_fraction_of_the_full_page() -> None:
    full_page = [_full_row(seq) for seq in range(50)]
    slim_page = [_slim_list_row(copy.deepcopy(row)) for row in full_page]

    full_bytes = len(json.dumps({"items": full_page}, ensure_ascii=False).encode("utf-8"))
    slim_bytes = len(json.dumps({"items": slim_page}, ensure_ascii=False).encode("utf-8"))
    print(f"50 pack rows: full {full_bytes:,} bytes, slim {slim_bytes:,} bytes ({slim_bytes / full_bytes:.1%})")

    assert full_bytes > 500_000, "the fixture no longer looks like an imported pack"
    assert slim_bytes * 10 < full_bytes
