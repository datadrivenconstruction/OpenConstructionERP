# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the plant rate catalogue."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment
from app.modules.equipment.rate_models import EquipmentRateCatalogue, EquipmentRateItem, EquipmentRateProfile


class RateRepository:
    """Catalogues, their machines and the saved import layouts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # catalogues
    async def list_catalogues(self) -> list[EquipmentRateCatalogue]:
        stmt = select(EquipmentRateCatalogue).order_by(
            EquipmentRateCatalogue.valid_from.desc(), EquipmentRateCatalogue.created_at.desc()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_catalogue(self, catalogue_id: uuid.UUID) -> EquipmentRateCatalogue | None:
        return await self.session.get(EquipmentRateCatalogue, catalogue_id)

    async def add_catalogue(self, catalogue: EquipmentRateCatalogue) -> EquipmentRateCatalogue:
        self.session.add(catalogue)
        await self.session.flush()
        return catalogue

    async def update_catalogue(self, catalogue: EquipmentRateCatalogue, fields: dict[str, Any]) -> None:
        for key, value in fields.items():
            setattr(catalogue, key, value)
        await self.session.flush()

    async def delete_catalogue(self, catalogue: EquipmentRateCatalogue) -> None:
        await self.session.execute(delete(EquipmentRateItem).where(EquipmentRateItem.catalogue_id == catalogue.id))
        await self.session.delete(catalogue)
        await self.session.flush()

    async def counts_by_catalogue(self) -> dict[uuid.UUID, tuple[int, int]]:
        """Catalogue id -> (machines, assets using one of its machines)."""
        machines = (
            await self.session.execute(
                select(EquipmentRateItem.catalogue_id, func.count()).group_by(EquipmentRateItem.catalogue_id)
            )
        ).all()
        assets = (
            await self.session.execute(
                select(EquipmentRateItem.catalogue_id, func.count(Equipment.id))
                .join(Equipment, Equipment.rate_item_id == EquipmentRateItem.id)
                .group_by(EquipmentRateItem.catalogue_id)
            )
        ).all()
        used = {cid: n for cid, n in assets}
        return {cid: (n, used.get(cid, 0)) for cid, n in machines}

    # items
    async def list_items(self, catalogue_id: uuid.UUID) -> list[EquipmentRateItem]:
        stmt = select(EquipmentRateItem).where(EquipmentRateItem.catalogue_id == catalogue_id)
        return list((await self.session.execute(stmt.order_by(EquipmentRateItem.code))).scalars().all())

    async def get_item(self, item_id: uuid.UUID) -> EquipmentRateItem | None:
        return await self.session.get(EquipmentRateItem, item_id)

    async def get_item_by_code(self, catalogue_id: uuid.UUID, code: str) -> EquipmentRateItem | None:
        stmt = select(EquipmentRateItem).where(
            EquipmentRateItem.catalogue_id == catalogue_id, EquipmentRateItem.code == code
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_item(self, item: EquipmentRateItem) -> EquipmentRateItem:
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_item(self, item: EquipmentRateItem, fields: dict[str, Any]) -> None:
        for key, value in fields.items():
            setattr(item, key, value)
        await self.session.flush()

    async def delete_item(self, item: EquipmentRateItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    async def assets_by_item(self, catalogue_id: uuid.UUID) -> dict[uuid.UUID, int]:
        stmt = (
            select(Equipment.rate_item_id, func.count())
            .join(EquipmentRateItem, EquipmentRateItem.id == Equipment.rate_item_id)
            .where(EquipmentRateItem.catalogue_id == catalogue_id)
            .group_by(Equipment.rate_item_id)
        )
        return {iid: n for iid, n in (await self.session.execute(stmt)).all()}

    # import profiles
    async def list_profiles(self) -> list[EquipmentRateProfile]:
        stmt = select(EquipmentRateProfile).order_by(EquipmentRateProfile.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_profile_by_name(self, name: str) -> EquipmentRateProfile | None:
        stmt = select(EquipmentRateProfile).where(EquipmentRateProfile.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_profile(self, profile: EquipmentRateProfile) -> EquipmentRateProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def delete_profile(self, profile: EquipmentRateProfile) -> None:
        await self.session.delete(profile)
        await self.session.flush()
