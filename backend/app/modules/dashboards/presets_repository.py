"""Data access layer for dashboard presets / collections (T05).

Kept in a separate module from :mod:`.repository` so the snapshot path
isn't bloated with preset-specific filter logic. Tenant scoping mirrors
:class:`SnapshotRepository`: ``tenant_id=None`` bypasses the filter
(admin / unscoped reads), but the service layer never opts into that
for normal user requests.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboards.models import DashboardPreset


class DashboardPresetRepository:
    """Persistence surface for dashboard presets + collections."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------

    async def get(
        self,
        preset_id: uuid.UUID | str,
        *,
        tenant_id: str | None,
    ) -> DashboardPreset | None:
        """Return one preset by id, constrained to the caller's tenant."""
        stmt = select(DashboardPreset).where(
            DashboardPreset.id == _as_uuid(preset_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(DashboardPreset.tenant_id == str(tenant_id))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_visible(
        self,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
        project_id: uuid.UUID | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DashboardPreset], int]:
        """List every preset visible to ``owner_id``.

        Visibility rules:

        * Always include rows where ``owner_id`` matches (the user's own
          presets — both private and their published collections).
        * Additionally include rows where
          ``kind='collection' AND shared_with_project=True`` AND the
          row's ``project_id`` matches the requested project (if a
          project filter was supplied) — those are the public
          collections from other users on this project.

        Tenant scoping always applies on top.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        limit = min(limit, 500)

        own_clause = DashboardPreset.owner_id == owner_id

        shared_clauses = [
            DashboardPreset.kind == "collection",
            DashboardPreset.shared_with_project.is_(True),
        ]
        if project_id is not None:
            shared_clauses.append(
                DashboardPreset.project_id == project_id,
            )
        shared_clause = and_(*shared_clauses)

        base = select(DashboardPreset).where(or_(own_clause, shared_clause))
        if tenant_id is not None:
            base = base.where(DashboardPreset.tenant_id == str(tenant_id))
        if project_id is not None:
            # When the caller pinned a project, also restrict their own
            # rows to that project (or to global / project-less rows).
            base = base.where(
                or_(
                    DashboardPreset.project_id == project_id,
                    DashboardPreset.project_id.is_(None),
                ),
            )
        if kind is not None:
            base = base.where(DashboardPreset.kind == kind)

        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        rows_stmt = (
            base.order_by(DashboardPreset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(rows_stmt)).scalars().all()
        return list(rows), total

    # -- writes ------------------------------------------------------------

    async def add(self, preset: DashboardPreset) -> DashboardPreset:
        self.session.add(preset)
        await self.session.flush()
        return preset

    async def delete(self, preset: DashboardPreset) -> None:
        await self.session.delete(preset)
        await self.session.flush()


# ── helpers ─────────────────────────────────────────────────────────────────


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


__all__ = ["DashboardPresetRepository"]
