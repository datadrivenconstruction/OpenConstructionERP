# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Relinking cannot keep the prior catalogue's provenance for an unresolved item."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.boq import price_list_carry


@pytest.mark.parametrize("replace", [False, True])
async def test_unresolved_new_link_drops_previous_provenance_only_on_replacement(monkeypatch, replace):
    metadata = {
        "cost_item_id": str(uuid.uuid4()),
        "prezzario": {"region": "Toscana", "edition": "2025"},
        "resources": [{"name": "Original resource", "quantity": 3}],
    }
    # Missing and retired items both resolve to None at this boundary.
    monkeypatch.setattr(price_list_carry, "load_cost_item", AsyncMock(return_value=None))
    await price_list_carry.carry_from_link(object(), metadata, replace=replace)
    assert ("prezzario" in metadata) is not replace
    assert metadata["resources"] == [{"name": "Original resource", "quantity": 3}]
