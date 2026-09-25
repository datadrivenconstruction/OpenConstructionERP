# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost picker states the rate the bill line will receive.

The "From Database" picker showed the catalogue ``rate`` while the add flow
priced the new line from the item's components, so a row listed at one price
landed in the bill at another. ``buildup_rate`` is the figure the add flow
writes, computed the way the add flow computes it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.modules.costs.buildup import buildup_rate, has_variant_slot
from app.modules.costs.schemas import CostItemResponse

# Two rows shaped like an imported catalogue: the component costs are the
# source's own figures and are not quantity x price of the rounded columns.
_COMPONENTS = [
    {"name": "Worker", "unit": "h", "quantity": 24.38, "unit_rate": 19.67, "cost": 479.59, "type": "labor"},
    {"name": "Nails", "unit": "kg", "quantity": 0.0, "unit_rate": 15107.19, "cost": 12.84, "type": "material"},
    {"name": "Profile", "unit": "m", "quantity": 2, "unit_rate": 9.34, "type": "material"},
]


def test_the_rate_is_the_sum_the_add_flow_writes() -> None:
    # 479.59 + 12.84 + 2 x 9.34 (no cost on the row, so quantity x rate)
    assert buildup_rate(_COMPONENTS, {}) == Decimal("511.11")


def test_an_item_without_components_has_no_buildup() -> None:
    assert buildup_rate([], {}) is None


def test_a_variant_slot_leaves_the_rate_to_the_pick() -> None:
    stats = {"mean": 5, "median": 5, "count": 2}
    variants = [{"label": "a", "price": 4}, {"label": "b", "price": 6}]
    with_component_slot = [
        *_COMPONENTS,
        {"name": "Board", "available_variants": variants, "available_variant_stats": stats},
    ]
    assert has_variant_slot(with_component_slot, {})
    assert buildup_rate(with_component_slot, {}) is None
    assert buildup_rate(_COMPONENTS, {"variants": variants, "variant_stats": stats}) is None


def test_the_response_carries_it_next_to_the_catalogue_rate() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        code="MESA_KAME",
        description="Frame wall",
        descriptions={},
        unit="m2",
        rate="500.00",
        currency="CAD",
        source="cwicr",
        classification={},
        components=_COMPONENTS,
        tags=[],
        region="ENG_TORONTO",
        mass_per_unit="",
        mass_basis="",
        catalog_id=None,
        is_active=True,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payload = CostItemResponse.model_validate(row).model_dump(by_alias=True, mode="json")
    assert payload["rate"] == "500.00"
    assert payload["buildup_rate"] == "511.11"
