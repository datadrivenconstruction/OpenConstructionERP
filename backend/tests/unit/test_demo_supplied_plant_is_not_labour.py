# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A scanner priced in millions is the machine, not 45 % labour.

The generic split read 45 % of a 12.5M SAR MRI scanner as labour and turned it
into 178,571 hours on one position. Equipment supplied and installed by its
maker keeps a small installation share; the shielding of its room is building
work and keeps its own trade.
"""

from __future__ import annotations

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _enrich_position_metadata


def _position(demo_id: str, ordinal: str):
    template = DEMO_TEMPLATES[demo_id]
    for _o, _t, _c, items in template.sections:
        for item in items:
            if item[0] == ordinal:
                return template, item
    raise AssertionError(f"{demo_id} has no {ordinal}")


@pytest.mark.parametrize("ordinal", ["11.01", "11.02", "11.05", "13.01"])
def test_supplied_medical_plant_is_mostly_the_machine(ordinal):
    template, (_o, description, unit, quantity, rate, codes) = _position("hospital-jeddah", ordinal)
    meta = _enrich_position_metadata(description, unit, rate, codes, currency=template.currency)
    assert meta["cwicr_ref"] == "CWICR-SPE-003"
    hours = sum(r["quantity"] for r in meta["resources"] if r.get("unit") == "hr") * quantity
    # Weeks of a specialist crew, not years: under 5,000 hours a piece.
    assert hours / quantity < 5000


def test_the_shielding_of_a_scanner_room_stays_building_work():
    template, (_o, description, unit, _q, rate, codes) = _position("hospital-lyon", "10.2")
    meta = _enrich_position_metadata(description, unit, rate, codes, currency=template.currency)
    assert meta["cwicr_ref"] != "CWICR-SPE-003"
