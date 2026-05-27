# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Compliance documents data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_docs.models import ComplianceDoc


class ComplianceDocRepository:
    """‌⁠‍Data access for :class:`ComplianceDoc` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self,
        doc_id: uuid.UUID,
    ) -> ComplianceDoc | None:
        return await self.session.get(ComplianceDoc, doc_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        doc_type: str | None = None,
    ) -> list[ComplianceDoc]:
        stmt = select(ComplianceDoc).where(ComplianceDoc.project_id == project_id)
        if status is not None:
            stmt = stmt.where(ComplianceDoc.status == status)
        if doc_type is not None:
            stmt = stmt.where(ComplianceDoc.doc_type == doc_type)
        # Sort by expiry ascending so the most-urgent rows are first —
        # the same default the UI uses, so the table renders without
        # client-side resorting.
        stmt = stmt.order_by(ComplianceDoc.expires_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[ComplianceDoc]:
        stmt = (
            select(ComplianceDoc)
            .where(
                ComplianceDoc.project_id == project_id,
                ComplianceDoc.status.in_(("expiring_soon", "expired")),
            )
            .order_by(ComplianceDoc.expires_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, doc: ComplianceDoc) -> ComplianceDoc:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_fields(
        self,
        doc_id: uuid.UUID,
        **fields: object,
    ) -> None:
        stmt = update(ComplianceDoc).where(ComplianceDoc.id == doc_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc is not None:
            await self.session.delete(doc)
            await self.session.flush()
