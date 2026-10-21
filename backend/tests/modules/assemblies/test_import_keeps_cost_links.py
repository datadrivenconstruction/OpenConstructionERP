# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export then import keeps each component's link to its cost item."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assemblies.schemas import AssemblyCreate, AssemblyExport, ComponentCreate
from app.modules.assemblies.service import AssemblyService
from app.modules.costs.models import CostItem
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _cost_item(session: AsyncSession, *, active: bool = True) -> CostItem:
    item = CostItem(
        code=f"C-{uuid.uuid4().hex[:8]}",
        description="Concrete C30/37",
        unit="m3",
        rate="120.00",
        currency="EUR",
        source="cwicr",
        is_active=active,
    )
    session.add(item)
    await session.flush()
    return item


async def test_round_trip_keeps_cost_item_id(session: AsyncSession) -> None:
    service = AssemblyService(session)
    item = await _cost_item(session)
    asm = await service.create_assembly(
        AssemblyCreate(code=f"A-{uuid.uuid4().hex[:6]}", name="Wall", unit="m2"), owner_id=str(uuid.uuid4())
    )
    await service.add_component(
        asm.id,
        ComponentCreate(
            description="Concrete", unit="m3", quantity=1.0, unit_cost=Decimal("120"), cost_item_id=item.id
        ),
    )
    payload = await service.export_assembly(asm.id)
    assert payload["components"][0]["cost_item_id"] == str(item.id)

    warnings: list[str] = []
    imported = await service.import_assembly(AssemblyExport(**payload), owner_id=None, warnings=warnings)
    comps = await service.component_repo.list_for_assembly(imported.id)
    assert [c.cost_item_id for c in comps] == [item.id]
    assert warnings == []


async def test_unknown_or_inactive_cost_item_imports_unlinked_with_warning(session: AsyncSession) -> None:
    service = AssemblyService(session)
    inactive = await _cost_item(session, active=False)
    export = AssemblyExport(
        code=f"A-{uuid.uuid4().hex[:6]}",
        name="Wall",
        unit="m2",
        components=[
            {"description": "Ghost", "unit": "m3", "cost_item_id": str(uuid.uuid4())},
            {"description": "Retired", "unit": "m3", "cost_item_id": str(inactive.id)},
            {"description": "Junk", "unit": "m3", "cost_item_id": "not-a-uuid"},
        ],
    )
    warnings: list[str] = []
    imported = await service.import_assembly(export, owner_id=None, warnings=warnings)
    comps = await service.component_repo.list_for_assembly(imported.id)
    assert [c.cost_item_id for c in comps] == [None, None, None]
    assert warnings == [f"components[{i}]: cost_item_id not found, imported unlinked" for i in range(3)]
