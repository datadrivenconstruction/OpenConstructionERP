# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the plant register PostgreSQL tests.

A world is a throwaway database with real users, a project with the governance
``elf_module_framework`` model pinned (its document type ``m04_equipment_frame``
hosts plant, so area ``m04_equipment`` is the hosting area, owned by ``area_owner``), an approval route for ``plant_decision_paper`` whose single
step names the approver, and an in-memory package plan provider standing in
for the delivery-model module (two packages: one that supplies and installs,
one that only installs). Everything commits for real.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.plant_register.ports import (
    OwnerFurnishedRef,
    PackagePlan,
    PackageRef,
    register_package_plan_provider,
)
from app.modules.plant_register.service import PlantService
from tests.pg.governance_fixtures import add_project, add_route, add_user


@dataclass
class FakePlanProvider:
    """The delivery-model port, idempotent on the plant item id like the real one must be."""

    plans: dict[uuid.UUID, PackagePlan] = field(default_factory=dict)
    ofis: dict[uuid.UUID, OwnerFurnishedRef] = field(default_factory=dict)
    by_item: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    ensure_calls: int = 0
    released: list[uuid.UUID] = field(default_factory=list)

    async def package_plan(self, session: Any, project_id: uuid.UUID) -> PackagePlan | None:
        return self.plans.get(project_id)

    async def ensure_owner_furnished_item(
        self, session: Any, project_id: uuid.UUID, *, plant_item_id, title, installer_package_id, actor_id
    ) -> OwnerFurnishedRef:
        self.ensure_calls += 1
        ofi_id = self.by_item.get(plant_item_id) or uuid.uuid4()
        self.by_item[plant_item_id] = ofi_id
        prev = self.ofis.get(ofi_id)
        ref = OwnerFurnishedRef(ofi_id, installer_package_id, prev.progress if prev else "none")
        self.ofis[ofi_id] = ref
        return ref

    async def release_owner_furnished_item(self, session: Any, project_id: uuid.UUID, *, plant_item_id, actor_id):
        self.released.append(plant_item_id)
        self.ofis.pop(self.by_item.pop(plant_item_id, None), None)

    async def get_owner_furnished_item(self, session: Any, project_id: uuid.UUID, ofi_id: uuid.UUID):
        return self.ofis.get(ofi_id)

    def set_progress(self, ofi_id: uuid.UUID, progress: str) -> None:
        ref = self.ofis[ofi_id]
        self.ofis[ofi_id] = OwnerFurnishedRef(ref.id, ref.installer_package_id, progress)


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    area_owner: uuid.UUID
    editor: uuid.UUID
    approver: uuid.UUID
    outsider: uuid.UUID
    provider: FakePlanProvider
    supplier_pkg: uuid.UUID
    installer_pkg: uuid.UUID
    route_id: uuid.UUID | None = None


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, provider: FakePlanProvider | None = None, model: bool = True
) -> World:
    """The plant test world. ``model=False`` leaves the project without a phase model: no gates, no areas."""
    from sqlalchemy import select

    from app.modules.plant_register.catalogue import register_plant_kind
    from app.modules.project_governance.models import GovernanceArea
    from app.modules.project_governance.service import GovernanceService

    register_plant_kind()
    provider = provider or FakePlanProvider()
    register_package_plan_provider(provider)
    async with factory() as s:
        manager = await add_user(s, "manager")
        area_owner = await add_user(s, "editor")
        editor = await add_user(s, "editor")
        approver = await add_user(s, "manager")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [area_owner, editor, approver])
        if model:
            await GovernanceService(s).set_model(
                pid,
                source="shipped",
                catalogue_id="elf_module_framework",
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
            area = (
                await s.execute(
                    select(GovernanceArea).where(
                        GovernanceArea.project_id == pid, GovernanceArea.code == "m04_equipment"
                    )
                )
            ).scalar_one()
            area.owner_user_id = area_owner
        route_id = await add_route(s, pid, "plant_decision_paper", approver)
        await s.commit()
    sup, ins = uuid.uuid4(), uuid.uuid4()
    provider.plans[pid] = PackagePlan(
        "multi_package",
        (
            PackageRef(sup, "P-EL", "Electrical works", True, True),
            PackageRef(ins, "P-INST", "Installation", False, True),
        ),
    )
    return World(factory, pid, manager, area_owner, editor, approver, outsider, provider, sup, ins, route_id)


async def item(w: World, code: str = "PL-1", cls: str = "mv_switchgear", **extra: Any) -> uuid.UUID:
    async with w.factory() as s:
        row = await PlantService(s).create_item(
            w.project_id,
            {"code": code, "title": f"Item {code}", "component_class_code": cls, **extra},
            actor_id=w.area_owner,
        )
        await s.commit()
        return row.id


async def quote(w: World, item_id: uuid.UUID, today: date = date(2026, 10, 11), **kw: Any):
    data = {
        "source": "supplier_quote",
        "source_name": "Manufacturer A",
        "enquiry_date": date(2026, 8, 3),
        "lead_weeks_min": 40,
        "lead_weeks_max": 44,
        **kw,
    }
    async with w.factory() as s:
        q = await PlantService(s).add_quote(w.project_id, item_id, data, actor_id=w.area_owner, today=today)
        await s.commit()
        return q


async def get(w: World, model: Any, row_id: uuid.UUID) -> Any:
    async with w.factory() as s:
        return await s.get(model, row_id)


async def view(w: World, item_id: uuid.UUID, today: date = date(2026, 10, 11)) -> dict[str, Any]:
    async with w.factory() as s:
        return (await PlantService(s).item_views(w.project_id, today=today, only=[item_id]))[0]
