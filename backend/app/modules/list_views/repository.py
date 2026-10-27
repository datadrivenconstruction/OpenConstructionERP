# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views data access. Every query is bounded by the caller's tenant."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.list_views.models import ListView


class ListViewRepository:
    """Queries for list views; never returns a row of another tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_visible(self, *, tenant_id: str, user_id: uuid.UUID, scope_key: str) -> list[ListView]:
        """Own views plus views shared within the tenant, for one page."""
        stmt = (
            select(ListView)
            .where(
                ListView.tenant_id == tenant_id,
                ListView.scope_key == scope_key,
                or_(ListView.user_id == user_id, ListView.is_shared.is_(True)),
            )
            .order_by(ListView.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_visible(self, view_id: uuid.UUID, *, tenant_id: str, user_id: uuid.UUID) -> ListView | None:
        """One view the caller may see, or None."""
        stmt = select(ListView).where(
            ListView.id == view_id,
            ListView.tenant_id == tenant_id,
            or_(ListView.user_id == user_id, ListView.is_shared.is_(True)),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_by_name(self, *, user_id: uuid.UUID, scope_key: str, name: str) -> ListView | None:
        """The caller's own view with this name on this page."""
        stmt = select(ListView).where(
            ListView.user_id == user_id, ListView.scope_key == scope_key, ListView.name == name
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def clear_default(self, *, user_id: uuid.UUID, scope_key: str, keep: uuid.UUID | None = None) -> None:
        """Unmark the caller's default view on a page, except ``keep``."""
        stmt = update(ListView).where(ListView.user_id == user_id, ListView.scope_key == scope_key)
        if keep is not None:
            stmt = stmt.where(ListView.id != keep)
        await self.session.execute(stmt.values(is_default=False))

    async def add(self, view: ListView) -> ListView:
        self.session.add(view)
        await self.session.flush()
        await self.session.refresh(view)
        return view

    async def delete(self, view: ListView) -> None:
        await self.session.delete(view)
        await self.session.flush()
