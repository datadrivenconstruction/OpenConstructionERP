# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A material the user adds as a custom carbon EPD record shows up in the sustainability picker.

The picker (GET /v1/boq/epd-materials/) merges ``source=custom`` rows of
``oe_carbon_epd_record`` ahead of the embedded reference set, under an
``own:`` id that the position assign route resolves again.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.boq.router import OWN_EPD_PREFIX, _own_epd_materials
from app.modules.carbon.models import EPDRecord


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(EPDRecord.__table__.create)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add_all(
            [
                EPDRecord(
                    epd_id="own-recycled-c30",
                    source="custom",
                    material_class="concrete",
                    product_name="Recycled concrete C30/37",
                    declared_unit="m3",
                    gwp_a1a3=Decimal("180.5"),
                ),
                EPDRecord(
                    epd_id="ice-steel",
                    source="ice",
                    material_class="steel",
                    product_name="Steel rebar",
                    declared_unit="kg",
                    gwp_a1a3=Decimal("1.99"),
                ),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


async def test_only_custom_records_are_offered_as_own(session) -> None:
    items = await _own_epd_materials(session)
    assert [m["id"] for m in items] == [f"{OWN_EPD_PREFIX}own-recycled-c30"]
    own = items[0]
    assert own["gwp"] == pytest.approx(180.5)
    assert own["unit"] == "m3"
    assert own["category"] == "concrete"
    assert own["own"] is True


async def test_filters_and_lookup_by_id(session) -> None:
    assert await _own_epd_materials(session, category="steel") == []
    assert len(await _own_epd_materials(session, query="recycled")) == 1
    assert await _own_epd_materials(session, query="timber") == []
    found = await _own_epd_materials(session, epd_id="own-recycled-c30")
    assert found[0]["name"] == "Recycled concrete C30/37"
