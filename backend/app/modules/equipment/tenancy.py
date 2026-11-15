# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Default tenant for fleet rows created without a request (seeds, backfill).

Single-tenant installs resolve the tenant to the owning user's id
(``app.core.tenant_scope``). With no request, the install owner is the oldest
active administrator; an install with no users yet falls back to ``"default"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

FALLBACK_TENANT = "default"


async def default_tenant_id(session: AsyncSession) -> str:
    """The install owner's tenant id, or :data:`FALLBACK_TENANT` on an empty install."""
    from app.modules.users.models import User

    owner = (
        await session.execute(
            select(User.id)
            .where(User.is_active.is_(True))
            .order_by((User.role == "admin").desc(), User.created_at, User.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return str(owner) if owner is not None else FALLBACK_TENANT
