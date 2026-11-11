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
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.boq.router import OWN_EPD_PREFIX, _own_epd_materials
from app.modules.carbon.models import EPDRecord
from app.modules.carbon.service import CarbonService


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
                    tenant_id="tenant-a",
                ),
                EPDRecord(
                    epd_id="own-b-secret",
                    source="custom",
                    material_class="concrete",
                    product_name="Tenant B secret mix",
                    declared_unit="m3",
                    gwp_a1a3=Decimal("99"),
                    tenant_id="tenant-b",
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
    items = await _own_epd_materials(session, tenant_id="tenant-a")
    assert [m["id"] for m in items] == [f"{OWN_EPD_PREFIX}own-recycled-c30"]
    own = items[0]
    assert own["gwp"] == pytest.approx(180.5)
    assert own["unit"] == "m3"
    assert own["category"] == "concrete"
    assert own["own"] is True


async def test_filters_and_lookup_by_id(session) -> None:
    assert await _own_epd_materials(session, tenant_id="tenant-a", category="steel") == []
    assert len(await _own_epd_materials(session, tenant_id="tenant-a", query="recycled")) == 1
    assert await _own_epd_materials(session, tenant_id="tenant-a", query="timber") == []
    found = await _own_epd_materials(session, tenant_id="tenant-a", epd_id="own-recycled-c30")
    assert found[0]["name"] == "Recycled concrete C30/37"


async def test_another_tenants_material_never_reaches_the_picker(session) -> None:
    assert await _own_epd_materials(session, tenant_id="tenant-a", epd_id="own-b-secret") == []
    assert [m["name"] for m in await _own_epd_materials(session, tenant_id="tenant-b")] == ["Tenant B secret mix"]
    assert await _own_epd_materials(session, tenant_id=None) == []


async def test_carbon_epd_library_is_tenant_scoped(session) -> None:
    svc = CarbonService(session)
    items, _ = await svc.list_epds(tenant_id="tenant-a", scoped=True)
    names = {i.product_name for i in items}
    assert names == {"Recycled concrete C30/37", "Steel rebar"}
    secret = next(i for i in (await svc.list_epds())[0] if i.epd_id == "own-b-secret")
    for call in (
        svc.get_epd(secret.id, tenant_id="tenant-a", scoped=True),
        svc.delete_epd(secret.id, tenant_id="tenant-a", scoped=True),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404
    assert (await svc.get_epd(secret.id, tenant_id="tenant-b", scoped=True)).product_name == "Tenant B secret mix"
