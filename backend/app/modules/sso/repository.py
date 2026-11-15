# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO data access: providers and single-use values."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sso.models import SsoOneTime, SsoProvider


class SsoRepository:
    """Queries for :mod:`app.modules.sso`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_providers(self, *, enabled_only: bool = False) -> list[SsoProvider]:
        stmt = select(SsoProvider).order_by(SsoProvider.display_name)
        if enabled_only:
            stmt = stmt.where(SsoProvider.enabled.is_(True))
        return list((await self.session.execute(stmt)).scalars())

    async def get(self, provider_id: uuid.UUID) -> SsoProvider | None:
        return await self.session.get(SsoProvider, provider_id)

    async def by_slug(self, slug: str) -> SsoProvider | None:
        stmt = select(SsoProvider).where(SsoProvider.slug == slug)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def put_one_time(
        self, kind: str, value: str, slug: str, expires_at: datetime, data: dict[str, Any] | None = None
    ) -> None:
        self.session.add(SsoOneTime(kind=kind, value=value, provider_slug=slug, expires_at=expires_at, data=data or {}))
        await self.session.flush()

    async def take_one_time(self, kind: str, value: str, slug: str) -> SsoOneTime | None:
        """Delete and return a live value; None when absent, expired or for another provider."""
        stmt = select(SsoOneTime).where(SsoOneTime.kind == kind, SsoOneTime.value == value).with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        await self.session.delete(row)
        await self.session.flush()
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if row.provider_slug != slug or expires <= datetime.now(UTC):
            return None
        return row

    async def exists_one_time(self, kind: str, value: str) -> bool:
        stmt = select(SsoOneTime.id).where(SsoOneTime.kind == kind, SsoOneTime.value == value)
        return (await self.session.execute(stmt)).first() is not None

    async def purge_expired(self) -> None:
        await self.session.execute(delete(SsoOneTime).where(SsoOneTime.expires_at < datetime.now(UTC)))
