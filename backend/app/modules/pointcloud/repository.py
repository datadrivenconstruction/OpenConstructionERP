# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud data access layer - one repository per entity.

Mirrors the ``geo_hub`` repository style: a tiny shared ``_BaseRepo`` for the
create / get / update / delete boilerplate, plus per-entity list queries that
are always scoped to a project and a tenant so a cross-tenant read can never
leak rows.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pointcloud.models import ScanDataset, ScanRegistration


class _BaseRepo:
    """Tiny shared helper - create / get / update / delete boilerplate."""

    model: type

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, entity_id)

    async def create(self, obj: Any) -> Any:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, entity_id: uuid.UUID, **fields: object) -> None:
        if not fields:
            return
        stmt = (
            update(self.model)
            .where(self.model.id == entity_id)  # type: ignore[attr-defined]
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        obj = await self.get_by_id(entity_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


# ── ScanDataset ──────────────────────────────────────────────────────────


class ScanDatasetRepository(_BaseRepo):
    """Data access for reality-capture scans."""

    model = ScanDataset

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ScanDataset]:
        """List scans for ``project_id`` belonging to ``tenant_id``.

        Both the project and the tenant are part of the WHERE clause so a row
        owned by another tenant can never be returned even if the same project
        id were somehow shared. ``status`` optionally narrows to one lifecycle
        state (``uploading`` / ``uploaded`` / ``converting`` / ``ready`` /
        ``failed``).
        """
        stmt = select(ScanDataset).where(ScanDataset.project_id == project_id).where(ScanDataset.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(ScanDataset.status == status)
        stmt = stmt.order_by(ScanDataset.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count_for_project(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
    ) -> int:
        """Total scan count for the project / tenant, for list pagination."""
        stmt = (
            select(func.count())
            .select_from(ScanDataset)
            .where(ScanDataset.project_id == project_id)
            .where(ScanDataset.tenant_id == tenant_id)
        )
        if status:
            stmt = stmt.where(ScanDataset.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def get_for_tenant(
        self,
        scan_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> ScanDataset | None:
        """Fetch one scan only when it belongs to ``tenant_id`` (else ``None``).

        This is the tenant-scoped read primitive the service uses; the router
        additionally runs the project-access IDOR guard.
        """
        stmt = select(ScanDataset).where(ScanDataset.id == scan_id).where(ScanDataset.tenant_id == tenant_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def set_status(self, scan_id: uuid.UUID, status: str) -> None:
        """Move a scan to a new lifecycle status."""
        await self.update_fields(scan_id, status=status)

    async def set_artifacts(
        self,
        scan_id: uuid.UUID,
        *,
        copc_uri: str | None = None,
        tileset_uri: str | None = None,
        dtm_uri: str | None = None,
    ) -> None:
        """Stamp the converter output URIs onto a scan.

        Only the URIs that are passed (non-``None``) are written, so a partial
        completion (COPC ready, tileset still pending) does not clobber the
        other columns.
        """
        fields: dict[str, object] = {}
        if copc_uri is not None:
            fields["copc_uri"] = copc_uri
        if tileset_uri is not None:
            fields["tileset_uri"] = tileset_uri
        if dtm_uri is not None:
            fields["dtm_uri"] = dtm_uri
        await self.update_fields(scan_id, **fields)


# ── ScanRegistration ─────────────────────────────────────────────────────


class ScanRegistrationRepository(_BaseRepo):
    """Data access for scan alignment / deviation results."""

    model = ScanRegistration

    async def list_for_scan(
        self,
        scan_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ScanRegistration]:
        stmt = (
            select(ScanRegistration)
            .where(ScanRegistration.scan_id == scan_id)
            .order_by(ScanRegistration.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


__all__ = [
    "ScanDatasetRepository",
    "ScanRegistrationRepository",
]
